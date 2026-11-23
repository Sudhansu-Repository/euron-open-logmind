# ─────────────────────────────────────────────────────────────────────────────
# aws-dev: a full, cheaper copy of production. Two AZs, single NAT, single-AZ
# database, one cache node, no deletion protection, small autoscaling ceilings.
#
# ClickHouse, the log store, runs on one EC2 instance in a private subnet (AWS has no
# managed ClickHouse; see modules/clickhouse). Its CLICKHOUSE_URL, like DATABASE_URL and
# REDIS_URL, reaches the tasks only through Secrets Manager.
#
# Validate-only in this repository (nothing is ever applied to a real account by
# the project itself); everything needed to deploy is here:
#   cp terraform.tfvars.example terraform.tfvars   # then edit
#   make aws-deploy ENV=aws-dev TAG=0.1.0   # registries, images, infrastructure,
#                                           # migrations, then the services
# ─────────────────────────────────────────────────────────────────────────────

module "kms" {
  source                  = "../../modules/kms"
  name_prefix             = var.name_prefix
  deletion_window_in_days = 7
}

module "network" {
  source                     = "../../modules/network"
  name_prefix                = var.name_prefix
  az_count                   = 2
  single_nat_gateway         = true
  enable_interface_endpoints = false
  logs_kms_key_arn           = module.kms.key_arn
  flow_log_retention_days    = 14
}

module "database" {
  source                = "../../modules/database"
  name_prefix           = var.name_prefix
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.private_subnet_ids
  kms_key_arn           = module.kms.key_arn
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = 200
  multi_az              = false
  backup_retention_days = 3
  deletion_protection   = false
  skip_final_snapshot   = true
}

module "cache" {
  source                  = "../../modules/cache"
  name_prefix             = var.name_prefix
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  kms_key_arn             = module.kms.key_arn
  logs_kms_key_arn        = module.kms.key_arn
  node_type               = var.cache_node_type
  num_cache_clusters      = 1
  recovery_window_in_days = 0
  log_retention_days      = 14
  apply_immediately       = true
}

module "clickhouse" {
  source         = "../../modules/clickhouse"
  name_prefix    = var.name_prefix
  vpc_id         = module.network.vpc_id
  subnet_id      = module.network.private_subnet_ids[0]
  kms_key_arn    = module.kms.key_arn
  instance_type  = var.clickhouse_instance_type
  data_volume_gb = var.clickhouse_data_volume_gb
  ami_id         = var.clickhouse_ami_id
}

module "storage" {
  source                   = "../../modules/storage"
  name_prefix              = var.name_prefix
  kms_key_arn              = module.kms.key_arn
  evidence_expiration_days = var.evidence_expiration_days
  force_destroy            = true
}

module "secrets" {
  source                  = "../../modules/secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = 0
  include_connection_urls = true
  database_url            = module.database.connection_url
  redis_url               = module.cache.connection_url
  clickhouse_url          = module.clickhouse.connection_url
}

module "ecr" {
  source       = "../../modules/ecr"
  name_prefix  = var.name_prefix
  kms_key_arn  = module.kms.key_arn
  force_delete = true
}

module "email" {
  source          = "../../modules/email"
  name_prefix     = var.name_prefix
  domain          = var.mail_domain
  from_address    = var.mail_from_address
  route53_zone_id = var.route53_zone_id
}

locals {
  url = "https://${var.hostname}"

  # Everything the api, worker and migrate read that is not a secret
  # (apps/api/src/logmind/core/config.py). Secrets (SESSION_SECRET, API_KEY_PEPPER,
  # DATABASE_URL, REDIS_URL, CLICKHOUSE_URL) come from module.secrets; PORT, PUBLIC_URL,
  # EVIDENCE_BUCKET and WORKER_METRICS_PORT from module.service. AWS_ENDPOINT_URL stays
  # unset on AWS.
  api_environment = merge({
    ENVIRONMENT   = "production"
    LOGMIND_CLOUD = "aws"
    LOG_LEVEL     = "INFO"
    AWS_REGION    = var.region
    KEY_MODE      = "kms"
    KMS_KEY_ID    = module.kms.alias_name
    STORAGE       = "s3"
    CORS_ORIGINS  = local.url
    COOKIE_SECURE = "true"
    # Longer than the ALB idle timeout (300 s), and X-Forwarded-For trusted only from
    # inside the VPC (the load balancer).
    HTTP_KEEP_ALIVE_S   = "310"
    FORWARDED_ALLOW_IPS = module.network.vpc_cidr_block
    SIGNUP_ENABLED      = tostring(var.signup_enabled)
    MAIL_BACKEND        = "ses"
    MAIL_FROM           = "${var.mail_from_name} <${var.mail_from_address}>"
    # Model providers on private addresses (a self-hosted Ollama or vLLM). Off by
    # default on AWS: the VPC also holds the database, the cache and ClickHouse.
    PROVIDER_ALLOW_PRIVATE = tostring(var.provider_allow_private)
    ALERT_INTERVAL_S       = tostring(var.alert_interval_s)
    # Pool sized so (api_max + worker_max + migrate) x (pool + overflow) stays under
    # db_max_connections.
    DB_POOL_SIZE    = "5"
    DB_MAX_OVERFLOW = "5"
  }, var.api_extra_environment)
}

module "service" {
  source             = "../../modules/service"
  name_prefix        = var.name_prefix
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  hostname           = var.hostname
  certificate_arn    = var.certificate_arn
  route53_zone_id    = var.route53_zone_id

  server_image  = "${module.ecr.repository_urls["server"]}:${var.image_tag}"
  web_image     = "${module.ecr.repository_urls["web"]}:${var.image_tag}"
  migrate_image = "${module.ecr.repository_urls["server"]}:${coalesce(var.migrate_image_tag, var.image_tag)}"

  environment      = local.api_environment
  secrets          = module.secrets.ecs_secrets
  migrate_secrets  = module.secrets.bootstrap_secrets
  send_mail        = true
  mail_policy_json = module.email.send_policy_json

  kms_key_arn                  = module.kms.key_arn
  evidence_bucket_arn          = module.storage.bucket_arn
  evidence_bucket_name         = module.storage.bucket_name
  db_security_group_id         = module.database.security_group_id
  db_port                      = module.database.port
  cache_security_group_id      = module.cache.security_group_id
  clickhouse_security_group_id = module.clickhouse.security_group_id
  clickhouse_port              = module.clickhouse.port
  log_group_names              = module.observability.log_group_names
  logs_kms_key_arn             = module.kms.key_arn

  api_cpu          = 512
  api_memory       = 2048
  api_min_count    = 1
  api_max_count    = 2
  worker_cpu       = 1024
  worker_memory    = 2048
  worker_min_count = 1
  worker_max_count = 2
  web_min_count    = 1
  web_max_count    = 2

  deletion_protection    = false
  enable_waf             = true
  waf_log_retention_days = 14
  metrics_allowed_cidrs  = var.metrics_allowed_cidrs
  worker_metrics_cidrs   = var.worker_metrics_cidrs
}

module "observability" {
  source             = "../../modules/observability"
  name_prefix        = var.name_prefix
  log_retention_days = 14
  logs_kms_key_arn   = module.kms.key_arn
  sns_kms_key_arn    = module.kms.key_arn
  alarm_email        = var.alarm_email

  alb_arn_suffix   = module.service.alb_arn_suffix
  ecs_cluster_name = module.service.cluster_name
  lb_services      = module.service.services
  ecs_services     = module.service.service_names

  db_instance_identifier     = module.database.instance_identifier
  db_max_connections         = 100
  cache_replication_group_id = module.cache.replication_group_id
  clickhouse_instance_id     = module.clickhouse.instance_id
  cache_node_count           = 1
}

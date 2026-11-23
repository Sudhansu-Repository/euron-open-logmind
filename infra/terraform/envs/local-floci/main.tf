# ─────────────────────────────────────────────────────────────────────────────
# Local environment on the Floci AWS emulator.
#
# The modules that build production run here unchanged; only the provider endpoints
# differ. `make up` applies this automatically (the compose `tf-local-floci` one-shot)
# before migrate, api and worker start, so local development uses KMS, S3 and Secrets
# Manager exactly as AWS does. By hand, against a running emulator:
#
#   terraform -chdir=infra/terraform/envs/local-floci init
#   terraform -chdir=infra/terraform/envs/local-floci apply -var endpoint=http://localhost:6066
#
# Postgres, Redis and ClickHouse are plain Compose containers locally (the emulator does
# not back RDS or ElastiCache, and a ClickHouse instance is not an AWS API). Their AWS
# counterparts, RDS, ElastiCache and ClickHouse on EC2, together with the network, ecr,
# service and observability modules, are covered by aws-dev and aws-prod
# (make tf-validate, make tf-aws-on-floci).
# ─────────────────────────────────────────────────────────────────────────────

module "kms" {
  source                  = "../../modules/kms"
  name_prefix             = var.name_prefix
  deletion_window_in_days = 7
}

module "storage" {
  source        = "../../modules/storage"
  name_prefix   = var.name_prefix
  kms_key_arn   = module.kms.key_arn
  enforce_tls   = false # the emulator speaks plain HTTP
  force_destroy = true
  cors_origins  = var.cors_origins
}

# Generated secrets are an AWS-deployment concern; locally compose reads
# deploy/compose/.env (make env). Created here anyway so the module is exercised against
# a real Secrets Manager API (the app secret and the create-admin bootstrap secret).
module "secrets" {
  source                  = "../../modules/secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = 0
}

# The SES identity and configuration set the api and worker send through with
# MAIL_BACKEND=ses (the Floci overlay's default is smtp against Mailpit instead).
module "email" {
  source       = "../../modules/email"
  name_prefix  = var.name_prefix
  domain       = var.mail_domain
  from_address = var.mail_from_address
}

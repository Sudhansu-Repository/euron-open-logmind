output "url" {
  description = "Public URL (the dashboard, with the API under /api, the live tail WebSocket at /api/v1/logs/live and OTLP/HTTP log ingestion at /v1/logs)."
  value       = module.service.url
}

output "load_balancer_dns_name" {
  description = "CNAME target for the host name when the zone is not in Route53."
  value       = module.service.alb_dns_name
}

output "cluster_name" {
  description = "ECS cluster of the api, worker and web."
  value       = module.service.cluster_name
}

output "services" {
  description = "ECS service names."
  value       = module.service.service_names
}

output "ecr_repositories" {
  description = "Image repositories (server, web)."
  value       = module.ecr.repository_urls
}

output "run_task" {
  description = "Parameters for one-off tasks (migrate, create-admin, seed-demo)."
  value       = module.service.run_task
}

output "evidence_bucket" {
  description = "AI investigation evidence bucket (EVIDENCE_BUCKET)."
  value       = module.storage.bucket_name
}

output "clickhouse_instance_id" {
  description = "ClickHouse instance (operator access: aws ssm start-session --target <id>)."
  value       = module.clickhouse.instance_id
}

output "kms_key_alias" {
  description = "KMS key alias (KMS_KEY_ID)."
  value       = module.kms.alias_name
}

output "dkim_records" {
  description = "DKIM CNAMEs for the mail domain (already published when route53_zone_id is set)."
  value       = module.email.dkim_records
}

output "dashboard_name" {
  description = "CloudWatch dashboard."
  value       = module.observability.dashboard_name
}

output "image_tag" {
  description = "The image tag the services run (aws-deploy.sh holds them on it while the next release migrates)."
  value       = var.image_tag
}

output "bootstrap_secret_arn" {
  description = "Secret the one-off create-admin task reads the first owner's password from (scripts/aws-run-task.sh)."
  value       = module.secrets.bootstrap_secret_arn
}

output "alarm_topic_arn" {
  description = "SNS topic every alarm publishes to."
  value       = module.observability.alarm_topic_arn
}

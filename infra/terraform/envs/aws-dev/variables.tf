variable "region" {
  description = "AWS region."
  type        = string
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "dev"
}

variable "extra_tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}

variable "name_prefix" {
  description = "Prefix for every resource name (at most 24 characters); the bucket name derives from it, so make it globally unique (e.g. \"acme-logmind-dev\")."
  type        = string
}

variable "hostname" {
  description = "Public host name of the dashboard and API, e.g. logmind-dev.example.com."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate in the same region covering hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for the alias record and the DKIM records. Null: create them yourself (load_balancer_dns_name and dkim_records outputs)."
  type        = string
  default     = null
}

variable "mail_domain" {
  description = "Domain alert notification mail is sent from (an SES domain identity), e.g. logmind-dev.example.com."
  type        = string
}

variable "mail_from_address" {
  description = "From address of LogMind mail, on mail_domain (the address inside MAIL_FROM; the SES send policy allows only it), e.g. alerts@logmind-dev.example.com."
  type        = string
}

variable "mail_from_name" {
  description = "Display name on outgoing mail (MAIL_FROM is \"<mail_from_name> <mail_from_address>\")."
  type        = string
  default     = "LogMind Alerts"
}

variable "signup_enabled" {
  description = "Let anyone create an organisation from the sign-up page (SIGNUP_ENABLED). Turn off once your organisation exists."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Image tag the services run (the git commit or a release); the same tag for server and web."
  type        = string
}

variable "migrate_image_tag" {
  description = "Image tag of the one-off migrate task. Null: image_tag. scripts/aws-deploy.sh sets it to the new release while the services stay on the old one, migrates, then moves the services."
  type        = string
  default     = null
}

variable "alarm_email" {
  description = "Alarm notification address."
  type        = string
  default     = null
}

variable "api_extra_environment" {
  description = "Extra api, worker and migrate environment (see docs/guides/configuration.md). Never secrets."
  type        = map(string)
  default     = {}
}

variable "evidence_expiration_days" {
  description = "Days an AI investigation evidence pack (evidence/ in the evidence bucket) is kept."
  type        = number
  default     = 180
}

variable "provider_allow_private" {
  description = "Allow AI model providers on private addresses (PROVIDER_ALLOW_PRIVATE), e.g. a self-hosted Ollama in the VPC. Off by default: the VPC also holds the database, cache and ClickHouse."
  type        = bool
  default     = false
}

variable "alert_interval_s" {
  description = "Seconds between alert rule evaluations in the worker (ALERT_INTERVAL_S)."
  type        = number
  default     = 30
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.small"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "clickhouse_instance_type" {
  description = "EC2 instance type of the ClickHouse log store."
  type        = string
  default     = "m6i.large"
}

variable "clickhouse_data_volume_gb" {
  description = "ClickHouse data volume size in GiB (log_events and its rollup)."
  type        = number
  default     = 50
}

variable "clickhouse_ami_id" {
  description = "AMI for the ClickHouse instance. Null: the latest Amazon Linux 2023 at first apply."
  type        = string
  default     = null
}

variable "metrics_allowed_cidrs" {
  description = "Source CIDRs allowed to scrape the api's /metrics through the load balancer."
  type        = list(string)
  default     = []
}

variable "worker_metrics_cidrs" {
  description = "In-VPC Prometheus CIDRs allowed to scrape the worker's /metrics on port 9464. Empty: no worker ingress."
  type        = list(string)
  default     = []
}

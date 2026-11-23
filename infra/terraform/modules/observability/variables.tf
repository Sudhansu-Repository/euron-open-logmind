variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the app log groups."
  type        = number
  default     = 30
}

variable "logs_kms_key_arn" {
  description = "CMK for the log groups (its key policy must allow CloudWatch Logs, as the kms module's does). Null uses CloudWatch's default encryption."
  type        = string
  default     = null
}

variable "alarm_email" {
  description = "Address subscribed to alarm notifications (confirm the e-mail AWS sends). Null: subscribe something else to the topic."
  type        = string
  default     = null
}

variable "alb_arn_suffix" {
  description = "Load balancer ARN suffix."
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name."
  type        = string
}

variable "lb_services" {
  description = "Load-balanced services (service module `services`): { api = { service_name, target_group_arn_suffix }, web = { ... } }. Must contain api."
  type = map(object({
    service_name            = string
    target_group_arn_suffix = string
  }))
  validation {
    condition     = contains(keys(var.lb_services), "api")
    error_message = "lb_services must contain api."
  }
}

variable "ecs_services" {
  description = "Every ECS service to watch for CPU and memory (service module `service_names`): { api = \"api\", worker = \"worker\", web = \"web\" }."
  type        = map(string)
}

variable "db_instance_identifier" {
  description = "RDS instance identifier."
  type        = string
}

variable "db_max_connections" {
  description = "Connection ceiling the alarm measures against."
  type        = number
  default     = 200
}

variable "cache_replication_group_id" {
  description = "ElastiCache replication group id; nodes are <id>-001, <id>-002, ..."
  type        = string
}

variable "cache_node_count" {
  description = "Nodes in the replication group (cache module num_cache_clusters)."
  type        = number
  default     = 1
}

variable "clickhouse_instance_id" {
  description = "ClickHouse EC2 instance id (clickhouse module instance_id)."
  type        = string
}

variable "target_5xx_threshold" {
  description = "5xx responses per 5 minutes (per app, and at the load balancer) that raise an alarm."
  type        = number
  default     = 25
}

variable "api_p95_latency_seconds" {
  description = "api p95 time to first byte that raises an alarm (log ingestion is the hot path)."
  type        = number
  default     = 2
}

variable "ingestion_rejected_log_pattern" {
  description = "CloudWatch Logs JSON filter matching the api's request line for an ingestion path that answered 4xx or 5xx."
  type        = string
  default     = "{ $.msg = \"request\" && $.status >= 400 && ($.path = \"/v1/logs\" || $.path = \"/api/v1/logs\" || $.path = \"/api/v1/logs/batch\") }"
}

variable "clickhouse_unavailable_log_pattern" {
  description = "CloudWatch Logs JSON filter matching a failed ClickHouse call."
  type        = string
  default     = "{ $.msg = \"clickhouse unavailable*\" }"
}

variable "investigation_failed_log_pattern" {
  description = "CloudWatch Logs JSON filter matching an AI investigation that ended in error."
  type        = string
  default     = "{ $.msg = \"investigation failed\" }"
}

variable "alert_evaluation_failed_log_pattern" {
  description = "CloudWatch Logs JSON filter matching an alert rule that could not be evaluated."
  type        = string
  default     = "{ $.msg = \"alert rule evaluation failed*\" }"
}

variable "mail_failed_log_pattern" {
  description = "CloudWatch Logs JSON filter matching alert mail the backend refused."
  type        = string
  default     = "{ $.msg = \"mail send failed\" }"
}

variable "worker_cycle_failed_log_pattern" {
  description = "CloudWatch Logs JSON filter matching the worker's failed cycle line."
  type        = string
  default     = "{ $.msg = \"worker cycle failed*\" }"
}

variable "ingestion_rejected_threshold" {
  description = "Rejected ingestion requests per 5 minutes that raise an alarm."
  type        = number
  default     = 100
}

variable "investigation_failure_threshold" {
  description = "Failed AI investigations per 5 minutes that raise an alarm."
  type        = number
  default     = 5
}

variable "worker_cycle_failure_threshold" {
  description = "Failed worker cycles per 5 minutes that raise an alarm."
  type        = number
  default     = 10
}

variable "sns_kms_key_arn" {
  description = "CMK for the alarm topic (its key policy must let CloudWatch use it, as the kms module's does)."
  type        = string
}

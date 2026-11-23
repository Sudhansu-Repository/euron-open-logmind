variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "vpc_id" {
  description = "VPC id."
  type        = string
}

variable "subnet_id" {
  description = "Private subnet the instance runs in (one AZ; the data volume is created in the same AZ)."
  type        = string
}

variable "kms_key_arn" {
  description = "CMK that encrypts the root and data volumes."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type. ClickHouse wants memory: m6i.large (8 GiB) for dev, r6i/m6i xlarge or larger for production ingest."
  type        = string
  default     = "m6i.large"
}

variable "architecture" {
  description = "CPU architecture of the instance type and the Amazon Linux 2023 AMI: x86_64 (m6i, r6i) or arm64 (Graviton m7g, r7g)."
  type        = string
  default     = "x86_64"
  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be x86_64 or arm64."
  }
}

variable "ami_id" {
  description = "AMI to boot instead of the latest Amazon Linux 2023 (looked up when null). Pin it to control when the OS image moves."
  type        = string
  default     = null
}

variable "root_volume_gb" {
  description = "Root volume size in GiB (OS, Docker and the image)."
  type        = number
  default     = 30
}

variable "data_volume_gb" {
  description = "Data volume size in GiB, mounted at /var/lib/clickhouse (log_events and log_rollup_1m)."
  type        = number
  default     = 100
  validation {
    condition     = var.data_volume_gb >= 10
    error_message = "data_volume_gb must be at least 10."
  }
}

variable "image" {
  description = "ClickHouse server image, pinned (the same release Compose runs locally). Point it at a copy in your own ECR to avoid Docker Hub pull limits."
  type        = string
  default     = "clickhouse/clickhouse-server:24.12.2.29"
}

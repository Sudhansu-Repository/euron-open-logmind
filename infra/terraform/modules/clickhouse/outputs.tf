output "security_group_id" {
  description = "ClickHouse security group; consumers add ingress rules against it."
  value       = aws_security_group.this.id
}

output "port" {
  description = "ClickHouse HTTP port."
  value       = local.port
}

output "private_ip" {
  description = "Private IP of the ClickHouse instance."
  value       = aws_instance.this.private_ip
}

output "instance_id" {
  description = "ClickHouse instance id (SSM Session Manager target, CloudWatch InstanceId dimension)."
  value       = aws_instance.this.id
}

output "connection_url" {
  description = "CLICKHOUSE_URL for the api, worker and migrate (http://logmind:<password>@<private ip>:8123/logmind). Pass it to the secrets module, never to plain task environment."
  value       = "http://logmind:${random_password.this.result}@${aws_instance.this.private_ip}:${local.port}/logmind"
  sensitive   = true
}

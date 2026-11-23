output "bucket_name" {
  description = "Evidence bucket name (EVIDENCE_BUCKET)."
  value       = aws_s3_bucket.evidence.bucket
}

output "bucket_arn" {
  description = "Evidence bucket ARN, for IAM policies."
  value       = aws_s3_bucket.evidence.arn
}

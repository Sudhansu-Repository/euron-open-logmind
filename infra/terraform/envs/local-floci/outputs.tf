output "evidence_bucket" {
  description = "EVIDENCE_BUCKET for the local stack."
  value       = module.storage.bucket_name
}

output "kms_key_alias" {
  description = "KMS_KEY_ID for the local stack."
  value       = module.kms.alias_name
}

output "app_secret_arn" {
  description = "The emulated Secrets Manager secret (SESSION_SECRET, API_KEY_PEPPER)."
  value       = module.secrets.secret_arn
}

output "bootstrap_secret_arn" {
  description = "The emulated Secrets Manager secret holding LOGMIND_ADMIN_PASSWORD."
  value       = module.secrets.bootstrap_secret_arn
}

output "mail_identity_arn" {
  description = "The emulated SES domain identity."
  value       = module.email.identity_arn
}

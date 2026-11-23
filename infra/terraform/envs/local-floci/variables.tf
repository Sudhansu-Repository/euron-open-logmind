variable "endpoint" {
  description = "Emulator endpoint. http://floci:4566 inside compose, http://localhost:6066 from the host."
  type        = string
  default     = "http://localhost:6066"
}

variable "name_prefix" {
  description = "Must match EVIDENCE_BUCKET (<name_prefix>-evidence) and KMS_KEY_ID (alias/<name_prefix>) in deploy/compose/compose.floci.yaml."
  type        = string
  default     = "logmind-local"
}

variable "cors_origins" {
  description = "Dashboard origins allowed to fetch objects with JavaScript."
  type        = list(string)
  default     = ["http://localhost:6010", "http://127.0.0.1:6010"]
}

variable "mail_domain" {
  description = "SES domain identity created on the emulator (the domain of MAIL_FROM locally)."
  type        = string
  default     = "logmind.local"
}

variable "mail_from_address" {
  description = "From address the send policy allows (the address inside MAIL_FROM locally)."
  type        = string
  default     = "alerts@logmind.local"
}

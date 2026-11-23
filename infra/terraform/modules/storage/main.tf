# One private, versioned bucket for what is too large to keep in a database row.
#
# <name_prefix>-evidence (EVIDENCE_BUCKET):
#   evidence/<org id>/    AI investigation evidence packs: the log lines, error groups
#                         and occurrences an investigation selected and compressed before
#                         prompting a model. The ai_investigations row in Postgres keeps
#                         only the object key; downloads go through the api, which checks
#                         the caller's organisation first. Expired after
#                         evidence_expiration_days.
#   An overwritten or deleted object stays recoverable for noncurrent_retention_days.
#
# Log lines themselves live in ClickHouse (log_events) and relational data in Postgres;
# the append-only audit_log is a Postgres table, not an Object Lock bucket. So this module
# provisions exactly the one bucket the investigation path needs.
resource "aws_s3_bucket" "evidence" {
  #checkov:skip=CKV_AWS_144:Cross-region replication doubles where customer log evidence lives (a data-residency decision for the operator); versioning covers recovery and packs can be regenerated from ClickHouse.
  #checkov:skip=CKV_AWS_18:Access logging targets a separate log bucket an operator chooses; CloudTrail data events cover object access.
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications; the api and worker write and read these objects themselves.
  bucket        = "${var.name_prefix}-evidence"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != null ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence" {
  bucket     = aws_s3_bucket.evidence.id
  depends_on = [aws_s3_bucket_versioning.evidence]

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  # Replaced or deleted versions stay recoverable for a while, then go.
  rule {
    id     = "expire-noncurrent"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_retention_days
    }
  }

  rule {
    id     = "expire-evidence"
    status = "Enabled"
    filter {
      prefix = "evidence/"
    }
    expiration {
      days = var.evidence_expiration_days
    }
  }
}

# Only needed when a browser fetches evidence packs with JavaScript; a presigned download link
# opened as a navigation needs none, so the default is no CORS at all.
resource "aws_s3_bucket_cors_configuration" "evidence" {
  count  = length(var.cors_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.evidence.id
  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = var.cors_origins
    allowed_headers = ["*"]
    expose_headers  = ["Content-Disposition", "Content-Length", "ETag"]
    max_age_seconds = 3600
  }
}

data "aws_iam_policy_document" "tls" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.evidence.arn, "${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "evidence" {
  count      = var.enforce_tls ? 1 : 0
  bucket     = aws_s3_bucket.evidence.id
  policy     = data.aws_iam_policy_document.tls.json
  depends_on = [aws_s3_bucket_public_access_block.evidence]
}

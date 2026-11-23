# LogMind's own secrets, in Secrets Manager. ECS injects each JSON key into the
# containers that need it as an environment variable; the values never appear in a task
# definition, a plan diff or a log. Each consumer gets only its own keys (see the outputs).
#
# Two secrets with different lifecycles and readers:
#
#   <name_prefix>/app           SESSION_SECRET and API_KEY_PEPPER. Read by the api, the
#                               worker and the migrate task. SESSION_SECRET signs
#                               dashboard sessions; API_KEY_PEPPER peppers the hashes of
#                               project API keys (lmk_<prefix>_<secret>), kept separate so
#                               rotating sessions never invalidates every ingestion key.
#   <name_prefix>/bootstrap     LOGMIND_ADMIN_PASSWORD, read only by the one-off
#                               migrate task: `make aws-admin` puts the first owner's
#                               password here, runs `create-admin`, then overwrites it
#                               with a random value. The password never travels as an ECS
#                               task override (those stay readable to anyone allowed to
#                               describe the task).
#
# DATABASE_URL, REDIS_URL and CLICKHOUSE_URL are generated once by the database, cache
# and clickhouse modules and merged into the app secret here (include_connection_urls),
# so the api, worker and migrate tasks read one JSON document for every connection
# string they need. AI provider keys and alert channel secrets are not here: the api
# seals them with KMS and stores them in Postgres.
#
# Generated once, then rotated out of band; Terraform never rolls them back. Locally
# (Compose) the same values come from deploy/compose/.env.
locals {
  signing_keys = ["SESSION_SECRET", "API_KEY_PEPPER"]
  app_keys = concat(
    local.signing_keys,
    var.include_connection_urls ? ["DATABASE_URL", "REDIS_URL", "CLICKHOUSE_URL"] : [],
  )
}

resource "random_password" "this" {
  for_each = toset(concat(local.signing_keys, ["LOGMIND_ADMIN_PASSWORD"]))
  length   = 64
  special  = false
}

resource "aws_secretsmanager_secret" "app" {
  #checkov:skip=CKV2_AWS_57:A session signing key and an API key pepper (plus the generated connection URLs); rotation is an operator procedure, not a Lambda.
  name                    = "${var.name_prefix}/app"
  description             = "LogMind signing secrets (session, API key pepper) and connection URLs"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode(merge(
    { for k in local.signing_keys : k => random_password.this[k].result },
    var.include_connection_urls ? {
      DATABASE_URL   = var.database_url
      REDIS_URL      = var.redis_url
      CLICKHOUSE_URL = var.clickhouse_url
    } : {},
  ))

  # Rotation happens out of band (put a new version by hand or by pipeline). Without
  # this, the next `terraform apply` would quietly roll every secret back.
  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "bootstrap" {
  #checkov:skip=CKV2_AWS_57:Holds a random placeholder except for the seconds `make aws-admin` runs create-admin; nothing to rotate.
  name                    = "${var.name_prefix}/bootstrap"
  description             = "LogMind first-owner password for the one-off create-admin task (random placeholder otherwise)"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "bootstrap" {
  secret_id     = aws_secretsmanager_secret.bootstrap.id
  secret_string = jsonencode({ LOGMIND_ADMIN_PASSWORD = random_password.this["LOGMIND_ADMIN_PASSWORD"].result })

  # scripts/aws-run-task.sh writes and then scrubs this value.
  lifecycle {
    ignore_changes = [secret_string]
  }
}

locals {
  # api, worker and migrate.
  ecs_secrets = [for k in local.app_keys : { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }]
  # The migrate task only.
  bootstrap_secrets = [
    { name = "LOGMIND_ADMIN_PASSWORD", valueFrom = "${aws_secretsmanager_secret.bootstrap.arn}:LOGMIND_ADMIN_PASSWORD::" },
  ]
}

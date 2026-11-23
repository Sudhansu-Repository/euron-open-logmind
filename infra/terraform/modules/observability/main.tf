# Logs, alarms and one dashboard for a deployment:
#
#   - a CloudWatch log group per app (api, worker, web, migrate), encrypted, with
#     retention
#   - product metrics extracted from the structured JSON logs: rejected log ingestion
#     requests, ClickHouse unavailability, failed AI investigations, failed alert rule
#     evaluations, failed alert mail and failed worker cycles
#   - alarms to an SNS topic (optionally e-mailed): 5xx, api p95 latency, unhealthy
#     targets, a service with no running task, CPU and memory per service, database,
#     cache, the ClickHouse instance, and the product metrics above
#   - one dashboard with the same signals side by side
data "aws_region" "current" {}

locals {
  region     = data.aws_region.current.region
  apps       = toset(["api", "worker", "web", "migrate"])
  namespace  = "LogMind/${var.name_prefix}"
  cache_node = [for i in range(var.cache_node_count) : format("%s-%03d", var.cache_replication_group_id, i + 1)]
}

# ─── Logs ────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "app" {
  #checkov:skip=CKV_AWS_338:Retention is an input (log_retention_days); aws-prod keeps 365 days.
  for_each          = local.apps
  name              = "/logmind/${var.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
}

# Log lines turned into metrics. Every process logs one JSON object per line
# (core/logs.py: `msg` plus the structured fields), so each filter matches a message
# and, where it matters, a field:
#
#   IngestionRejected        an ingestion request (/v1/logs, /api/v1/logs,
#                            /api/v1/logs/batch) answered 4xx or 5xx (api): a bad API
#                            key, an oversized or malformed batch, or a rate limit
#   ClickHouseUnavailable    a request could not reach the log store (api; the worker's
#                            failures surface as WorkerCycleFailures)
#   InvestigationFailures    an AI investigation ended in error: the model provider
#                            refused, timed out or answered badly (worker)
#   AlertEvaluationFailures  an alert rule could not be evaluated, so it cannot fire
#                            (worker)
#   MailFailures             alert mail was refused by SES or SMTP (api, worker)
#   WorkerCycleFailures      a worker cycle raised (it continues on the next one); a burst
#                            means a dependency is down (worker)
#
# A metric gets one filter per log group it can appear in; the patterns are inputs, so a
# deployment can tune them without editing the module.
locals {
  log_metrics = merge([
    for metric, m in {
      IngestionRejected       = { groups = ["api"], pattern = var.ingestion_rejected_log_pattern }
      ClickHouseUnavailable   = { groups = ["api"], pattern = var.clickhouse_unavailable_log_pattern }
      InvestigationFailures   = { groups = ["worker"], pattern = var.investigation_failed_log_pattern }
      AlertEvaluationFailures = { groups = ["worker"], pattern = var.alert_evaluation_failed_log_pattern }
      MailFailures            = { groups = ["api", "worker"], pattern = var.mail_failed_log_pattern }
      WorkerCycleFailures     = { groups = ["worker"], pattern = var.worker_cycle_failed_log_pattern }
    } : { for g in m.groups : "${metric}-${g}" => { metric = metric, group = g, pattern = m.pattern } }
  ]...)
}

resource "aws_cloudwatch_log_metric_filter" "this" {
  for_each       = local.log_metrics
  name           = "${var.name_prefix}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.app[each.value.group].name
  pattern        = each.value.pattern
  metric_transformation {
    name          = each.value.metric
    namespace     = local.namespace
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

# ─── Alarms ──────────────────────────────────────────────────────────────────

# Encrypted with the CMK: CloudWatch cannot publish to a topic under the AWS-managed SNS
# key, and the kms module's key policy lets it use this one.
resource "aws_sns_topic" "alarms" {
  name              = "${var.name_prefix}-alarms"
  kms_master_key_id = var.sns_kms_key_arn
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == null ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  lb_alarms = merge([
    for name, s in var.lb_services : {
      "${name}-5xx" = {
        description = "${name}: 5xx responses from the tasks"
        namespace   = "AWS/ApplicationELB"
        metric      = "HTTPCode_Target_5XX_Count"
        stat        = "Sum"
        threshold   = var.target_5xx_threshold
        period      = 300
        dimensions  = { LoadBalancer = var.alb_arn_suffix, TargetGroup = s.target_group_arn_suffix }
        comparison  = "GreaterThanThreshold"
      }
      "${name}-unhealthy" = {
        description = "${name}: tasks failing load balancer health checks"
        namespace   = "AWS/ApplicationELB"
        metric      = "UnHealthyHostCount"
        stat        = "Maximum"
        threshold   = 0
        period      = 60
        dimensions  = { LoadBalancer = var.alb_arn_suffix, TargetGroup = s.target_group_arn_suffix }
        comparison  = "GreaterThanThreshold"
      }
    }
  ]...)

  ecs_alarms = merge([
    for name, service_name in var.ecs_services : {
      "${name}-cpu" = {
        description = "${name}: CPU sustained above 85%"
        namespace   = "AWS/ECS"
        metric      = "CPUUtilization"
        stat        = "Average"
        threshold   = 85
        period      = 300
        dimensions  = { ClusterName = var.ecs_cluster_name, ServiceName = service_name }
        comparison  = "GreaterThanThreshold"
      }
      "${name}-memory" = {
        description = "${name}: memory sustained above 85%"
        namespace   = "AWS/ECS"
        metric      = "MemoryUtilization"
        stat        = "Average"
        threshold   = 85
        period      = 300
        dimensions  = { ClusterName = var.ecs_cluster_name, ServiceName = service_name }
        comparison  = "GreaterThanThreshold"
      }
    }
  ]...)

  edge_alarms = {
    alb-5xx = {
      description = "Load balancer 5xx (no healthy target, timeouts)"
      namespace   = "AWS/ApplicationELB"
      metric      = "HTTPCode_ELB_5XX_Count"
      stat        = "Sum"
      threshold   = var.target_5xx_threshold
      period      = 300
      dimensions  = { LoadBalancer = var.alb_arn_suffix }
      comparison  = "GreaterThanThreshold"
    }
  }

  db_alarms = {
    db-cpu = {
      description = "Database CPU sustained above 80%"
      namespace   = "AWS/RDS"
      metric      = "CPUUtilization"
      stat        = "Average"
      threshold   = 80
      period      = 300
      dimensions  = { DBInstanceIdentifier = var.db_instance_identifier }
      comparison  = "GreaterThanThreshold"
    }
    db-storage = {
      description = "Database free storage below 5 GiB (error occurrences, AI investigations, alert history and the audit log grow it)"
      namespace   = "AWS/RDS"
      metric      = "FreeStorageSpace"
      stat        = "Minimum"
      threshold   = 5 * 1024 * 1024 * 1024
      period      = 300
      dimensions  = { DBInstanceIdentifier = var.db_instance_identifier }
      comparison  = "LessThanThreshold"
    }
    db-connections = {
      description = "Database connections above 80% of the configured ceiling"
      namespace   = "AWS/RDS"
      metric      = "DatabaseConnections"
      stat        = "Maximum"
      threshold   = var.db_max_connections * 0.8
      period      = 300
      dimensions  = { DBInstanceIdentifier = var.db_instance_identifier }
      comparison  = "GreaterThanThreshold"
    }
  }

  # Per node. Memory is the alarm that matters most here: a full node refuses writes
  # under noeviction, and the API key cache and dashboard aggregate cache fall back to
  # the next request reading Postgres or ClickHouse instead (degraded, not broken).
  cache_alarms = merge([
    for i, node in local.cache_node : {
      "cache-node-${i + 1}-memory" = {
        description = "Cache node ${node}: memory above 80%"
        namespace   = "AWS/ElastiCache"
        metric      = "DatabaseMemoryUsagePercentage"
        stat        = "Maximum"
        threshold   = 80
        period      = 300
        dimensions  = { CacheClusterId = node }
        comparison  = "GreaterThanThreshold"
      }
      "cache-node-${i + 1}-cpu" = {
        description = "Cache node ${node}: engine CPU above 80%"
        namespace   = "AWS/ElastiCache"
        metric      = "EngineCPUUtilization"
        stat        = "Average"
        threshold   = 80
        period      = 300
        dimensions  = { CacheClusterId = node }
        comparison  = "GreaterThanThreshold"
      }
    }
  ]...)

  # The log store's instance. EC2 publishes no memory or disk metrics on its own;
  # ClickHouseUnavailable (below) catches the log store failing from the app's side.
  clickhouse_alarms = {
    clickhouse-cpu = {
      description = "ClickHouse instance CPU sustained above 80% (ingest merges or heavy searches)"
      namespace   = "AWS/EC2"
      metric      = "CPUUtilization"
      stat        = "Average"
      threshold   = 80
      period      = 300
      dimensions  = { InstanceId = var.clickhouse_instance_id }
      comparison  = "GreaterThanThreshold"
    }
    clickhouse-status-check = {
      description = "ClickHouse instance failing its EC2 status checks"
      namespace   = "AWS/EC2"
      metric      = "StatusCheckFailed"
      stat        = "Maximum"
      threshold   = 0
      period      = 60
      dimensions  = { InstanceId = var.clickhouse_instance_id }
      comparison  = "GreaterThanThreshold"
    }
  }

  threshold_alarms = merge(local.lb_alarms, local.ecs_alarms, local.edge_alarms, local.db_alarms, local.cache_alarms, local.clickhouse_alarms)
}

resource "aws_cloudwatch_metric_alarm" "threshold" {
  for_each            = local.threshold_alarms
  alarm_name          = "${var.name_prefix}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = each.value.stat
  dimensions          = each.value.dimensions
  period              = each.value.period
  evaluation_periods  = 2
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# p95, not average: a slow write hides inside an average of fast reads. Log ingestion is
# the hot path every shipper and SDK waits on.
resource "aws_cloudwatch_metric_alarm" "api_latency_p95" {
  alarm_name          = "${var.name_prefix}-api-latency-p95"
  alarm_description   = "api: p95 response time above ${var.api_p95_latency_seconds}s (every log shipper waits on ingestion)"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p95"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.lb_services["api"].target_group_arn_suffix }
  period              = 300
  evaluation_periods  = 3
  threshold           = var.api_p95_latency_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# A service with no running task is down, whatever its other metrics say. Missing data
# counts as breaching: a service that stopped reporting is not healthy. Container
# Insights (on by default in the service module) publishes RunningTaskCount.
resource "aws_cloudwatch_metric_alarm" "not_running" {
  for_each            = var.ecs_services
  alarm_name          = "${var.name_prefix}-${each.key}-not-running"
  alarm_description   = "${each.key}: no running task"
  namespace           = "ECS/ContainerInsights"
  metric_name         = "RunningTaskCount"
  statistic           = "Minimum"
  dimensions          = { ClusterName = var.ecs_cluster_name, ServiceName = each.value }
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

locals {
  log_alarms = {
    ingestion-rejected = {
      description = "More than ${var.ingestion_rejected_threshold} rejected ingestion requests in 5 minutes (bad API keys, malformed or oversized batches, rate limits)"
      metric      = "IngestionRejected"
      threshold   = var.ingestion_rejected_threshold
    }
    clickhouse-unavailable = {
      description = "The api could not reach ClickHouse (ingestion and search are failing)"
      metric      = "ClickHouseUnavailable"
      threshold   = 0
    }
    investigation-failures = {
      description = "More than ${var.investigation_failure_threshold} AI investigations failed in 5 minutes (a model provider is down or misconfigured)"
      metric      = "InvestigationFailures"
      threshold   = var.investigation_failure_threshold
    }
    alert-evaluation-failures = {
      description = "An alert rule could not be evaluated (it cannot fire until fixed)"
      metric      = "AlertEvaluationFailures"
      threshold   = 0
    }
    mail-failures = {
      description = "Alert mail was refused by the mail backend"
      metric      = "MailFailures"
      threshold   = 0
    }
    worker-cycle-failures = {
      description = "Worker cycles failed more than ${var.worker_cycle_failure_threshold} times in 5 minutes (a dependency is likely down)"
      metric      = "WorkerCycleFailures"
      threshold   = var.worker_cycle_failure_threshold
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "logs" {
  for_each            = local.log_alarms
  alarm_name          = "${var.name_prefix}-${each.key}"
  alarm_description   = each.value.description
  namespace           = local.namespace
  metric_name         = each.value.metric
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# ─── Dashboard ───────────────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = var.name_prefix
  dashboard_body = jsonencode({
    widgets = concat(
      [
        {
          type = "metric", x = 0, y = 0, width = 12, height = 6
          properties = {
            title = "Requests and errors", region = local.region, stat = "Sum", period = 60
            metrics = [
              ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix],
              [".", "HTTPCode_Target_4XX_Count", ".", "."],
              [".", "HTTPCode_Target_5XX_Count", ".", "."],
              [".", "HTTPCode_ELB_5XX_Count", ".", "."],
            ]
          }
        },
        {
          type = "metric", x = 12, y = 0, width = 12, height = 6
          properties = {
            title = "api latency p50 / p95 / p99", region = local.region, period = 60
            metrics = [
              ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.lb_services["api"].target_group_arn_suffix, { stat = "p50" }],
              ["...", { stat = "p95" }],
              ["...", { stat = "p99" }],
            ]
          }
        },
        {
          type = "metric", x = 0, y = 12, width = 8, height = 6
          properties = {
            title = "Ingestion rejects / ClickHouse / investigations / alerts / mail / worker", region = local.region, period = 60, stat = "Sum"
            metrics = [
              [local.namespace, "IngestionRejected"],
              [local.namespace, "ClickHouseUnavailable"],
              [local.namespace, "InvestigationFailures"],
              [local.namespace, "AlertEvaluationFailures"],
              [local.namespace, "MailFailures"],
              [local.namespace, "WorkerCycleFailures"],
            ]
          }
        },
        {
          type = "metric", x = 0, y = 6, width = 12, height = 6
          properties = {
            title = "ClickHouse instance CPU / network", region = local.region, stat = "Average", period = 60
            metrics = [
              ["AWS/EC2", "CPUUtilization", "InstanceId", var.clickhouse_instance_id],
              [".", "NetworkIn", ".", ".", { stat = "Sum" }],
              [".", "NetworkOut", ".", ".", { stat = "Sum" }],
            ]
          }
        },
        {
          type = "metric", x = 8, y = 12, width = 8, height = 6
          properties = {
            title = "Database", region = local.region, stat = "Average", period = 60
            metrics = [
              ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_identifier],
              [".", "DatabaseConnections", ".", "."],
              [".", "ReadLatency", ".", "."],
              [".", "WriteLatency", ".", "."],
            ]
          }
        },
        {
          type = "metric", x = 16, y = 12, width = 8, height = 6
          properties = {
            title = "Cache memory % / engine CPU %", region = local.region, stat = "Maximum", period = 60
            metrics = concat(
              [for node in local.cache_node : ["AWS/ElastiCache", "DatabaseMemoryUsagePercentage", "CacheClusterId", node]],
              [for node in local.cache_node : ["AWS/ElastiCache", "EngineCPUUtilization", "CacheClusterId", node]],
            )
          }
        },
      ],
      [
        for i, name in sort(keys(var.ecs_services)) : {
          type = "metric", x = (i % 3) * 8, y = 18 + floor(i / 3) * 6, width = 8, height = 6
          properties = {
            title = "${name}: CPU / memory", region = local.region, stat = "Average", period = 60
            metrics = [
              ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_services[name]],
              [".", "MemoryUtilization", ".", ".", ".", "."],
            ]
          }
        }
      ],
    )
  })
}

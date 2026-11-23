# Deploy to AWS

Nothing in this repository is applied to a real account by the project itself; this is how
you would. `infra/terraform/envs/aws-dev` and `aws-prod` provision:

| Module | Resources |
| --- | --- |
| `network` | VPC over two (dev) or three (prod) AZs, public and private subnets, NAT, flow logs, interface endpoints (prod) |
| `database` | RDS PostgreSQL 16, encrypted, forced SSL, Performance Insights, backups |
| `cache` | ElastiCache Redis, encrypted in transit and at rest, auth token |
| `clickhouse` | ClickHouse on EC2 (AWS has no managed ClickHouse): private subnet, encrypted gp3 data volume, IMDSv2, SSM only (no SSH), no ingress except 8123 from the api and worker |
| `storage` | The evidence bucket: versioned, SSE-KMS, TLS only, lifecycle expiry |
| `kms` | One key with rotation, used for sealing, S3, logs and secrets |
| `secrets` | `SESSION_SECRET`, `API_KEY_PEPPER` and the connection URLs (Postgres, Redis, ClickHouse) |
| `email` | SES domain identity, DKIM, configuration set |
| `ecr` | `server` and `web` repositories, scan on push, immutable tags |
| `service` | ECS Fargate (api, worker, web, a migrate task), ALB with HTTPS and WAF, autoscaling |
| `observability` | Log groups, metric filters, alarms (5xx, latency, ClickHouse health, failed investigations, alert evaluation failures), a dashboard |

```bash
cd infra/terraform/envs/aws-dev
cp terraform.tfvars.example terraform.tfvars   # hostname, certificate, zone, alarm email
cp backend.tf.example backend.tf               # your state bucket
cd ../../../..
make aws-deploy ENV=aws-dev TAG=0.1.0          # registries, images, infrastructure,
                                               # migrations, rollout
LOGMIND_ADMIN_PASSWORD='...' make aws-admin ENV=aws-dev EMAIL=you@example.com
```

`make tf-aws-on-floci` plans, applies, re-plans and destroys the whole `aws-dev` environment
against a throwaway Floci, so plan-time and apply-time errors show up without an account.

**Production notes.** Set `ENVIRONMENT=production` (the environments do); the boot guards
then refuse unsafe settings. Give ClickHouse an instance and volume sized for your volume
(`clickhouse_instance_type`, `clickhouse_data_volume_gb`), and back the data volume up with
AWS Backup or a Data Lifecycle Manager policy. `PROVIDER_ALLOW_PRIVATE` defaults to `false` on
AWS; set it to `true` only to reach a model server inside the VPC.

# Running the local stack against real AWS

`make up-aws` keeps Postgres, Redis, ClickHouse, Mailpit and the web app local but points
migrate, api and worker at real AWS resources (the KMS key, the evidence bucket, SES) using
your AWS CLI profile, mounted read-only.

```bash
cp deploy/compose/.env.aws.example deploy/compose/.env.aws   # key alias, bucket, sender
make up-aws
```

Use the outputs of an `aws-dev` apply, or your own equivalents. Credentials never enter the
repository: `.env.aws` is git-ignored and holds only identifiers.

# ClickHouse, LogMind's log store, on one EC2 instance.
#
# AWS has no managed ClickHouse service (ClickHouse Cloud is a separate vendor, sold
# through the Marketplace), so the AWS environments run the same pinned
# clickhouse/clickhouse-server image that Compose runs locally, on an instance this module
# owns. It holds log_events and the log_rollup_1m pre-aggregate; `logmind migrate`
# creates both after the Postgres migrations. There is no fallback: log ingestion,
# search, the live tail and every dashboard read it, so CLICKHOUSE_URL is required.
#
#   - one instance in one private subnet, no public IP, no SSH key and no port 22:
#     operators reach it through SSM Session Manager (the instance profile carries only
#     AmazonSSMManagedInstanceCore)
#   - IMDSv2 required with a hop limit of 1, so the container cannot reach the instance
#     credentials; EBS-optimized; detailed monitoring
#   - an encrypted root volume and a separate encrypted gp3 data volume (the CMK),
#     mounted at /var/lib/clickhouse. The data volume is its own resource: replacing the
#     instance (a new image tag, a new password) detaches it and the new instance mounts
#     the same data again
#   - a security group with no ingress of its own: consumers (the api, worker and migrate
#     tasks) add ingress on 8123 against it, the way the database and cache modules work.
#     Egress is HTTPS only: the image pull from Docker Hub and the dnf repositories (via
#     the NAT gateway), and the SSM endpoints. DNS and NTP use the VPC resolver and the
#     Amazon Time Sync link-local addresses, which security groups do not filter
#   - the password is generated here; only its SHA-256 reaches the instance (user data
#     is readable to anyone allowed to describe the instance). The full CLICKHOUSE_URL is
#     handed to the secrets module and injected into the tasks, never put in plain
#     environment
#
# A single node, not a replicated cluster: losing the instance stops log ingestion and
# search until it is replaced, though the data volume survives. Snapshot the data volume
# (AWS Backup or Data Lifecycle Manager) if log history must outlive the volume itself.
data "aws_ami" "al2023" {
  count       = var.ami_id == null ? 1 : 0
  owners      = ["amazon"]
  most_recent = true
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-${var.architecture}"]
  }
  filter {
    name   = "architecture"
    values = [var.architecture]
  }
}

locals {
  ami_id = var.ami_id != null ? var.ami_id : data.aws_ami.al2023[0].id
  port   = 8123
}

# Alphanumeric only, so the password needs no escaping inside the URL.
resource "random_password" "this" {
  length  = 40
  special = false
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-clickhouse"
  description = "ClickHouse HTTP; ingress only from application security groups"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name_prefix}-clickhouse" }
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.this.id
  description       = "HTTPS for the image pull, dnf repositories and SSM (see the header)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name_prefix}-clickhouse"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Session Manager only: no other AWS API is called from the instance.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_partition" "current" {}

resource "aws_iam_instance_profile" "this" {
  name = "${var.name_prefix}-clickhouse"
  role = aws_iam_role.this.name
}

resource "aws_instance" "this" {
  ami                         = local.ami_id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.this.id]
  iam_instance_profile        = aws_iam_instance_profile.this.name
  associate_public_ip_address = false
  ebs_optimized               = true
  monitoring                  = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    kms_key_id            = var.kms_key_arn
    delete_on_termination = true
  }

  # cloud-init runs user data on first boot only, so a new image or password replaces the
  # instance; the data volume is reattached to the replacement (see the header).
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    image           = var.image
    database        = "logmind"
    user            = "logmind"
    password_sha256 = sha256(random_password.this.result)
    port            = local.port
    device          = "/dev/sdf"
  })
  user_data_replace_on_change = true

  tags = { Name = "${var.name_prefix}-clickhouse" }

  lifecycle {
    # A newer Amazon Linux AMI must not replace the log store on an unrelated apply;
    # pin ami_id, or replace deliberately, to move to one.
    ignore_changes = [ami]
  }
}

resource "aws_ebs_volume" "data" {
  #checkov:skip=CKV2_AWS_9:Backups of the log store are the operator's choice of AWS Backup or Data Lifecycle Manager plan (see the header); log_events also carries its own TTL.
  availability_zone = aws_instance.this.availability_zone
  type              = "gp3"
  size              = var.data_volume_gb
  encrypted         = true
  kms_key_id        = var.kms_key_arn
  tags              = { Name = "${var.name_prefix}-clickhouse-data" }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.this.id
  # Stop ClickHouse cleanly (the instance) before the volume is pulled away.
  stop_instance_before_detaching = true
}

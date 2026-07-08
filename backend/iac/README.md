# Backend IaC (Terraform module)

Provisions everything the backend needs in AWS:

- the **7 DynamoDB tables + GSIs**, mirroring `scripts/create_tables.py`
  exactly (all-string keys, no cross-tenant `name-index`), with PITR,
  SSE, and deletion protection on by default;
- **IAM**: execution role (image pull, logs, SSM secret injection) and a
  least-privilege task role scoped to the 7 tables and their indexes, plus
  EMR Serverless job-run permissions only when `emr_mode = "real"` and S3
  read on the scoring-output locations only when `dq_s3_read_arns` is set;
- **ECS Fargate**: log group, task definition (port 8000, `/health` check,
  Entra + Snowflake settings injected as SSM secrets, table names wired
  automatically), and a service with circuit-breaker rollback, optionally
  attached to an ALB target group. Creates a dedicated cluster unless you
  pass one in.

Networking (VPC, subnets, security groups, the ALB itself) is deliberately
out of scope: pass in what your landing zone provides.

## Usage

```hcl
module "mlserv_backend" {
  source = "./backend/iac"

  aws_region      = "us-east-1"
  container_image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/mlserv-backend:v1.0.0"

  subnet_ids         = ["subnet-priv-a", "subnet-priv-b"]
  security_group_ids = [aws_security_group.backend.id]
  target_group_arn   = aws_lb_target_group.backend.arn

  cors_allowed_origins = "https://mlserv.example.com"

  # AUTH_MODE is always "prod" here; the app refuses to boot unless these
  # resolve to non-blank values.
  entra_parameter_arns = {
    ENTRA_TENANT_ID = "arn:aws:ssm:us-east-1:123456789012:parameter/mlserv/entra-tenant-id"
    ENTRA_CLIENT_ID = "arn:aws:ssm:us-east-1:123456789012:parameter/mlserv/entra-client-id"
    ENTRA_JWKS_URL  = "arn:aws:ssm:us-east-1:123456789012:parameter/mlserv/entra-jwks-url"
    ENTRA_ISSUER    = "arn:aws:ssm:us-east-1:123456789012:parameter/mlserv/entra-issuer"
    ENTRA_AUDIENCE  = "arn:aws:ssm:us-east-1:123456789012:parameter/mlserv/entra-audience"
  }

  tags = { app = "mlserv", env = "prod" }
}
```

`desired_count` defaults to 2 — safe, since job writes are optimistically
locked and monitoring snapshots are idempotent per run.

## Notable variables

| Variable | Default | Purpose |
|---|---|---|
| `name_prefix` | `mlserv` | Resource/table name prefix; must match the app's `TABLE_*` settings |
| `cluster_arn` | `""` (create one) | Deploy into an existing ECS cluster |
| `emr_mode` | `mock` | `real` also attaches EMR Serverless job-run permissions to the task role |
| `snowflake_mode` | `mock` | `real` runs live async COPY INTO unloads; supply `snowflake_parameter_arns` (SSM: account, user, private key PEM, storage integration) or the app refuses to start |
| `dq_mode` | `mock` | `real` computes quality/drift evidence from the run's parquet scoring output on S3; supply `dq_s3_read_arns` (bucket + object ARNs) |
| `extra_environment` | `{}` | Extra env vars (threshold overrides, `STEP_TIMEOUT_SECONDS`, ...) |
| `create_ecr_repository` | `false` | Also create the `mlserv-backend` ECR repo |
| `enable_deletion_protection` | `true` | DynamoDB deletion protection |

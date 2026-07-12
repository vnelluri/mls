variable "name_prefix" {
  description = "Prefix for every named resource (tables are <prefix>-tenants, ...). Must match the backend's TABLE_* settings (default mlserv)."
  type        = string
  default     = "mlserv"
}

variable "aws_region" {
  description = "Region, used in the container's AWS_REGION env and log configuration."
  type        = string
  default     = "us-east-1"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}

# ---- DynamoDB ---------------------------------------------------------------

variable "enable_point_in_time_recovery" {
  description = "PITR on all tables. Keep enabled for any environment a regulator might ask about."
  type        = bool
  default     = true
}

variable "enable_deletion_protection" {
  description = "DynamoDB deletion protection on all tables."
  type        = bool
  default     = true
}

# ---- ECS --------------------------------------------------------------------

variable "cluster_arn" {
  description = "Existing ECS cluster to deploy into. Leave empty to create a dedicated <prefix>-cluster."
  type        = string
  default     = ""
}

variable "container_image" {
  description = "Backend image, e.g. <account>.dkr.ecr.<region>.amazonaws.com/mlserv-backend:<tag> (built from backend/Dockerfile, prod stage)."
  type        = string
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Service task count. The API is safe at >1 (optimistic locking + conditional writes coordinate the per-task refresh loops)."
  type        = number
  default     = 2
}

variable "subnet_ids" {
  description = "Private subnets for the service's awsvpc ENIs."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups for the service ENIs (must allow the ALB to reach port 8000)."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "Assign public IPs to task ENIs. Keep false; tasks belong in private subnets behind the ALB."
  type        = bool
  default     = false
}

variable "target_group_arn" {
  description = "ALB target group forwarding to the API (port 8000). Empty = no load balancer attachment."
  type        = string
  default     = ""
}

variable "health_check_grace_period_seconds" {
  type    = number
  default = 30
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the service log group."
  type        = number
  default     = 90
}

variable "create_ecr_repository" {
  description = "Also create an ECR repository named <prefix>-backend."
  type        = bool
  default     = false
}

# ---- Application configuration ------------------------------------------------

variable "cors_allowed_origins" {
  description = "Comma-separated origins for CORS_ALLOWED_ORIGINS (the frontend's URL)."
  type        = string
}

variable "emr_mode" {
  description = "EMR_MODE: \"mock\" (in-process simulation) or \"real\" (EMR Serverless)."
  type        = string
  default     = "mock"
}

variable "snowflake_mode" {
  description = "SNOWFLAKE_MODE: \"mock\" or \"real\" (live async COPY INTO unloads; requires snowflake_parameter_arns)."
  type        = string
  default     = "mock"
}

variable "dq_mode" {
  description = "DQ_MODE: \"mock\" or \"real\" (computes quality/drift evidence from the run's parquet scoring output on S3; requires dq_s3_read_arns)."
  type        = string
  default     = "mock"
}

variable "emr_application_arns" {
  description = <<-EOT
    EMR Serverless application ARNs the platform may run jobs on — one per
    tenant, matching each tenant's execution config (emrApplicationId set via
    PUT /tenants/{id}/execution). Required when emr_mode = "real".
  EOT
  type        = list(string)
  default     = []
}

variable "emr_execution_role_arns" {
  description = <<-EOT
    EMR job execution role ARNs the task role may pass to EMR Serverless
    (iam:PassRole, conditioned to emr-serverless.amazonaws.com) — one per
    tenant, matching each tenant's execution config (emrExecutionRoleArn).
    These roles carry the S3 read (input/artifacts) and write (scoring
    output) grants for their tenant's prefixes. Required when
    emr_mode = "real".
  EOT
  type        = list(string)
  default     = []
}

variable "snowflake_parameter_arns" {
  description = <<-EOT
    SSM parameter ARNs for the Snowflake SERVICE ACCOUNT the platform
    connects as (users never connect to Snowflake themselves), injected as
    container secrets when SNOWFLAKE_MODE=real (the app refuses to start in
    real mode without account, user, an auth method, and the storage
    integration). Scope the account's Snowflake role tightly: it bounds what
    any tenant pipeline can export. Keys: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
    SNOWFLAKE_PRIVATE_KEY (PEM, SecureString), SNOWFLAKE_STORAGE_INTEGRATION,
    and optionally SNOWFLAKE_ROLE / SNOWFLAKE_PRIVATE_KEY_PASSPHRASE /
    SNOWFLAKE_PASSWORD.
  EOT
  type        = map(string)
  default     = {}
}

variable "dq_s3_read_arns" {
  description = <<-EOT
    S3 ARNs the real DQ engine may read scoring output from — include BOTH
    the bucket ARNs (for ListBucket) and the object-prefix ARNs (for
    GetObject), e.g.:
      ["arn:aws:s3:::scoring-out", "arn:aws:s3:::scoring-out/*"]
    Only attached when non-empty.
  EOT
  type        = list(string)
  default     = []
}

variable "artifacts_bucket_name" {
  description = <<-EOT
    Existing S3 bucket for model-artifact uploads (the backend's
    S3_ARTIFACTS_BUCKET, default mlserv-artifacts). Grants the task role
    put/get on "<bucket>/*" when set; empty = no policy attached (uploads
    will 500 in that case).
  EOT
  type        = string
  default     = ""
}

variable "entra_parameter_arns" {
  description = <<-EOT
    SSM parameter ARNs for the Entra ID settings, injected as container
    secrets. ALL keys are required in prod: the app refuses to start with
    AUTH_MODE=prod unless ENTRA_JWKS_URL, ENTRA_ISSUER, and an audience are
    set. Keys: ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_JWKS_URL,
    ENTRA_ISSUER, ENTRA_AUDIENCE.
  EOT
  type        = map(string)
}

variable "extra_environment" {
  description = "Additional plain environment variables for the container (e.g. PSI_FAIL, STEP_TIMEOUT_SECONDS overrides)."
  type        = map(string)
  default     = {}
}

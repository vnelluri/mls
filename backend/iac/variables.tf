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
  description = "SNOWFLAKE_MODE: \"mock\" or \"real\"."
  type        = string
  default     = "mock"
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

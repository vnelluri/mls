variable "name_prefix" {
  description = "Prefix for every named resource; keep it equal to the backend module's name_prefix (default mlserv)."
  type        = string
  default     = "mlserv"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}

# ---- Tenants ------------------------------------------------------------------

variable "tenant_ids" {
  description = <<-EOT
    Platform tenant ids (e.g. ["acme-capital", "blue-harbor-bank"]). Each id
    MUST equal the tenant_id used inside the platform (and therefore the slug
    in the tenant's tms-<tenant>-<role> Entra groups) — it becomes the
    tenant's S3 prefix and names its EMR application and execution role.
    Onboarding a tenant = adding its id here, applying, then entering the
    tenant_execution output into PUT /tenants/{id}/execution.
  EOT
  type        = set(string)

  validation {
    condition     = alltrue([for t in var.tenant_ids : can(regex("^[a-z0-9][a-z0-9-]*$", t))])
    error_message = "Tenant ids must be lowercase slugs (letters, digits, hyphens) to be valid S3 prefixes and group-name slugs."
  }
}

# ---- S3 -----------------------------------------------------------------------

variable "kms_key_arn" {
  description = "CMK for bucket encryption. Empty = SSE-S3 (AES256)."
  type        = string
  default     = ""
}

variable "data_retention_days" {
  description = <<-EOT
    Lifecycle expiry for run data (unload staging + scoring output) in the
    data bucket. Run evidence beyond the retention window lives in the job's
    runHistory and monitoring snapshots, not in raw parquet. 0 disables
    expiry — check your regulator's expectations before lowering this.
  EOT
  type        = number
  default     = 90
}

# ---- EMR Serverless -------------------------------------------------------------

variable "emr_release_label" {
  description = "EMR Serverless release for every tenant application."
  type        = string
  default     = "emr-7.5.0"
}

variable "emr_idle_timeout_minutes" {
  description = "Auto-stop idle timeout per application (cost guard)."
  type        = number
  default     = 15
}

variable "emr_maximum_capacity" {
  description = "Per-application capacity ceiling (cost guard). Null = EMR defaults."
  type = object({
    cpu    = string # e.g. "64 vCPU"
    memory = string # e.g. "512 GB"
  })
  default = {
    cpu    = "64 vCPU"
    memory = "512 GB"
  }
  nullable = true
}

# ---- Snowflake storage integration ----------------------------------------------

variable "snowflake_iam_user_arn" {
  description = <<-EOT
    STORAGE_AWS_IAM_USER_ARN from `DESC INTEGRATION <name>` in Snowflake.
    Leave empty on the FIRST apply (the trust policy then only trusts this
    account as a placeholder); create the integration in Snowflake pointing
    at snowflake_integration_role_arn, read the two DESC values back, set
    both variables, and apply again. See the README handshake section.
  EOT
  type        = string
  default     = ""
}

variable "snowflake_external_id" {
  description = "STORAGE_AWS_EXTERNAL_ID from `DESC INTEGRATION <name>` (second apply of the handshake)."
  type        = string
  default     = ""
}

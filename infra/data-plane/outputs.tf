output "bucket_names" {
  description = "The three platform buckets, keyed data / models / platform."
  value       = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "tenant_execution" {
  description = <<-EOT
    Per-tenant execution config — exactly the body a PlatformAdmin enters
    via PUT /tenants/{tenant_id}/execution after onboarding the tenant.
  EOT
  value = {
    for t in var.tenant_ids : t => {
      emrApplicationId    = aws_emrserverless_application.tenant[t].id
      emrExecutionRoleArn = aws_iam_role.emr_execution[t].arn
      dataS3Prefix        = "s3://${aws_s3_bucket.this["data"].bucket}/${t}/"
    }
  }
}

output "emr_application_arns" {
  description = "Feed to the backend module's emr_application_arns."
  value       = [for t in var.tenant_ids : aws_emrserverless_application.tenant[t].arn]
}

output "emr_execution_role_arns" {
  description = "Feed to the backend module's emr_execution_role_arns."
  value       = [for t in var.tenant_ids : aws_iam_role.emr_execution[t].arn]
}

output "dq_s3_read_arns" {
  description = "Feed to the backend module's dq_s3_read_arns (bucket + objects, for the real DQ engine)."
  value = [
    aws_s3_bucket.this["data"].arn,
    "${aws_s3_bucket.this["data"].arn}/*",
  ]
}

output "snowflake_integration_role_arn" {
  description = "STORAGE_AWS_ROLE_ARN for CREATE STORAGE INTEGRATION in Snowflake."
  value       = aws_iam_role.snowflake_integration.arn
}

output "entrypoint_s3_uri" {
  description = "Where to upload backend/emr/scoring_entrypoint.py — set the backend's EMR_ENTRYPOINT_S3_URI to this."
  value       = "s3://${aws_s3_bucket.this["platform"].bucket}/entrypoints/scoring_entrypoint.py"
}

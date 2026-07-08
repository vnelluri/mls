# The platform's three buckets. Names carry the account id — bucket names are
# global, and this keeps the module appliable in any account without input.
#
#   data      <prefix>-data-<acct>      per-tenant run data: Snowflake unload
#                                       staging + scoring output, always under
#                                       s3://<bucket>/<tenant_id>/... (the
#                                       tenant's dataS3Prefix; enforced by the
#                                       API at pipeline create)
#   models    <prefix>-models-<acct>    registered model artifacts, versioned
#                                       (an artifact referenced by the registry
#                                       must never silently change)
#   platform  <prefix>-platform-<acct>  platform assets: the scoring
#                                       entrypoint under entrypoints/, versioned

data "aws_caller_identity" "current" {}

locals {
  buckets = {
    data     = { versioned = false }
    models   = { versioned = true }
    platform = { versioned = true }
  }
  bucket_name = { for k, _ in local.buckets : k => "${var.name_prefix}-${k}-${data.aws_caller_identity.current.account_id}" }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets

  bucket = local.bucket_name[each.key]
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = { for k, b in local.buckets : k => b if b.versioned }

  bucket = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == "" ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn == "" ? null : var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != ""
  }
}

# Run data is transient by design (every run writes fresh <date>/<runId>/
# prefixes); expire it so cost doesn't grow with every run forever.
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.this["data"].id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = var.data_retention_days > 0 ? [1] : []
    content {
      id     = "expire-run-data"
      status = "Enabled"
      filter {}
      expiration {
        days = var.data_retention_days
      }
    }
  }
}

# TLS-only, on every bucket.
data "aws_iam_policy_document" "bucket_tls_only" {
  for_each = aws_s3_bucket.this

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      each.value.arn,
      "${each.value.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  policy = data.aws_iam_policy_document.bucket_tls_only[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

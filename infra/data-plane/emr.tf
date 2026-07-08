# One EMR Serverless application + one job execution role PER TENANT. The
# application id and role ARN go into the tenant's execution config
# (PUT /tenants/{id}/execution) — the platform resolves them from there when
# an execute_model step starts, and the backend task role may only pass the
# roles listed in its emr_execution_role_arns allowlist. The role is the
# tenant-isolation boundary for compute: it can read/write ONLY its tenant's
# prefixes, so even a malicious scoring script cannot touch another tenant's
# data.

resource "aws_emrserverless_application" "tenant" {
  for_each = var.tenant_ids

  name          = "${var.name_prefix}-${each.key}"
  release_label = var.emr_release_label
  type          = "spark"

  auto_start_configuration {
    enabled = true
  }

  auto_stop_configuration {
    enabled              = true
    idle_timeout_minutes = var.emr_idle_timeout_minutes
  }

  dynamic "maximum_capacity" {
    for_each = var.emr_maximum_capacity == null ? [] : [var.emr_maximum_capacity]
    content {
      cpu    = maximum_capacity.value.cpu
      memory = maximum_capacity.value.memory
    }
  }

  tags = merge(var.tags, { tenant = each.key })
}

data "aws_iam_policy_document" "emr_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["emr-serverless.amazonaws.com"]
    }
    # Confused-deputy guard: only job runs from THIS account may assume the
    # role. (The application ARN itself can't be referenced here without a
    # dependency cycle — account scoping is the standard mitigation.)
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "emr_execution" {
  for_each = var.tenant_ids

  name               = "${var.name_prefix}-${each.key}-emr-execution"
  assume_role_policy = data.aws_iam_policy_document.emr_assume.json
  tags               = merge(var.tags, { tenant = each.key })
}

data "aws_iam_policy_document" "emr_execution" {
  for_each = var.tenant_ids

  # Run data: read the unload staging, write the scoring output — both live
  # under the tenant's own prefix (Spark also deletes _temporary/ files and
  # overwrite-mode targets, hence DeleteObject).
  statement {
    sid = "TenantRunData"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.this["data"].arn}/${each.key}/*"]
  }

  statement {
    sid       = "TenantDataList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.this["data"].arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${each.key}/*", "${each.key}"]
    }
  }

  # Model artifacts: read-only, own tenant only.
  statement {
    sid       = "TenantModelArtifacts"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["models"].arn}/${each.key}/*"]
  }

  # The scoring entrypoint script (shared platform asset).
  statement {
    sid     = "PlatformEntrypoints"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.this["platform"].arn}/entrypoints/*",
    ]
  }
}

resource "aws_iam_role_policy" "emr_execution" {
  for_each = var.tenant_ids

  name   = "tenant-scoped-s3"
  role   = aws_iam_role.emr_execution[each.key].id
  policy = data.aws_iam_policy_document.emr_execution[each.key].json
}

# KMS decrypt/encrypt when the buckets use a CMK — without this, every real
# job run fails on the first GetObject.
data "aws_iam_policy_document" "emr_execution_kms" {
  count = var.kms_key_arn == "" ? 0 : 1

  statement {
    sid = "BucketCmk"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "emr_execution_kms" {
  for_each = var.kms_key_arn == "" ? toset([]) : var.tenant_ids

  name   = "bucket-cmk"
  role   = aws_iam_role.emr_execution[each.key].id
  policy = data.aws_iam_policy_document.emr_execution_kms[0].json
}

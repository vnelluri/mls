# The AWS half of the Snowflake STORAGE INTEGRATION: the IAM role Snowflake
# assumes for BOTH directions of COPY INTO — writing unloads into the data
# bucket AND reading a run's scored output back out for the
# load_to_snowflake step. Two-step handshake (see README): first apply with
# the snowflake_* variables empty (placeholder trust: this account only),
# create the integration in Snowflake pointing at this role's ARN, then set
# the two DESC INTEGRATION values and apply again to pin the trust to
# Snowflake's IAM user + external id.
#
# Scope note: Snowflake gets write access to the whole data bucket rather
# than per-tenant paths, because unload destinations are tenant-chosen. The
# API is the guard: it validates every destination under the requesting
# tenant's dataS3Prefix before any SQL is issued, and only the platform's
# service account can issue that SQL.

data "aws_iam_policy_document" "snowflake_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type = "AWS"
      identifiers = [
        var.snowflake_iam_user_arn != "" ? var.snowflake_iam_user_arn : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
      ]
    }

    dynamic "condition" {
      for_each = var.snowflake_external_id == "" ? [] : [1]
      content {
        test     = "StringEquals"
        variable = "sts:ExternalId"
        values   = [var.snowflake_external_id]
      }
    }
  }
}

resource "aws_iam_role" "snowflake_integration" {
  name               = "${var.name_prefix}-snowflake-integration"
  assume_role_policy = data.aws_iam_policy_document.snowflake_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "snowflake_integration" {
  # What COPY INTO <s3://...> (unload) needs: put the parquet files (and
  # delete them — the platform unloads with OVERWRITE = TRUE).
  statement {
    sid = "UnloadObjects"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.this["data"].arn}/*"]
  }

  # What COPY INTO <table> FROM <s3://...> (load_to_snowflake) needs: read
  # the run's scored output back out. Read-only — the load step never
  # writes to S3, only to the destination Snowflake table.
  statement {
    sid       = "LoadObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["data"].arn}/*"]
  }

  statement {
    sid       = "DataBucketList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.this["data"].arn]
  }
}

resource "aws_iam_role_policy" "snowflake_integration" {
  name   = "data-bucket-unload"
  role   = aws_iam_role.snowflake_integration.id
  policy = data.aws_iam_policy_document.snowflake_integration.json
}

resource "aws_iam_role_policy" "snowflake_integration_kms" {
  count = var.kms_key_arn == "" ? 0 : 1

  name   = "bucket-cmk"
  role   = aws_iam_role.snowflake_integration.id
  policy = data.aws_iam_policy_document.emr_execution_kms[0].json
}

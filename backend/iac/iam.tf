data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---- Execution role: image pull, logs, SSM secret injection -----------------

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-backend-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    sid     = "ReadInjectedParameters"
    actions = ["ssm:GetParameters"]
    resources = concat(
      values(var.entra_parameter_arns),
      values(var.snowflake_parameter_arns),
    )
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-entra-parameters"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# ---- Task role: least-privilege DynamoDB access ------------------------------

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-backend-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "task_dynamodb" {
  statement {
    sid = "TableAccess"
    # Exactly what the repositories use: item CRUD, Query (never Scan except
    # the small tenants table), and the transactional snapshot+model write.
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:ConditionCheckItem",
    ]
    resources = concat(
      [for t in aws_dynamodb_table.this : t.arn],
      [for t in aws_dynamodb_table.this : "${t.arn}/index/*"],
    )
  }
}

resource "aws_iam_role_policy" "task_dynamodb" {
  name   = "dynamodb-mlserv-tables"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_dynamodb.json
}

# EMR Serverless permissions for EMR_MODE=real, scoped to exactly the
# per-tenant applications and job execution roles registered in the tenants'
# execution config. StartJobRun carries an executionRoleArn, so the task role
# also needs iam:PassRole on those roles — but ONLY toward the EMR Serverless
# service: without the PassedToService condition, this permission would let
# the API hand any listed role to any service.
data "aws_iam_policy_document" "task_emr" {
  statement {
    sid = "EmrServerlessJobRuns"
    actions = [
      "emr-serverless:StartJobRun",
      "emr-serverless:GetJobRun",
      "emr-serverless:CancelJobRun",
    ]
    # Job-run ARNs are children of the application ARN.
    resources = concat(
      var.emr_application_arns,
      [for arn in var.emr_application_arns : "${arn}/jobruns/*"],
    )
  }

  statement {
    sid       = "PassEmrJobExecutionRoles"
    actions   = ["iam:PassRole"]
    resources = var.emr_execution_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["emr-serverless.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "task_emr" {
  count  = var.emr_mode == "real" ? 1 : 0
  name   = "emr-serverless-job-runs"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_emr.json

  lifecycle {
    # Same fail-fast policy as the app: real mode with an empty allowlist
    # would produce a policy that can start nothing (or, worse, tempt a "*").
    precondition {
      condition     = length(var.emr_application_arns) > 0 && length(var.emr_execution_role_arns) > 0
      error_message = "emr_mode = \"real\" requires emr_application_arns and emr_execution_role_arns (one per tenant)."
    }
  }
}

# S3 read access for the real DQ engine (DQ_MODE=real): list + get on the
# scoring-output locations named in dq_s3_read_arns. Attach only when used.
data "aws_iam_policy_document" "task_dq_s3" {
  statement {
    sid = "DqScoringOutputRead"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = var.dq_s3_read_arns
  }
}

resource "aws_iam_role_policy" "task_dq_s3" {
  count  = length(var.dq_s3_read_arns) > 0 ? 1 : 0
  name   = "dq-scoring-output-read"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_dq_s3.json
}

# Artifacts bucket: model-artifact uploads (POST /models/artifacts). Write +
# head only -- the API never reads artifacts back (EMR job execution roles
# carry the read grants); deliberately no s3:DeleteObject or s3:CreateBucket
# (the bucket is provisioned out-of-band, matching artifacts_bucket_name).
data "aws_iam_policy_document" "task_artifacts_s3" {
  statement {
    sid       = "ArtifactUploadWrite"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["arn:aws:s3:::${var.artifacts_bucket_name}/*"]
  }

  statement {
    sid       = "ArtifactBucketHead"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.artifacts_bucket_name}"]
  }
}

resource "aws_iam_role_policy" "task_artifacts_s3" {
  count  = var.artifacts_bucket_name != "" ? 1 : 0
  name   = "artifacts-bucket-upload"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_artifacts_s3.json
}

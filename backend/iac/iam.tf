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
    sid       = "ReadEntraParameters"
    actions   = ["ssm:GetParameters"]
    resources = values(var.entra_parameter_arns)
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

# EMR Serverless permissions for EMR_MODE=real. Scoped to start/describe/
# cancel job runs; attach only when the real executor is enabled.
data "aws_iam_policy_document" "task_emr" {
  statement {
    sid = "EmrServerlessJobRuns"
    actions = [
      "emr-serverless:StartJobRun",
      "emr-serverless:GetJobRun",
      "emr-serverless:CancelJobRun",
    ]
    resources = ["*"] # narrow to specific application ARNs per tenant setup
  }
}

resource "aws_iam_role_policy" "task_emr" {
  count  = var.emr_mode == "real" ? 1 : 0
  name   = "emr-serverless-job-runs"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_emr.json
}

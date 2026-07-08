locals {
  create_cluster = var.cluster_arn == ""
  cluster_arn    = local.create_cluster ? aws_ecs_cluster.this[0].arn : var.cluster_arn
  service_name   = "${var.name_prefix}-backend"

  base_environment = {
    AUTH_MODE                  = "prod"
    AWS_REGION                 = var.aws_region
    DDB_ENDPOINT_URL           = "" # empty -> real DynamoDB via the task role
    EMR_MODE                   = var.emr_mode
    SNOWFLAKE_MODE             = var.snowflake_mode
    DQ_MODE                    = var.dq_mode
    CORS_ALLOWED_ORIGINS       = var.cors_allowed_origins
    TABLE_TENANTS              = aws_dynamodb_table.this["tenants"].name
    TABLE_GROUP_MAPPINGS       = aws_dynamodb_table.this["group-mappings"].name
    TABLE_PIPELINES            = aws_dynamodb_table.this["pipelines"].name
    TABLE_JOBS                 = aws_dynamodb_table.this["jobs"].name
    TABLE_MODELS               = aws_dynamodb_table.this["models"].name
    TABLE_MONITORING_SNAPSHOTS = aws_dynamodb_table.this["monitoring-snapshots"].name
    TABLE_AUDIT                = aws_dynamodb_table.this["audit"].name
  }

  environment = merge(local.base_environment, var.extra_environment)
}

resource "aws_ecs_cluster" "this" {
  count = local.create_cluster ? 1 : 0
  name  = "${var.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_ecr_repository" "this" {
  count                = var.create_ecr_repository ? 1 : 0
  name                 = local.service_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.service_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_ecs_task_definition" "this" {
  family                   = local.service_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = local.service_name
      image     = var.container_image
      essential = true

      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]

      environment = [
        for k, v in local.environment : { name = k, value = v }
      ]

      # Entra + Snowflake settings arrive as SSM-parameter secrets. The app
      # fails fast at startup if a required one is blank (AUTH_MODE=prod /
      # SNOWFLAKE_MODE=real).
      secrets = [
        for k, arn in merge(var.entra_parameter_arns, var.snowflake_parameter_arns) :
        { name = k, valueFrom = arn }
      ]

      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)\" || exit 1",
        ]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 15
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "backend"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "this" {
  name            = local.service_name
  cluster         = local.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # >1 task is safe: job writes are optimistically locked and snapshots are
  # idempotent per run, so the per-task background refresh loops coordinate
  # through DynamoDB conditional writes.
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = var.assign_public_ip
  }

  dynamic "load_balancer" {
    for_each = var.target_group_arn == "" ? [] : [var.target_group_arn]
    content {
      target_group_arn = load_balancer.value
      container_name   = local.service_name
      container_port   = 8000
    }
  }

  health_check_grace_period_seconds = var.target_group_arn == "" ? null : var.health_check_grace_period_seconds
  propagate_tags                    = "SERVICE"

  tags = var.tags
}

# ECS Fargate service for the frontend (nginx serving the built SPA),
# mirroring infrastructure/ecs-task-def.json / ecs-service.json.
#
# NOTE: pick one provisioning path — this module OR the JSON task-def/service
# files under infrastructure/ — never both (same names).

locals {
  create_cluster = var.cluster_arn == ""
  cluster_arn    = local.create_cluster ? aws_ecs_cluster.this[0].arn : var.cluster_arn
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role only — the container serves static assets and needs no AWS
# API access of its own, so no task role is attached.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_cluster" "this" {
  count = local.create_cluster ? 1 : 0
  name  = "${var.name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_ecr_repository" "this" {
  count                = var.create_ecr_repository ? 1 : 0
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = var.container_image
      essential = true

      portMappings = [
        { containerPort = 80, protocol = "tcp" }
      ]

      environment = [
        for k, v in var.extra_environment : { name = k, value = v }
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "wget -q -O - http://localhost:80/ || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "frontend"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "this" {
  name            = var.name
  cluster         = local.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

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
      container_name   = "frontend"
      container_port   = 80
    }
  }

  health_check_grace_period_seconds = var.target_group_arn == "" ? null : var.health_check_grace_period_seconds
  propagate_tags                    = "SERVICE"

  tags = var.tags
}

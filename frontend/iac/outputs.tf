output "cluster_arn" {
  value = local.cluster_arn
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "ecr_repository_url" {
  value = var.create_ecr_repository ? aws_ecr_repository.this[0].repository_url : null
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}

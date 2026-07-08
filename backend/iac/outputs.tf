output "table_names" {
  description = "All 7 DynamoDB table names, keyed by logical name."
  value       = { for k, t in aws_dynamodb_table.this : k => t.name }
}

output "table_arns" {
  value = { for k, t in aws_dynamodb_table.this : k => t.arn }
}

output "task_role_arn" {
  description = "Role the API runs as (DynamoDB + optional EMR access)."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "cluster_arn" {
  value = local.cluster_arn
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}

output "ecr_repository_url" {
  value = var.create_ecr_repository ? aws_ecr_repository.this[0].repository_url : null
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}

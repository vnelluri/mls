variable "name" {
  description = "Base name for every resource."
  type        = string
  default     = "ml-serving-monitoring-frontend"
}

variable "aws_region" {
  description = "Region for log configuration."
  type        = string
  default     = "us-east-1"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}

variable "cluster_arn" {
  description = "Existing ECS cluster to deploy into (typically the backend's). Leave empty to create a dedicated one."
  type        = string
  default     = ""
}

variable "container_image" {
  description = "Frontend image (nginx serving the Vite build), e.g. <account>.dkr.ecr.<region>.amazonaws.com/ml-serving-monitoring-frontend:<tag>. Build args / VITE_* env are baked at image build time."
  type        = string
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Service task count."
  type        = number
  default     = 2
}

variable "subnet_ids" {
  description = "Private subnets for the service's awsvpc ENIs."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups for the service ENIs (must allow the ALB to reach port 80)."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "Assign public IPs to task ENIs. Keep false; the ALB fronts the service."
  type        = bool
  default     = false
}

variable "target_group_arn" {
  description = "ALB target group forwarding to the frontend (port 80). Empty = no load balancer attachment."
  type        = string
  default     = ""
}

variable "health_check_grace_period_seconds" {
  type    = number
  default = 30
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the service log group."
  type        = number
  default     = 30
}

variable "create_ecr_repository" {
  description = "Also create an ECR repository named after the service."
  type        = bool
  default     = false
}

variable "extra_environment" {
  description = "Plain environment variables for the container. Note: the SPA reads VITE_* at BUILD time — runtime env only affects nginx itself."
  type        = map(string)
  default     = {}
}

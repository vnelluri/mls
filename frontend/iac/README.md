# Frontend IaC (Terraform module)

ECS Fargate service for the frontend — an nginx container serving the built
SPA on port 80: log group, task definition with the wget health check, and a
circuit-breaker service optionally attached to an ALB target group. Creates
a dedicated cluster unless you pass one in (typically you'd reuse the
backend's).

Networking (VPC, subnets, security groups, the ALB itself) is out of scope:
pass in what your landing zone provides. Remember the SPA reads its `VITE_*`
configuration (API base URL, Entra client id, demo mode) at **build time** —
bake it into the image; runtime container env cannot change it.

## Usage

```hcl
module "mlserv_frontend" {
  source = "./frontend/iac"

  aws_region      = "us-east-1"
  container_image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/ml-serving-monitoring-frontend:v1.0.0"

  cluster_arn        = module.mlserv_backend.cluster_arn # share the backend's cluster
  subnet_ids         = ["subnet-priv-a", "subnet-priv-b"]
  security_group_ids = [aws_security_group.frontend.id]
  target_group_arn   = aws_lb_target_group.frontend.arn

  tags = { app = "mlserv", env = "prod" }
}
```

The frontend's origin (the ALB/CloudFront URL in front of this service) must
appear in the backend's `cors_allowed_origins`.

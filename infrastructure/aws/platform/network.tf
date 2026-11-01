# VPC with two public and two private subnets, and no NAT gateway (it would
# cost more than everything else here). Application tasks run in the public
# subnets with public IPs so they can reach ECR, Secrets Manager and
# CloudWatch; their security group only admits the ALB. RDS sits in the
# private subnets with no route to the internet.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # Cloud Map private DNS needs both
  tags                 = { Name = "syncwave" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "syncwave" }
}

resource "aws_subnet" "public" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  tags              = { Name = "syncwave-public-${local.azs[count.index]}" }
}

resource "aws_subnet" "private" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.this.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  tags              = { Name = "syncwave-private-${local.azs[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "syncwave-public" }

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "syncwave-private" }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Free: S3 traffic (audio downloads by the workers) stays on the AWS network
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id, aws_route_table.private.id]
  tags              = { Name = "syncwave-s3" }
}

# ---------------------------------------------------------------------------
# Security groups

resource "aws_security_group" "alb" {
  name        = "syncwave-alb"
  description = "Public HTTP(S) into the load balancer"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "alb_to_services" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.services.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

# Every application task (and the db-init tasks) uses this group
resource "aws_security_group" "services" {
  name        = "syncwave-services"
  description = "Application tasks: port 8080 from the ALB, service ports from each other"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_ingress_rule" "services_from_alb" {
  security_group_id            = aws_security_group.services.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

# Service-to-service calls, as in Compose: HTTP on 8080 (Playlist and
# Recommendation call the Catalogue), the Streaming Service on 8081 (Sync
# calls it) and gRPC on 50051 (Jam calls Playlist, Sync calls Catalogue).
# Only tasks in this group can reach these ports; the ALB still reaches 8080 only.
resource "aws_vpc_security_group_ingress_rule" "services_from_services" {
  for_each = {
    http      = 8080
    streaming = 8081
    grpc      = 50051
  }

  security_group_id            = aws_security_group.services.id
  referenced_security_group_id = aws_security_group.services.id
  description                  = "Service to service (${each.key})"
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

resource "aws_vpc_security_group_egress_rule" "services_all" {
  security_group_id = aws_security_group.services.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "rds" {
  name        = "syncwave-rds"
  description = "Postgres from application tasks"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_services" {
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.services.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_security_group" "rabbitmq" {
  name        = "syncwave-rabbitmq"
  description = "AMQP from application tasks"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_ingress_rule" "rabbitmq_from_services" {
  security_group_id            = aws_security_group.rabbitmq.id
  referenced_security_group_id = aws_security_group.services.id
  ip_protocol                  = "tcp"
  from_port                    = 5672
  to_port                      = 5672
}

# Pulls its images and writes logs over the internet, like the services
resource "aws_vpc_security_group_egress_rule" "rabbitmq_all" {
  security_group_id = aws_security_group.rabbitmq.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

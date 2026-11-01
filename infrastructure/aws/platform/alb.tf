# The production gateway: one Application Load Balancer in front of every
# service. Each service stack adds its own listener rule for
# /api/<service>/* (modules/ecs-service), mirroring
# infrastructure/gateway/nginx.conf. Unknown paths get the same 404 body.

locals {
  https     = var.certificate_arn != null
  not_found = jsonencode({ error = { code = "UNKNOWN_SERVICE", message = "No service is routed at this path" } })
}

resource "aws_lb" "this" {
  name               = "syncwave"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  # nginx keeps proxied connections open for 1h, so Jam/Sync WebSockets stay up
  idle_timeout = 3600
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.https ? "redirect" : "fixed-response"

    dynamic "redirect" {
      for_each = local.https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "fixed_response" {
      for_each = local.https ? [] : [1]
      content {
        content_type = "application/json"
        message_body = local.not_found
        status_code  = "404"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = local.https ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = local.not_found
      status_code  = "404"
    }
  }
}

locals {
  # The listener that service routes attach to
  app_listener_arn = local.https ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
}

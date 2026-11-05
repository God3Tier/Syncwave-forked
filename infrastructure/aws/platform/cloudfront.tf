# HTTPS without a domain name. CloudFront serves the whole site at
# https://<id>.cloudfront.net with its own certificate and passes every request,
# WebSocket upgrades included, to the ALB over HTTP, uncached and with every
# header, cookie and query string. Browsers only allow location (Discover's
# weather match) and the clipboard on HTTPS pages. The ALB stays reachable on
# its own http:// name. Off with -var cloudfront_enabled=false.

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

resource "aws_cloudfront_distribution" "this" {
  count           = var.cloudfront_enabled ? 1 : 0
  enabled         = true
  comment         = "syncwave"
  http_version    = "http2and3"
  is_ipv6_enabled = true
  # North America, Europe and Asia (Singapore included); the cheapest class
  # that still has edge locations near the team.
  price_class = "PriceClass_200"

  origin {
    origin_id   = "alb"
    domain_name = aws_lb.this.dns_name

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # The longest allowed without a quota increase. Upload answers once the
      # file is in S3, well within it.
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
    # The frontend's nginx already compresses; with caching off CloudFront would not.
    compress = false
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  lifecycle {
    precondition {
      # With a certificate the ALB's port 80 redirects to its own https:// name,
      # which would send browsers past CloudFront.
      condition     = var.certificate_arn == null
      error_message = "Use either cloudfront_enabled or certificate_arn, not both."
    }
  }
}

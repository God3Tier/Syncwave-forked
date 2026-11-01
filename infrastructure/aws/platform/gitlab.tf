# Lets the GitLab deploy job (ci/service.yml .deploy-ecs) act in AWS with a
# short-lived OIDC token instead of stored keys. Only pipelines on the main
# branch of this project can assume the role. Its ARN goes into the GitLab
# CI/CD variable AWS_ROLE_ARN (output gitlab_deploy_role_arn).

resource "aws_iam_openid_connect_provider" "gitlab" {
  count          = var.create_gitlab_oidc_provider ? 1 : 0
  url            = "https://gitlab.com"
  client_id_list = ["https://gitlab.com"]
}

data "aws_iam_openid_connect_provider" "gitlab" {
  count = var.create_gitlab_oidc_provider ? 0 : 1
  url   = "https://gitlab.com"
}

locals {
  gitlab_oidc_provider_arn = (var.create_gitlab_oidc_provider
    ? aws_iam_openid_connect_provider.gitlab[0].arn
  : data.aws_iam_openid_connect_provider.gitlab[0].arn)
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_iam_policy_document" "gitlab_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.gitlab_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "gitlab.com:aud"
      values   = ["https://gitlab.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "gitlab.com:sub"
      values   = ["project_path:${var.gitlab_project_path}:ref_type:branch:ref:${var.gitlab_deploy_branch}"]
    }
  }
}

resource "aws_iam_role" "gitlab_deploy" {
  name                 = "syncwave-gitlab-deploy"
  assume_role_policy   = data.aws_iam_policy_document.gitlab_assume.json
  max_session_duration = 3600
}

# Exactly what ci/scripts/deploy-ecs.sh does, and no more
data "aws_iam_policy_document" "gitlab_deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPushSyncwaveImages"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = ["arn:aws:ecr:${var.region}:${local.account_id}:repository/syncwave/*"]
  }

  # These two actions do not support resource-level permissions
  statement {
    sid       = "TaskDefinitions"
    actions   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid     = "UpdateSyncwaveServices"
    actions = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = [
      "arn:aws:ecs:${var.region}:${local.account_id}:service/${var.cluster_name}/*",
    ]
  }

  # Registering a task definition passes its execution and task roles
  statement {
    sid       = "PassSyncwaveTaskRoles"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/syncwave-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "gitlab_deploy" {
  name   = "deploy-to-ecs"
  role   = aws_iam_role.gitlab_deploy.id
  policy = data.aws_iam_policy_document.gitlab_deploy.json
}

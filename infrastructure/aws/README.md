# Production on AWS (placeholder)

Production per plan.md §17: images in **ECR**, containers on **ECS**, audio
in **S3**. The pipeline side is ready (`ci/service.yml` `.deploy-ecs`,
`ci/scripts/deploy-ecs.sh`). The AWS side below still has to be created.
Ideally create it as code in this folder, so it can be reviewed and rebuilt.

## What the deploy job expects

| Thing                    | Convention                                                   |
|--------------------------|--------------------------------------------------------------|
| ECR repository           | `syncwave/<service>` (e.g. `syncwave/lyrics`)                |
| ECS cluster              | name in CI variable `ECS_CLUSTER`                            |
| ECS service              | `<service>`, or `<service>-worker` for extra processes       |
| Task definition family   | `syncwave-<ecs service>`, a single container per task        |
| Health check             | container listens on 8080, `GET /health` returns 200          |

The deploy job copies the tested image to ECR, registers a new task
definition revision that changes only the image, and updates the service.
CPU, memory, environment variables and secrets live in the task definition.

## GitLab CI/CD variables (Settings > CI/CD > Variables; protected)

| Variable        | Example                                                      |
|-----------------|--------------------------------------------------------------|
| `AWS_ROLE_ARN`  | `arn:aws:iam::<account>:role/syncwave-gitlab-deploy`. Deploy jobs appear only once this is set |
| `AWS_REGION`    | `ap-southeast-1`                                             |
| `ECR_REGISTRY`  | `<account>.dkr.ecr.ap-southeast-1.amazonaws.com`             |
| `ECS_CLUSTER`   | `syncwave`                                                   |
| `WEATHER_API_KEY` | masked; injected into the Recommendation task as a secret  |

## GitLab -> AWS authentication (OIDC, no stored AWS keys)

1. IAM > Identity providers > add an OpenID Connect provider with URL
   `https://gitlab.com` and audience `https://gitlab.com`.
2. Create role `syncwave-gitlab-deploy` with a trust policy that only
   accepts this project's `main` branch:
   `"gitlab.com:sub": "project_path:cs302-2026/g4-team6/syncwave:ref_type:branch:ref:main"`.
3. Give the role only what deploying needs: ECR push to `syncwave/*`,
   `ecs:DescribeTaskDefinition`, `ecs:RegisterTaskDefinition`,
   `ecs:UpdateService`, `ecs:DescribeServices`, and `iam:PassRole` for
   the task execution role.

## Open decisions

- **RabbitMQ:** a container on ECS (cheapest; persistence needs EFS) or
  Amazon MQ (managed, but billed per hour even when idle). Load
  `infrastructure/rabbitmq/definitions.json` either way. Check current
  pricing in the AWS calculator before deciding.
- **Postgres:** RDS (managed, billed per hour) or a container (cheap,
  but data is lost unless backed by a volume).
- **Routing:** an Application Load Balancer with path rules mirroring
  `infrastructure/gateway/nginx.conf` (`/api/<service>/*`).
- **Cost:** the brief's budget is reimbursed only if it was requested in
  Week 7. Tear everything down when not demoing. A local Kubernetes
  cluster is also an accepted production environment if the budget is
  not available.

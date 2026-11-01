# Production on AWS (Terraform)

Production per plan.md §17: images in **ECR**, containers on **ECS Fargate**,
audio in **S3**, plus RDS Postgres and RabbitMQ. Everything is Terraform in
this folder. **[RUNBOOK.md](RUNBOOK.md)** has the commands: first-time
setup, smoke test, deploys, debugging, pausing between demos and teardown.

> **Status: proposal.** `platform/` is shared by every service and needs
> the team's agreement before it is applied (RabbitMQ and Postgres choices
> below, the S3 key layout with Upload). `services/lyrics` and
> `services/waveform` are the first two service stacks.

## Layout: one shared stack, one stack per service

```
infrastructure/aws/
├── bootstrap/            S3 bucket for Terraform state (run once per account; local state)
├── platform/             shared: VPC, ECS cluster, ALB, RDS, RabbitMQ, audio bucket, GitLab deploy role
├── modules/
│   ├── ecs-service/      one ECS service + task definition + logs + task role + optional ALB route
│   └── service-database/ one service's database/role on the shared RDS + its password secret
└── services/
    ├── lyrics/           ECR repo, database, API (lyrics) and worker (lyrics-worker)
    └── waveform/         ECR repo, database, API (waveform) and worker (waveform-worker)
```

- **platform** holds what every service needs and no single service owns.
  It changes rarely. Its outputs (`platform/outputs.tf`) are the contract the
  service stacks read through `terraform_remote_state`, so renaming one is a
  breaking change.
- **One root per service**, owned by the service owner. Each one has its own
  state file, so applying waveform can never change lyrics. Plans stay small,
  and owners do not block each other on the state lock.
- Every root uses the same S3 state bucket (`backend.hcl`) with a different
  key, and S3-native locking (`use_lockfile`; no DynamoDB table).

### Adding another service's stack

Copy `services/lyrics/`, then:
1. Change the names, the state `key` in `versions.tf`, the environment
   (from the service's `compose.yaml`) and the task role policy.
2. Pick an unused listener priority from the table below.
3. Make sure the ECS service names match `ECS_SERVICES` in the service's
   `.gitlab-ci.yml`.

## Architecture

```
internet ──> ALB :80 (/api/<service>/* rules, prefix rewritten away)
               │
               ▼   public subnets, tasks with public IPs, no NAT gateway
         ┌───────────────────────────────────────────────┐
         │ lyrics   waveform   (more services...)        │  SG "services": 8080 from ALB only
         │ lyrics-worker   waveform-worker               │
         │ rabbitmq (rabbitmq.syncwave.internal:5672)    │  SG "rabbitmq": 5672 from services
         └───────────────────────────────────────────────┘
               │                          │
               ▼  private subnets         ▼  S3 gateway endpoint
         RDS Postgres 17 (db per service)   S3 syncwave-audio-<account>
```

| Decision | Choice | Why |
|---|---|---|
| Routing | ALB listener rule per service, `url-rewrite` transform strips `/api/<service>` | Same contract as `infrastructure/gateway/nginx.conf`; the FastAPI routes have no prefix. Unknown paths return the same `UNKNOWN_SERVICE` 404. Idle timeout 1h (WebSockets). |
| Network | Public subnets for tasks, **no NAT gateway** | A NAT gateway costs more than everything else here. Tasks only accept traffic from the ALB; RDS has no internet route at all. |
| RabbitMQ | **One container on ECS** (Cloud Map DNS) | Cheapest. Plain AMQP inside the VPC needs no client changes (Amazon MQ requires TLS). There is no volume, so a restart loses queued messages; the topology is reloaded from `infrastructure/rabbitmq/definitions.json` by an init container. |
| Postgres | **One `db.t4g.micro` RDS instance**, one database and login role per service | Keeps the database-per-service rule of `infrastructure/postgres/init.sql` at the price of one small instance. The master password is managed by RDS in Secrets Manager. |
| Secrets | Secrets Manager `syncwave/<service>/db`, `syncwave/rabbitmq` | Injected as `DB_PASSWORD` / `AMQP_PASSWORD`; never in Terraform variables, images or Git. |
| S3 access | Per-task IAM roles, read-only on a key prefix | The APIs get no S3 access; the lyrics worker reads `lyrics/*`; the waveform worker reads `audio/*`. |
| Workers | `FARGATE_SPOT` | About 70% cheaper. An interrupted message is redelivered, and the consumers are idempotent. |

## Who owns what: Terraform vs the CI deploy job

| | Owner |
|---|---|
| ECR repository, ECS service, roles, CPU/memory, environment, secrets | Terraform |
| Which **image** a service runs | GitLab CI (`ci/scripts/deploy-ecs.sh`, on `main`) |

The deploy job copies the newest revision of task definition family
`syncwave-<ecs service>`, swaps only the image, and points the service at it.
So:

- `aws_ecs_service` ignores `task_definition`. A `terraform apply` never
  rolls back an image that CI deployed.
- Old revisions are kept (`skip_destroy`), so rollback is always possible.
- A config change made in Terraform (for example an env var) registers a new
  revision. It goes live with the **next CI deploy**, or immediately with
  RUNBOOK.md §6.

What the deploy job expects, all created here:

| Thing | Convention |
|---|---|
| ECR repository | `syncwave/<service>` |
| ECS cluster | `syncwave` (CI variable `ECS_CLUSTER`) |
| ECS service | `<service>`, plus `<service>-worker` for the AMQP consumer |
| Task definition family | `syncwave-<ecs service>`, a single container per task |
| Health check | container listens on 8080, `GET /health` returns 200 |

## ALB listener rule priorities

Each service's rule needs a unique priority on the shared listener. Claim one
here in the same merge request as the stack.

| Priority | Service | Path |
|---|---|---|
| 10 | catalogue | `/api/catalogue/*` (reserved) |
| 20 | search | `/api/search/*` (reserved) |
| 30 | streaming | `/api/streaming/*` (reserved; listens on 8081 locally) |
| 40 | upload | `/api/upload/*` (reserved) |
| **50** | **lyrics** | `/api/lyrics/*` |
| **60** | **waveform** | `/api/waveform/*` |
| 70 | playlist | `/api/playlist/*` (reserved) |
| 80 | recommendation | `/api/recommendation/*` (reserved) |
| 90 | jam | `/api/jam/*` (reserved) |
| 100 | sync | `/api/sync/*` (reserved) |

## GitLab CI/CD variables (Settings > CI/CD > Variables; protected)

| Variable | Value |
|---|---|
| `AWS_ROLE_ARN` | `terraform -chdir=platform output -raw gitlab_deploy_role_arn`. Deploy jobs appear only once this is set |
| `AWS_REGION` | `ap-southeast-1` |
| `ECR_REGISTRY` | `terraform -chdir=platform output -raw ecr_registry` |
| `ECS_CLUSTER` | `syncwave` |
| `WEATHER_API_KEY` | masked; injected into the Recommendation task as a secret |

GitLab authenticates with OIDC, so no AWS keys are stored in GitLab.
`platform/gitlab.tf` creates the provider and the `syncwave-gitlab-deploy`
role. The role trusts only this project's `main` branch, and may only push
to `syncwave/*` repositories, register task definitions, update services in
the cluster, and pass `syncwave-*` roles to ECS.

## Cost

Rough on-demand prices in ap-southeast-1, with everything running. Check the
[AWS Pricing Calculator](https://calculator.aws/) before relying on them.

| Item | ≈ per month |
|---|---|
| ALB | $18 + traffic |
| RDS db.t4g.micro + 20 GB gp3 | $20 |
| RabbitMQ task (0.5 vCPU, 1 GB) | $22 |
| Lyrics API + worker, Waveform API (0.25 vCPU, 0.5 GB each; worker on Spot) | $25 |
| Waveform worker (1 vCPU, 2 GB, Spot) | $15 |
| Public IPv4 addresses (one per task + the ALB's) | $25 |
| Secrets, logs, ECR, S3 | < $5 |
| **Total** | **≈ $130** (about $4 a day) |

The brief's budget is reimbursed only if it was requested in Week 7. **Pause
everything between demos**: RUNBOOK.md §8 brings it down to about $30/month
(the ALB, its IPs and storage). Or tear it all down (§9). A local Kubernetes cluster is also an
accepted production environment if the budget is not available.

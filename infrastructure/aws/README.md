# Production on AWS (Terraform)

Production per plan.md §17: images in **ECR**, containers on **ECS Fargate**,
audio in **S3**, plus RDS Postgres and RabbitMQ. Everything is Terraform in
this folder. **[RUNBOOK.md](RUNBOOK.md)** has the commands: bringing it up,
smoke test, deploys, debugging and teardown. Nothing stays up between
sessions: each session creates everything and destroys it again at the end.

> **Status: proposal.** `platform/` is shared by every service and needs
> the team's agreement before it is applied (RabbitMQ and Postgres choices
> below, the S3 key layout with Upload). Every service has a stack: the
> owners should review theirs (environment, sizing, what it may call).

## Layout: one shared stack, one stack per service

```
infrastructure/aws/
├── bootstrap/            S3 bucket for Terraform state (applied first, destroyed last; local state)
├── platform/             shared: VPC, ECS cluster, ALB, RDS, RabbitMQ, audio bucket, GitLab deploy role
├── modules/
│   ├── ecs-service/      one ECS service + task definition + logs + task role + optional ALB route
│   └── service-database/ one service's database/role on the shared RDS + its password secret
└── services/             one folder per service = its image name; ECS service names in brackets
    ├── catalogue/        database, API + gRPC (catalogue), worker (catalogue-worker), internal token for Sync
    ├── search/           database, API (search), worker (search-worker)
    ├── upload/           database, API (upload, writes S3), outbox publisher (upload-publisher)
    ├── audio_transmitter/  the Streaming Service (streaming) on 8081, reads S3; no database
    ├── lyrics/           database, API (lyrics), worker (lyrics-worker)
    ├── waveform/         database, API (waveform), worker (waveform-worker)
    ├── playlist/         database, API + gRPC (playlist), internal token for Jam
    ├── recommendation/   API (recommendation); no database, no worker
    ├── sync/             database, HTTP/WebSocket + gRPC (sync), internal token for Jam
    ├── jam/              database, API + WebSocket (jam)
    ├── song_request_orchestrator/  database, API (orchestrator)
    └── frontend/         the web UI (frontend), the ALB's catch-all /*
```

Each service stack also has its ECR repository. Owners: Catalogue and
Search Orvin, Upload Yonghuey, Streaming and the orchestrator Joseph, Lyrics
and Waveform Jiawen, Playlist and Recommendation Hayyun, Jam and Sync Azeez
(`plan.md` §2).

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
   `.gitlab-ci.yml`, and keep the `ecs_services` and `api_url` outputs (the
   runbook reads them).
4. Add the folder name to `SERVICES` in RUNBOOK.md §2.3 and §8 (and to
   `DB_SERVICES` if the stack has a `module.db`).

### Services that call each other

Services reach each other inside the VPC by name, as they do in Compose:

| Caller | Calls | Address (private DNS) | Token |
|---|---|---|---|
| search-worker, playlist, recommendation, streaming | Catalogue (HTTP) | `http://catalogue.syncwave.internal:8080` | none |
| sync | Catalogue (gRPC) | `catalogue.syncwave.internal:50051` | `syncwave/catalogue/internal-token` |
| sync | Streaming (HTTP) | `http://streaming.syncwave.internal:8081` | none |
| jam | Sync (gRPC) | `sync.syncwave.internal:50051` | `syncwave/sync/internal-token` |
| jam | Playlist (gRPC) | `playlist.syncwave.internal:50051` | `syncwave/playlist/internal-token` |
| orchestrator | Playlist, Streaming, Lyrics, Waveform (HTTP) | `playlist`/`lyrics`/`waveform` `:8080`, `streaming:8081` | none |

- **Names:** pass `service_discovery = { namespace_id = local.platform.service_discovery_namespace_id, name = "<service>" }`
  to `modules/ecs-service` and the service is reachable as
  `<service>.syncwave.internal`. Callers build the name from
  `local.platform.service_discovery_namespace`. A name exists only while its
  stack is up; RUNBOOK.md §2.3 ("Leaving a service out") lists each caller's
  fallback.
- **Ports:** `extra_ports` publishes ports besides the routed one (gRPC:
  `[50051]`), and `port` changes the routed one (Streaming: 8081). The
  `services` security group lets tasks in the group reach 8080, 8081 and
  50051 on each other; the ALB reaches 8080 and 8081.
- **Tokens shared between services:** the stack of the service being *called*
  creates the secret and outputs its ARN as `internal_token_secret_arn`, next
  to `grpc_target`. The caller's stack reads both through
  `terraform_remote_state` with `defaults`, so a missing stack gives an empty
  target and the caller's built-in fake (Sync, Jam). Apply the called service
  first (the order of `SERVICES` in RUNBOOK.md §2.3).

## Architecture

```
internet ──> CloudFront https://<id>.cloudfront.net (no caching; WebSockets pass through)
               │ HTTP
               ▼
             ALB :80   /api/<service>/*  -> that service, prefix rewritten away
               │       /api/* (anything else) -> 404 UNKNOWN_SERVICE
               │       /*                -> frontend
               ▼   public subnets, tasks with public IPs, no NAT gateway
         ┌────────────────────────────────────────────────────────────┐
         │ frontend                                                   │  SG "services": 8080 and 8081
         │ catalogue  search  upload  streaming(:8081)  lyrics        │  from the ALB; 8080, 8081 and
         │ waveform  playlist  recommendation  jam  sync  orchestrator│  50051 between services
         │ catalogue-worker  search-worker  upload-publisher          │
         │ lyrics-worker  waveform-worker                             │
         │ rabbitmq (rabbitmq.syncwave.internal:5672)                 │  SG "rabbitmq": 5672 from services
         └────────────────────────────────────────────────────────────┘
               │                          │
               ▼  private subnets         ▼  S3 gateway endpoint
         RDS Postgres 17 (db per service)   S3 syncwave-audio-<account>
```

| Decision | Choice | Why |
|---|---|---|
| Routing | ALB listener rule per service, `url-rewrite` transform strips `/api/<service>` | Same contract as `infrastructure/gateway/nginx.conf`; the FastAPI routes have no prefix. Unknown paths return the same `UNKNOWN_SERVICE` 404. Idle timeout 1h (WebSockets). |
| HTTPS | **CloudFront** in front of the ALB, default `*.cloudfront.net` certificate, caching off | No domain or certificate to buy or validate. Browsers allow location and the clipboard only on HTTPS pages. All headers, cookies and query strings are forwarded, so the APIs and WebSockets behave as on the ALB. With a domain, `-var certificate_arn=… -var cloudfront_enabled=false` puts HTTPS on the ALB instead. |
| Network | Public subnets for tasks, **no NAT gateway** | A NAT gateway costs more than everything else here. Tasks only accept traffic from the ALB; RDS has no internet route at all. |
| RabbitMQ | **One container on ECS** (Cloud Map DNS) | Cheapest. Plain AMQP inside the VPC needs no client changes (Amazon MQ requires TLS). There is no volume, so a restart loses queued messages; the topology is reloaded from `infrastructure/rabbitmq/definitions.json` by an init container. |
| Postgres | **One `db.t4g.small` RDS instance**, one database and login role per service | Keeps the database-per-service rule of `infrastructure/postgres/init.sql` at the price of one small instance. A micro's connection limit is too low for nine services' pools (`-var db_instance_class=db.t4g.micro` is fine for a few). The master password is managed by RDS in Secrets Manager. |
| Secrets | Secrets Manager `syncwave/<service>/db`, `syncwave/rabbitmq`, `syncwave/<service>/internal-token` | Injected as `DB_PASSWORD` / `AMQP_PASSWORD` / the tokens; never in Terraform variables, images or Git. Every service takes `DB_*` with the password on its own (Jam, Sync and the orchestrator were changed to accept it as well as `DATABASE_URL`). |
| S3 access | Per-task IAM roles, limited to a key prefix | Upload's API writes `audio/*` and `lyrics/*`; Streaming and the waveform worker read `audio/*`; the lyrics worker reads `lyrics/*`. Every other task has no S3 access. |
| Workers | `FARGATE_SPOT` | About 70% cheaper. An interrupted message is redelivered (or, for Upload's publisher, picked up again from the outbox), and the consumers are idempotent. |
| Worker start | Each worker waits for its API (`wait_for_steady_state`) | The API runs the migrations; a worker started first on an empty database would dead-letter its first messages. |
| Jam, Sync, orchestrator | **Exactly one task each** (`desired_count` 0 or 1), on-demand Fargate | They keep WebSockets, timing state and playback sessions in memory. A second task would split the participants; Spot would drop every connection on an interruption. |
| Streaming | Routed on **8081** (the module's `port`) | The service binds 8081 (`services/audio_transmitter/src/main.rs`), as behind the local gateway. |
| Frontend | ALB catch-all `/*` (priority 1000), behind a `/api/*` 404 rule (900) | Same split as the gateway's `location /`; unknown APIs still get `UNKNOWN_SERVICE` instead of the SPA's `index.html`. |
| Sync's `/internal/*` HTTP routes | 404 on the ALB (priority 99) | They are guarded only by the internal token and Jam uses gRPC, so nothing outside the VPC needs them. |

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
| ECR repository | `syncwave/<SERVICE>`, the folder and image name |
| ECS cluster | `syncwave` (CI variable `ECS_CLUSTER`) |
| ECS service | `ECS_SERVICES` in the service's `.gitlab-ci.yml`, or `<SERVICE>` when unset. Must match the stack's `ecs_services` output. Names with `_` need `ECS_SERVICES` (target group names allow only hyphens): `audio_transmitter` deploys `streaming`, `song_request_orchestrator` deploys `orchestrator` |
| Task definition family | `syncwave-<ecs service>`, a single container per task |
| Health check | container listens on 8080, `GET /health` returns 200 |

## ALB listener rule priorities

Each service's rule needs a unique priority on the shared listener. Claim one
here in the same merge request as the stack.

| Priority | Service | Path |
|---|---|---|
| 10 | catalogue | `/api/catalogue/*` |
| 20 | search | `/api/search/*` |
| 30 | streaming | `/api/streaming/*` (port 8081) |
| 40 | upload | `/api/upload/*` |
| 50 | lyrics | `/api/lyrics/*` |
| 60 | waveform | `/api/waveform/*` |
| 70 | playlist | `/api/playlist/*` |
| 80 | recommendation | `/api/recommendation/*` |
| 90 | jam | `/api/jam/*` |
| 99 | sync (block) | `/api/sync/internal/*` → 404 |
| 100 | sync | `/api/sync/*` |
| 110 | orchestrator | `/api/orchestrator/*` |
| 900 | platform | any other `/api/*` → 404 `UNKNOWN_SERVICE` |
| 1000 | frontend | `/*`, no rewrite; must stay the last rule |

## GitLab CI/CD variables (Settings > CI/CD > Variables; protected)

| Variable | Value |
|---|---|
| `AWS_ROLE_ARN` | `terraform -chdir=platform output -raw gitlab_deploy_role_arn`. Deploy jobs appear only once this is set |
| `AWS_REGION` | `ap-southeast-1` |
| `ECR_REGISTRY` | `terraform -chdir=platform output -raw ecr_registry` |
| `ECS_CLUSTER` | `syncwave` |

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
| ALB | $20 + traffic |
| CloudFront | $0 at this traffic (always free: 1 TB out and 10 million requests a month) |
| RDS db.t4g.small + 20 GB gp3 | $40 |
| RabbitMQ task (0.5 vCPU, 1 GB) | $22 |
| 9 small on-demand tasks (0.25 vCPU, 0.5 GB): catalogue, search, lyrics, waveform, playlist, recommendation, jam, sync, frontend | $101 |
| Upload API, Streaming, orchestrator (0.25–0.5 vCPU, 1 GB) | $58 |
| 4 small workers on Spot (catalogue, search, lyrics, upload-publisher) | $14 |
| Waveform worker (1 vCPU, 2 GB, Spot) | $14 |
| Public IPv4 addresses (18 tasks + the ALB's 2) | $73 |
| Secrets (~15), logs, ECR, S3 | $10 |
| **Total** | **≈ $350** (about $11.50 a day) |

That is about **$0.48 per hour while it is up**, billed by the hour or less,
and nothing between sessions because everything is destroyed (RUNBOOK.md §8).
A three-hour session costs about $1.50; bringing up only the stacks a session
needs (RUNBOOK.md §2.3) costs less. The brief's budget is
reimbursed only if it was requested in Week 7. A local Kubernetes cluster is
also an accepted production environment if the budget is not available.

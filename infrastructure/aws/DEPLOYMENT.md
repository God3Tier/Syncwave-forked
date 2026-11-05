# AWS deployment decision and checklist

Updated: 4 November 2026.

## Decision

Deploy the web UI and APIs as separate ECS Fargate services behind one public
entry point. Store images in ECR, audio in S3, service databases in RDS
Postgres, secrets in Secrets Manager, and use Cloud Map for private service
discovery. GitLab should authenticate with AWS through OIDC and update ECS task
definitions only after tests pass.

This preserves the local gateway contract: the browser uses `/` and
`/api/<service>`, while services call private names such as
`catalogue.syncwave.internal`.

## Current branch status

Do not deploy `feat/upload-integration` as production today. Its local stack is
healthy and its integration scenarios pass, but its Terraform is incomplete:

- Terraform roots exist only for Lyrics, Waveform, Playlist and Recommendation.
- Catalogue, Search, Upload/publisher, Streaming, Jam, Sync, frontend and the
  standalone request orchestrator have no service stack on this branch.
- The frontend has no catch-all production route here.
- The shared load balancer is HTTP-only on this branch; browser audio and
  WebSockets require HTTPS/WSS in production.
- Browser identity and internal tokens are development placeholders.
- The single RabbitMQ task has no durable volume or managed failover.

The newer `origin/dev` line contains broader AWS and HTTPS work. Merge or
rebase that work into the integration line, resolve it as code (do not copy
Terraform state), and repeat the full test matrix before applying anything.

## Deployment order

1. Run `terraform fmt -check -recursive` and `terraform validate` for every
   root. Review `terraform plan`; never apply a plan with unexplained deletes.
2. Apply `bootstrap/` to create the versioned, encrypted remote-state bucket.
3. Apply `platform/`: VPC, security groups, ECS cluster, ALB/CloudFront,
   Cloud Map, RDS, S3, RabbitMQ and the GitLab OIDC role.
4. Build immutable images once, scan them, push them to ECR by digest, and seed
   each service stack with that tested tag.
5. Apply service roots in dependency order: data-plane services first
   (Catalogue, Playlist, Sync), then workers and dependants, then Jam and the
   frontend catch-all route. Run migrations as one-shot ECS tasks before APIs.
6. Set protected GitLab variables from Terraform outputs: `AWS_ROLE_ARN`,
   `AWS_REGION`, `ECR_REGISTRY` and `ECS_CLUSTER`. Store no long-lived AWS key
   in GitLab.
7. Verify HTTPS, WSS, health endpoints and private DNS, then run the same smoke,
   ingestion, backend, recovery and Playwright tests against the public URL.
8. Record task-definition revisions and database migration versions. Roll back
   by restoring the previous task definition; use forward database migrations
   unless a tested down migration is explicitly safe.

Exact Terraform commands, diagnostics and teardown commands remain in
[RUNBOOK.md](RUNBOOK.md). Architecture ownership and estimated costs are in
[README.md](README.md).

## Production gates

Before a real release, all of these need evidence:

- HTTPS/WSS with certificate renewal and HTTP-to-HTTPS redirect.
- A real identity flow and authorization tests for every protected action.
- Durable RabbitMQ or a documented managed-broker choice, retry/DLQ alarms and
  recovery testing.
- RDS backups, migration rollback policy and per-service least-privilege roles.
- A supported Jam/Sync replica topology; in-memory socket ownership must not be
  scaled horizontally without affinity or shared session state.
- CloudWatch logs, metrics and alarms for failed processing, queue depth,
  unhealthy consumers, dependency timeouts and playback readiness failures.
- Tested ECS rollback plus successful staging artifacts for all scenario and
  browser tests.
- A cost budget/alarm and a teardown owner for temporary environments.

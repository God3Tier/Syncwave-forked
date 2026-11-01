# AWS runbook

Copy-paste commands for the AWS production environment. **Why** things are
set up this way is in [README.md](README.md).

The commands are for **Git Bash**, the same shell the CI scripts use, and run
from `infrastructure/aws/`. Each step says what you should see.

Contents:
[0 Every new terminal](#0-every-new-terminal) ·
[1 Prerequisites](#1-prerequisites) ·
[2 First-time setup](#2-first-time-setup) ·
[3 Smoke test](#3-smoke-test) ·
[4 End-to-end test](#4-end-to-end-test-lyrics-and-waveform) ·
[5 Deploy and roll back](#5-deploy-and-roll-back) ·
[6 Change configuration](#6-change-configuration) ·
[7 Debug](#7-debug) ·
[8 Pause and resume](#8-pause-between-demos-and-resume) ·
[9 Teardown](#9-teardown)

---

## 0. Every new terminal

```sh
cd infrastructure/aws                  # from the repo root
export MSYS_NO_PATHCONV=1              # Git Bash: stops /ecs/... arguments being turned into C:/Program Files/Git/ecs/...
export AWS_REGION=ap-southeast-1
export CLUSTER=syncwave
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
export GITLAB_IMAGES=registry.gitlab.com/cs302-2026/g4-team6/syncwave

# Once the platform exists (after step 2.2):
export ALB=$(terraform -chdir=platform output -raw base_url)
export BUCKET=$(terraform -chdir=platform output -raw audio_bucket_name)

# The image tag an ECS service is running now, e.g. `current_tag lyrics`
current_tag() {
  aws ecs describe-task-definition \
    --task-definition "$(aws ecs describe-services --cluster $CLUSTER --services "$1" --query 'services[0].taskDefinition' --output text)" \
    --query 'taskDefinition.containerDefinitions[0].image' --output text | sed 's/.*://'
}
```

You should see no errors. `echo $ACCOUNT_ID` prints your 12-digit account
ID. If it fails, sign in first (step 1).

In PowerShell, set variables as `$env:AWS_REGION = "ap-southeast-1"` and
continue lines with a backtick instead of `\`. Git Bash is simpler for
everything below.

---

## 1. Prerequisites

```sh
terraform version              # 1.16 or newer
aws --version                  # aws-cli/2.x
session-manager-plugin         # "The Session Manager plugin was installed successfully" (needed for ECS Exec)
docker buildx version
```

Sign in. Use whichever applies to your account:

```sh
aws login                                   # console credentials (AWS CLI 2.32+)
# or, for IAM Identity Center:
aws configure sso && aws sso login --profile <profile> && export AWS_PROFILE=<profile>

aws sts get-caller-identity                 # shows your account and identity
```

First-time setup creates IAM roles and an OIDC provider, so it needs an
administrator identity. Day-to-day commands need much less.

---

## 2. First-time setup

Run this once per AWS account, in this order.

### 2.1 State bucket (bootstrap)

```sh
terraform -chdir=bootstrap init
terraform -chdir=bootstrap apply                         # type "yes"
terraform -chdir=bootstrap output -raw backend_hcl > backend.hcl
cat backend.hcl
```

You should see `bucket = "syncwave-tfstate-<account id>"`, `use_lockfile = true`.
**Commit `backend.hcl`**: every root needs it, and it holds no secrets.
`bootstrap/terraform.tfstate` stays on your machine and is gitignored. If it
is lost, nothing breaks; see the comment at the top of `bootstrap/main.tf`.

### 2.2 Platform (shared; agree with the team first)

```sh
terraform -chdir=platform init -backend-config=../backend.hcl
terraform -chdir=platform plan -out=tfplan               # review: about 50 resources, no NAT gateway
terraform -chdir=platform apply tfplan                   # ~10 minutes, mostly RDS
```

If the apply fails with *"Provider with url https://gitlab.com already
exists"*, run it again with `-var create_gitlab_oidc_provider=false`.

Check that RabbitMQ is up and its queues were declared:

```sh
aws ecs describe-services --cluster $CLUSTER --services rabbitmq \
  --query 'services[0].{running:runningCount,desired:desiredCount}' --output table
aws logs tail /ecs/syncwave/rabbitmq --since 15m | grep "definitions loaded"
```

You should see `running 1, desired 1` and a `definitions loaded` line. The
line can take a minute or two after the task starts. Now run the two
`export ALB=…` / `export BUCKET=…` lines from step 0.

### 2.3 A service stack (repeat for each service)

```sh
SVC=lyrics          # then again with SVC=waveform
terraform -chdir=services/$SVC init -backend-config=../../backend.hcl
```

**a) Image repository and database first.** The tasks can't start without either.

```sh
terraform -chdir=services/$SVC apply -target=aws_ecr_repository.this -target=module.db
```

Terraform warns that `-target` is for exceptional use; this is one. Type `yes`.

**b) Create the service's database and login role.**

```sh
TASK=$(eval "$(terraform -chdir=services/$SVC output -raw db_init_command)")
echo $TASK
aws ecs wait tasks-stopped --cluster $CLUSTER --tasks $TASK
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK --query 'tasks[0].containers[0].exitCode'
aws logs tail /ecs/syncwave/$SVC-db-init --since 15m
```

You should see exit code `0`, and `database lyrics is ready` in the log. It
is safe to run again.

**c) Put a first image in ECR.** After this, CI keeps it up to date.

```sh
docker login registry.gitlab.com      # GitLab username + a personal access token with read_registry
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR
docker buildx imagetools create --tag $ECR/syncwave/$SVC:main $GITLAB_IMAGES/$SVC:dev
```

Use `$GITLAB_IMAGES/$SVC:main` instead of `:dev` once the service has been
merged to `main`. You should see the manifest being pushed. No rebuild
happens; this copies the image that CI already tested.

**d) Everything else** (ECS services, task roles, ALB route):

```sh
terraform -chdir=services/$SVC plan -out=tfplan          # review
terraform -chdir=services/$SVC apply tfplan
aws ecs wait services-stable --cluster $CLUSTER --services $SVC $SVC-worker
terraform -chdir=services/$SVC output api_url
```

`wait services-stable` returns silently when both services run their task.
If it times out after 10 minutes, go to [7 Debug](#7-debug).

### 2.4 Turn on CI deploys

```sh
terraform -chdir=platform output -raw gitlab_deploy_role_arn; echo
terraform -chdir=platform output -raw ecr_registry; echo
```

In GitLab, under Settings > CI/CD > Variables, add each of these as a
**protected** variable:

| Variable | Value |
|---|---|
| `AWS_ROLE_ARN` | first line above |
| `ECR_REGISTRY` | second line above |
| `AWS_REGION` | `ap-southeast-1` |
| `ECS_CLUSTER` | `syncwave` |

From now on, a merge to `main` that changes a service runs its `deploy` job,
which pushes the image and rolls the ECS services.

---

## 3. Smoke test

```sh
curl -s $ALB/api/lyrics/health; echo        # {"status":"ok"}
curl -s $ALB/api/waveform/health; echo      # {"status":"ok"}
curl -s $ALB/api/nope/x; echo               # {"error":{"code":"UNKNOWN_SERVICE",...}}

aws ecs describe-services --cluster $CLUSTER \
  --services lyrics lyrics-worker waveform waveform-worker rabbitmq \
  --query 'services[].{service:serviceName,running:runningCount,desired:desiredCount,rollout:deployments[0].rolloutState}' \
  --output table                            # running = desired, rollout COMPLETED

aws logs tail /ecs/syncwave/lyrics-worker --since 1h | grep consuming     # consuming lyrics.song-uploaded with prefetch 10
aws logs tail /ecs/syncwave/waveform-worker --since 1h | grep consuming   # consuming waveform.song-uploaded with prefetch 2
```

---

## 4. End-to-end test (lyrics and waveform)

This follows the same steps as "Try it without the Upload Service" in
`services/waveform/README.md`. The RabbitMQ management API isn't exposed in
AWS, so the event is published from inside a worker container.

**On your machine:** upload a song and its lyrics as the Upload Service
would. `example.mp3`/`example.lrc` are in the repo root; any `.mp3`/`.lrc`
works.

```sh
SONG_ID=$(python -c "import uuid; print(uuid.uuid4())"); echo $SONG_ID
aws s3 cp ../../example.mp3 s3://$BUCKET/audio/$SONG_ID.mp3
aws s3 cp ../../example.lrc s3://$BUCKET/lyrics/$SONG_ID.lrc

WORKER=$(aws ecs list-tasks --cluster $CLUSTER --service-name lyrics-worker --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster $CLUSTER --task $WORKER --container lyrics-worker --interactive --command sh
```

**In the container shell that opens:** paste the following, with your song
ID on the first line.

```sh
SONG_ID=<paste the id printed above>
python - "$SONG_ID" <<'PY'
import asyncio, json, os, sys, uuid
from datetime import datetime, timezone
import aio_pika

async def main(song_id):
    event_id = str(uuid.uuid4())
    event = {
        "event_id": event_id, "event_type": "SongUploaded", "version": 1, "song_id": song_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "producer": "upload", "correlation_id": event_id,
        "payload": {"audio_reference": f"audio/{song_id}.mp3", "lyrics_reference": f"lyrics/{song_id}.lrc",
                    "title": "Demo", "artist": "SyncWave Artist"},
    }
    connection = await aio_pika.connect(host=os.environ["AMQP_HOST"], port=int(os.environ["AMQP_PORT"]),
                                        login=os.environ["AMQP_USER"], password=os.environ["AMQP_PASSWORD"])
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        exchange = await channel.get_exchange("syncwave.events")
        message = aio_pika.Message(json.dumps(event).encode(), content_type="application/json",
                                   delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                                   message_id=event_id, type="SongUploaded")
        await exchange.publish(message, routing_key="song.uploaded")
    print("published SongUploaded", event_id, "for song", song_id)

asyncio.run(main(sys.argv[1]))
PY
exit
```

You should see `published SongUploaded <event id> for song <song id>`.

**Back on your machine**, after a few seconds (waveform takes longer than lyrics):

```sh
curl -s $ALB/api/lyrics/songs/$SONG_ID/lyrics | head -c 400; echo
curl -s "$ALB/api/waveform/songs/$SONG_ID/waveform?points=10"; echo
curl -s $ALB/api/waveform/songs/$SONG_ID/waveform/bands | head -c 200; echo
```

Lyrics come back with `"status": "READY"` and the timed `lines`; the waveform
comes back as 10 peaks. If you get another status or a 404 at first,
processing is still running. To watch it happen:

```sh
aws logs tail /ecs/syncwave/lyrics-worker --since 10m
aws logs tail /ecs/syncwave/waveform-worker --since 10m
```

`SongUploaded` is also routed to `catalogue.song-uploaded`, and the results
to `catalogue.processing-results`. Until Catalogue is deployed, those
messages pile up there, which is harmless. To clear them, see the RabbitMQ
commands in [7 Debug](#7-debug).

---

## 5. Deploy and roll back

**Normal path:** merge to `main`. The service's `deploy` job copies the image
to ECR, registers new task definition revisions, updates both ECS services,
and waits until they are stable.

**By hand** (for example before CI variables are set). Use the content tag
from the build job's log (`IMAGE_TAG=…`) or a branch tag such as `dev`.

```sh
SVC=lyrics; TAG=<tag>
docker buildx imagetools create --tag $ECR/syncwave/$SVC:$TAG $GITLAB_IMAGES/$SVC:$TAG
terraform -chdir=services/$SVC apply -var image_tag=$TAG            # registers revisions with that image
for s in $SVC $SVC-worker; do
  aws ecs update-service --cluster $CLUSTER --service $s --task-definition syncwave-$s \
    --query 'service.taskDefinition' --output text
done
aws ecs wait services-stable --cluster $CLUSTER --services $SVC $SVC-worker
```

`--task-definition syncwave-<name>` without a revision number means the
latest revision.

**Roll back** to an earlier revision:

```sh
aws ecs list-task-definitions --family-prefix syncwave-lyrics --sort DESC --max-items 5 \
  --query 'taskDefinitionArns' --output table
aws ecs update-service --cluster $CLUSTER --service lyrics --task-definition syncwave-lyrics:<revision>
aws ecs wait services-stable --cluster $CLUSTER --services lyrics
```

Do the same for `lyrics-worker` if it should go back too. A failing
deployment rolls back by itself (deployment circuit breaker); check the
service events in [7 Debug](#7-debug).

---

## 6. Change configuration

Environment variables, CPU/memory, secrets and task counts are Terraform
variables. Defaults are in `services/<svc>/variables.tf`; to override one,
use `-var` or a gitignored `services/<svc>/terraform.tfvars`.

Terraform registers a new task definition revision but does not roll it out:
the image is CI's job, and Terraform must not undo a deploy. Pass the image
that is running now, then roll out:

```sh
SVC=lyrics
TAG=$(current_tag $SVC); echo $TAG
terraform -chdir=services/$SVC apply -var image_tag=$TAG             # plus your -var changes
for s in $SVC $SVC-worker; do
  aws ecs update-service --cluster $CLUSTER --service $s --task-definition syncwave-$s --query 'service.taskDefinition' --output text
done
aws ecs wait services-stable --cluster $CLUSTER --services $SVC $SVC-worker
```

If you skip the `update-service` step, the change goes live with the next
CI deploy, because the deploy job builds on the latest revision.

Always pass `-var image_tag=$(current_tag <svc>)` when applying a service
stack that CI has already deployed. Otherwise the latest revision points at
the old `:main` seed image until the next deploy.

---

## 7. Debug

```sh
# What ECS last did with a service (failed placements, health check failures, rollbacks)
aws ecs describe-services --cluster $CLUSTER --services lyrics --query 'services[0].events[:8].message'

# Why the most recent task stopped
STOPPED=$(aws ecs list-tasks --cluster $CLUSTER --service-name lyrics --desired-status STOPPED --query 'taskArns[0]' --output text)
aws ecs describe-tasks --cluster $CLUSTER --tasks $STOPPED \
  --query 'tasks[0].{reason:stoppedReason,exit:containers[0].exitCode,detail:containers[0].reason}'

# Logs (Ctrl+C to stop following)
aws logs tail /ecs/syncwave/lyrics --follow
aws logs tail /ecs/syncwave/lyrics-worker --since 1h

# 502/503 from the ALB: are the API tasks healthy?
aws elbv2 describe-target-health \
  --target-group-arn $(aws elbv2 describe-target-groups --names syncwave-lyrics --query 'TargetGroups[0].TargetGroupArn' --output text) \
  --query 'TargetHealthDescriptions[].TargetHealth'

# A shell inside a running container
TASK=$(aws ecs list-tasks --cluster $CLUSTER --service-name lyrics --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster $CLUSTER --task $TASK --container lyrics --interactive --command sh

# Restart a service (new tasks, same revision)
aws ecs update-service --cluster $CLUSTER --service lyrics-worker --force-new-deployment --query 'service.serviceName'
```

**RabbitMQ:** check queue depth and consumers, inspect the DLQs, clear a queue:

```sh
RABBIT=$(aws ecs list-tasks --cluster $CLUSTER --service-name rabbitmq --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster $CLUSTER --task $RABBIT --container rabbitmq --interactive \
  --command "rabbitmqctl list_queues name messages consumers"
aws ecs execute-command --cluster $CLUSTER --task $RABBIT --container rabbitmq --interactive \
  --command "rabbitmqctl purge_queue catalogue.song-uploaded"
```

Every worker queue should show `consumers 1`. Messages in
`*.song-uploaded.dlq` failed permanently; the worker log says why.

| Symptom | Likely cause / fix |
|---|---|
| Task stops with `CannotPullContainerError` | The image tag isn't in ECR. Redo step 2.3c, or deploy a tag that exists (§5). |
| `ResourceInitializationError: unable to pull secrets` | The secret is missing or not readable. Check that `syncwave/<svc>/db` exists and the platform was applied (execution role policy). |
| API logs `password authentication failed` or `database "lyrics" does not exist` | The db-init task didn't run or failed: rerun step 2.3b. |
| Worker logs `RabbitMQ is not reachable` | The `rabbitmq` service is down or restarting. Check its events and logs. |
| A worker shows `consumers 0` after RabbitMQ restarted | The worker reconnected before the queues were re-declared. `--force-new-deployment` on the worker. |
| Waveform worker logs `DECODE_TIMEOUT` | The song is too long for the CPU. Raise `worker_cpu` (§6). |
| `execute-command` fails with `TargetNotConnectedException` | The task was started before ECS Exec was enabled. Restart it with `--force-new-deployment`. |

---

## 8. Pause between demos, and resume

This takes the bill from about $4/day to about $1/day: the ALB, public IPs
and storage keep running.

**Pause:**

```sh
for s in lyrics lyrics-worker waveform waveform-worker rabbitmq; do
  aws ecs update-service --cluster $CLUSTER --service $s --desired-count 0 --query 'service.serviceName' --output text
done
aws rds stop-db-instance --db-instance-identifier syncwave --query 'DBInstance.DBInstanceStatus'
```

**Resume:**

```sh
aws rds start-db-instance --db-instance-identifier syncwave --query 'DBInstance.DBInstanceStatus'
aws rds wait db-instance-available --db-instance-identifier syncwave       # ~5 minutes
aws ecs update-service --cluster $CLUSTER --service rabbitmq --desired-count 1 --query 'service.serviceName'
for s in lyrics lyrics-worker waveform waveform-worker; do
  aws ecs update-service --cluster $CLUSTER --service $s --desired-count 1 --query 'service.serviceName' --output text
done
```

Then run the smoke test (§3).

- AWS **restarts a stopped RDS instance after 7 days**. Stop it again if the break is longer.
- A `terraform apply` of a stack also resets its desired counts to the variables (default 1).
- Start RDS before applying `platform/`: Terraform can't modify a stopped instance.

---

## 9. Teardown

Destroy the service stacks before the platform, because they depend on its
outputs. ECR repositories and the audio bucket refuse to be deleted while they
hold images or objects. Turning on force-delete is a separate apply, because
Terraform's destroy reads the setting from state.

```sh
for SVC in waveform lyrics; do
  terraform -chdir=services/$SVC apply -target=aws_ecr_repository.this -var ecr_force_delete=true
  terraform -chdir=services/$SVC destroy -var ecr_force_delete=true
done

terraform -chdir=platform apply -target=aws_s3_bucket.audio -var audio_bucket_force_destroy=true
terraform -chdir=platform destroy -var audio_bucket_force_destroy=true      # ~10 minutes
```

If you set `db_deletion_protection = true`, apply it as `false` first.

- Task definition revisions are left behind as ACTIVE (`skip_destroy`). They cost nothing.
- Leave the bootstrap state bucket. It costs cents, and it's needed to rebuild.
- To remove the bootstrap bucket as well: empty every object version in the S3 console, delete the `prevent_destroy` block in `bootstrap/main.tf`, then run `terraform -chdir=bootstrap destroy`.

Also delete the GitLab CI variable `AWS_ROLE_ARN`, so that `main` pipelines
stop trying to deploy.

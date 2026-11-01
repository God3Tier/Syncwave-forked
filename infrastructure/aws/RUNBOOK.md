# AWS runbook

Copy-paste commands for the AWS production environment. **Why** things are
set up this way is in [README.md](README.md).

The commands are for **Git Bash**, the same shell the CI scripts use. Start
every step in the **repo root** (`syncwave/`). Steps that use Terraform begin
with `cd infrastructure/aws` and end with `cd -`, which takes you back to the
repo root; the other steps work from any directory. Each step says what you
should see.

**Nothing stays up between sessions.** A session starts with an empty account,
brings everything up (§2, about 25 minutes), and ends by destroying all of it,
the state bucket included (§8). Nothing is billed in between.

Each section sets the shell variables it uses, so you can start any section in
a new terminal. Commands that pass a `/ecs/...` log group start with
`MSYS_NO_PATHCONV=1`; without it, Git Bash turns the name into
`C:/Program Files/Git/ecs/...`. In PowerShell, write variables as
`$SVC = "lyrics"`, continue lines with a backtick instead of `\`, and leave out
`MSYS_NO_PATHCONV=1`.

Contents:
[1 Prerequisites](#1-prerequisites) ·
[2 Bring it up](#2-bring-it-up-every-session) ·
[3 Smoke test](#3-smoke-test) ·
[4 End-to-end test](#4-end-to-end-test) ·
[5 Deploy and roll back](#5-deploy-and-roll-back) ·
[6 Change configuration](#6-change-configuration) ·
[7 Debug](#7-debug) ·
[8 Tear it down](#8-tear-it-down-end-of-every-session)

---

## 1. Prerequisites

```sh
terraform version              # 1.16 or newer
aws --version                  # aws-cli/2.x
session-manager-plugin         # "The Session Manager plugin was installed successfully" (needed for ECS Exec)
docker buildx version
```

### Sign in with an IAM user access key (once per machine)

The CLI and Terraform sign in with a long-lived access key of your existing
IAM user. You need its access key ID and secret access key. If you don't have
them, create a key in IAM > Users > *your user* > Security credentials >
Create access key (use case "Command Line Interface (CLI)"); the secret is
shown only once.

Save the key as your default profile (stored in `~/.aws/credentials`):

```sh
aws configure
#   AWS Access Key ID:     AKIA...
#   AWS Secret Access Key: <secret>
#   Default region name:   ap-southeast-1
#   Default output format: json

aws sts get-caller-identity                 # "Arn": "arn:aws:iam::<account>:user/<your user>"
```

Every later `aws` and `terraform` command uses this profile and its region,
in any new terminal. If your default profile is already used for another
account, run `aws configure --profile syncwave` instead and add
`export AWS_PROFILE=syncwave` to `~/.bashrc`.

**Keep the key safe.** It works until someone deletes it, from anywhere.
- Never put it in the repo, a `.tfvars` file, a Dockerfile or a GitLab
  variable. GitLab deploys use OIDC and need no key (README.md).
- One user and key per person; don't share a key over chat.
- Rotate it: create a second key, `aws configure` with the new one, check
  `aws sts get-caller-identity`, then deactivate and delete the old key in
  the console.
- If it leaks, **deactivate it immediately** (IAM > Users > Security
  credentials), then check CloudTrail for activity you don't recognise.

### Log in to the GitLab container registry (once per machine)

Each session copies CI's images from GitLab's registry into ECR (step 2.3c).
The project is private, so Docker needs a token that can pull from its
registry; anonymous pulls get `403 Forbidden`. You only need to **read**.

**Open the token page:** in GitLab, select your avatar (top right) >
**Edit profile** > in the left sidebar, **Access** > **Personal access
tokens**. The **Generate token** dropdown offers two kinds of token. Use the
fine-grained one if you can; it can only pull this project's images.

**Option A: fine-grained token (recommended)**

1. **Generate token** > **Fine-grained token**.
2. **Name**: `syncwave-registry`. **Description** (optional): `Pull SyncWave
   images for the AWS runbook`.
3. **Expiration date**: the end of the project or semester (at most 365
   days; GitLab picks 365 days if left empty).
4. Under **Group and project access**, select **Only specific groups or
   projects I have access to**, then **Add group or project** >
   `cs302-2026/g4-team6/syncwave`. Add the project, not the `g4-team6`
   group: a group includes all its subgroups and projects.
5. Under **Add resource permissions**, keep the **Group and project** tab.
   Type `container` in **Search for resources to add** (it is under
   **Packages and Registry**) and tick **Container Repository**. Tick nothing
   else, and leave the **User** and **Global** tabs empty.
6. In the right panel, under **Group and project**, set the permission for
   Container Repository to **Read**.
7. **Generate token**, then copy the token. It is shown only once.

**Option B: legacy token** (if fine-grained tokens aren't offered, or the
group blocks them)

1. **Generate token** > **Legacy token**.
2. **Token name**: `syncwave-registry`. **Expiration date**: as above.
3. Scopes: tick only **`read_registry`**. A legacy token reaches every
   project you can see, so give it nothing more.
4. **Generate token**, then copy the token. It is shown only once.

**Log in** with your GitLab username and the token as the password. Pasting
through stdin keeps the token out of your shell history:

```sh
read -rsp "GitLab token: " GL_TOKEN; echo
echo "$GL_TOKEN" | docker login registry.gitlab.com --username <your gitlab username> --password-stdin
unset GL_TOKEN
```

You should see `Login Succeeded`. Check that the token can pull the images:

```sh
docker buildx imagetools inspect registry.gitlab.com/cs302-2026/g4-team6/syncwave/lyrics:dev | head -n 3
```

You should see `Name:`, `MediaType:` and `Digest:` lines. `403 Forbidden` or
`denied` means the token lacks the permission or the project.

Docker remembers the login, so you only repeat this when the token expires
or you change machines. Same rules as the AWS key: never commit or share the
token. If it leaks, revoke it on the same Personal access tokens page.

---

## 2. Bring it up (every session)

Run this at the start of every session, in this order. The `init` commands
are only needed the first time on a machine, but are harmless to repeat.

### 2.1 State bucket (bootstrap)

```sh
cd infrastructure/aws                  # from the repo root
terraform -chdir=bootstrap init
terraform -chdir=bootstrap apply                         # type "yes"
terraform -chdir=bootstrap output -raw backend_hcl > backend.hcl
cat backend.hcl
cd -
```

You should see `bucket = "syncwave-tfstate-<account id>"`, `use_lockfile = true`.
Every other stack's `init` reads `backend.hcl`. It is gitignored (it holds
the account ID) and comes out the same every session.
`bootstrap/terraform.tfstate` also stays on your machine.

To work on a stack from another machine during the session, write the file
from your own credentials instead of running bootstrap:

```sh
cd infrastructure/aws                  # from the repo root
printf 'bucket       = "syncwave-tfstate-%s"\nregion       = "ap-southeast-1"\nuse_lockfile = true\nencrypt      = true\n' \
  "$(aws sts get-caller-identity --query Account --output text)" > backend.hcl
cd -
```

### 2.2 Platform (shared; agree with the team first)

```sh
cd infrastructure/aws                  # from the repo root
terraform -chdir=platform init -backend-config=../backend.hcl
terraform -chdir=platform apply                          # about 50 to add; type "yes". ~10 minutes, mostly RDS
cd -
```

If the apply fails with *"Provider with url https://gitlab.com already
exists"*, run it again with `-var create_gitlab_oidc_provider=false`.

Check that RabbitMQ is up and its queues were declared:

```sh
aws ecs describe-services --cluster syncwave --services rabbitmq \
  --query 'services[0].{running:runningCount,desired:desiredCount}' --output table
MSYS_NO_PATHCONV=1 aws logs tail /ecs/syncwave/rabbitmq --since 15m | grep "definitions loaded"
```

You should see `running 1, desired 1` and a `definitions loaded` line. The
line can take a minute or two after the task starts.

### 2.3 Service stacks

`SERVICES` lists the service stacks to bring up: folder names under
`services/`, separated by spaces. Each step below runs for every service in
it, in turn, so run them in the same terminal.

- **Adding your service:** once its stack is in `services/<name>/` (see
  "Adding another service's stack" in README.md), add `<name>` here and in
  the same list in §8.
- **Bringing up only some:** set `SERVICES` to just those for this session.

```sh
# In apply order (see below). Add new services here (and in §8).
SERVICES="catalogue search upload audio_transmitter lyrics waveform playlist recommendation sync jam song_request_orchestrator frontend"
# The ones with a database (audio_transmitter, recommendation and frontend have none)
DB_SERVICES="catalogue search upload lyrics waveform playlist sync jam song_request_orchestrator"

cd infrastructure/aws                  # from the repo root
for SVC in $SERVICES; do
  terraform -chdir=services/$SVC init -backend-config=../../backend.hcl
done
cd -
```

`DB_SERVICES` is the part of `SERVICES` whose stack has a `module.db`; steps
a) and b) use it. The names are the folders under `services/`, which are also
the image names. Two folders run an ECS service with another name:
`audio_transmitter` runs `streaming`, and `song_request_orchestrator` runs
`orchestrator`.

**Why this order.** Some stacks read other stacks' outputs (a gRPC address and
the token to send), so the stack being called goes first:

| Stack | Reads the outputs of | If that stack isn't up |
|---|---|---|
| sync | catalogue | Sync uses its built-in fake catalogue (every song READY) |
| jam | sync, playlist | Jam uses its built-in fake for the missing one |

The others only call services by their private DNS name
(`catalogue.syncwave.internal`, `streaming.syncwave.internal`, ...), which
works in any order once everything is up. The frontend goes last because its
`/*` rule only makes sense once the `/api` routes exist.

**a) Image repositories and databases first.** The tasks can't start without either.

```sh
cd infrastructure/aws                  # from the repo root
for SVC in $SERVICES; do
  terraform -chdir=services/$SVC apply -target=aws_ecr_repository.this
done
for SVC in $DB_SERVICES; do
  terraform -chdir=services/$SVC apply -target=module.db
done
cd -
```

Terraform warns that `-target` is for exceptional use; this is one. Type
`yes` once for each apply.

**b) Create each service's database and login role.**

```sh
cd infrastructure/aws                  # from the repo root
for SVC in $DB_SERVICES; do
  CMD=$(terraform -chdir=services/$SVC output -raw db_init_command 2>/dev/null)
  if [ -z "$CMD" ]; then
    echo "$SVC: no db_init_command output; rerun step a for it (terraform -chdir=services/$SVC apply -target=module.db)"
    continue
  fi
  TASK=$(eval "$CMD")
  aws ecs wait tasks-stopped --cluster syncwave --tasks $TASK
  echo "$SVC db-init exit code: $(aws ecs describe-tasks --cluster syncwave --tasks $TASK \
    --query 'tasks[0].containers[0].exitCode' --output text)"
  # Named after the database, which isn't always the folder (song_request_orchestrator -> orchestrator)
  MSYS_NO_PATHCONV=1 aws logs tail "$(terraform -chdir=services/$SVC output -raw db_init_log_group)" --since 15m
done
cd -
```

For each service you should see exit code `0` and `database <service> is
ready` in the log. It is safe to run again.

A service that prints `no db_init_command output` has its database resources
but no saved outputs: its `-target=module.db` apply in step a stopped before
finishing. Run that apply again (with nothing left to create, it just saves the
outputs), then run this step again.

**c) Put a first image in ECR.** The repositories are new every session, so
they start empty. This needs the GitLab registry login from §1.

```sh
cd infrastructure/aws                  # from the repo root
ECR=$(terraform -chdir=platform output -raw ecr_registry)
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR   # valid 12 hours
for SVC in $SERVICES; do
  docker buildx imagetools create --tag $ECR/syncwave/$SVC:main \
    registry.gitlab.com/cs302-2026/g4-team6/syncwave/$SVC:dev
done
cd -
```

Use the `:main` image instead of `:dev` once a service has been merged to
`main`. You should see each manifest being pushed. No rebuild happens; this
copies the images that CI already tested. A `not found` error means CI has
not built that image on `dev` yet (`audio_transmitter` and
`song_request_orchestrator` got their build jobs late); leave that service out
of `SERVICES` for this session.

**d) Everything else** (ECS services, task roles, ALB routes):

```sh
cd infrastructure/aws                  # from the repo root
for SVC in $SERVICES; do
  terraform -chdir=services/$SVC apply                   # type "yes" for each
done
for SVC in $SERVICES; do
  # ecs_services lists the stack's ECS services, e.g. ["lyrics","lyrics-worker"]
  aws ecs wait services-stable --cluster syncwave \
    --services $(terraform -chdir=services/$SVC output -json ecs_services | tr '[]",' '    ')
  terraform -chdir=services/$SVC output -raw api_url; echo
done
cd -
```

`wait services-stable` returns silently once a stack's ECS services all run
their tasks, and the loop then prints that service's API URL. If it times out
after 10 minutes, go to [7 Debug](#7-debug).

**Open the app.** Everything is behind the load balancer's address, which the
platform stack prints:

```sh
terraform -chdir=infrastructure/aws/platform output -raw base_url; echo   # from the repo root
```

Open that URL (`http://syncwave-<id>.ap-southeast-1.elb.amazonaws.com`) in a
browser for the web UI once the frontend stack is up; the APIs are at
`<base_url>/api/<service>/...`. Each service stack prints its own address too
(`terraform -chdir=infrastructure/aws/services/<folder> output -raw api_url`).
It is plain `http://` because the platform has no TLS certificate, so the
browser may say the site is not secure. The address changes every session,
because the load balancer is recreated.

**Leaving a service out.** Services call each other by private DNS name, and
a name exists only while that service's stack is up. If you bring up only
some stacks, apply the callers with their fallbacks instead of step d) as
written:

| Left out | Apply this instead | Effect |
|---|---|---|
| catalogue | `terraform -chdir=services/playlist apply -var catalogue_mode=off` | Playlist accepts any song id |
| catalogue | `terraform -chdir=services/recommendation apply -var catalogue_mode=stub` | Recommendation ranks its built-in demo songs |
| audio_transmitter | `terraform -chdir=services/sync apply -var streaming_enabled=false` | Sync uses its built-in fake Streaming Service |
| catalogue, sync or playlist | nothing | Sync and Jam notice from the missing state and use their fakes |

Search, Streaming and the orchestrator have no fallback: their calls to a
missing service fail (Search's startup rebuild only logs the error). Each
`-var` changes only an environment variable, so it is a new task definition
revision: it goes live with the next CI deploy, or immediately with
[6 Change configuration](#6-change-configuration). To use the real service
again, bring its stack up and apply the caller again **without** the `-var`.

### 2.4 CI deploys during the session (optional)

Only needed if merges to `main` during this session should deploy here.

```sh
cd infrastructure/aws                  # from the repo root
terraform -chdir=platform output -raw gitlab_deploy_role_arn; echo
terraform -chdir=platform output -raw ecr_registry; echo
cd -
```

In GitLab, under Settings > CI/CD > Variables, add each of these as a
**protected** variable:

| Variable | Value |
|---|---|
| `AWS_ROLE_ARN` | first line above |
| `ECR_REGISTRY` | second line above |
| `AWS_REGION` | `ap-southeast-1` |
| `ECS_CLUSTER` | `syncwave` |

The values are the same every session, so the last three can stay set.
`AWS_ROLE_ARN` is what turns the `deploy` jobs on: delete it at teardown
(§8), or deploy jobs on `main` fail while nothing is up.

---

## 3. Smoke test

```sh
cd infrastructure/aws                  # from the repo root
ALB=$(terraform -chdir=platform output -raw base_url)
for P in catalogue search upload streaming lyrics waveform playlist recommendation jam sync orchestrator; do
  printf '%-15s %s\n' $P "$(curl -s $ALB/api/$P/health)"     # {"status":"ok"} (the orchestrator says OK)
done
curl -s $ALB/ | grep -o '<title>.*</title>'                # the frontend's index.html
curl -s $ALB/api/nope/x; echo                              # {"error":{"code":"UNKNOWN_SERVICE",...}}
curl -s $ALB/api/sync/internal/v1/sessions/x; echo         # 404: Sync's internal routes are not public

aws ecs describe-services --cluster syncwave \
  --services catalogue catalogue-worker search search-worker upload upload-publisher streaming \
             lyrics lyrics-worker waveform waveform-worker playlist recommendation \
  --query 'services[].{service:serviceName,running:runningCount,desired:desiredCount,rollout:deployments[0].rolloutState}' \
  --output table                            # running = desired, rollout COMPLETED
aws ecs describe-services --cluster syncwave --services sync jam orchestrator frontend rabbitmq \
  --query 'services[].{service:serviceName,running:runningCount,desired:desiredCount,rollout:deployments[0].rolloutState}' \
  --output table                            # (describe-services takes at most 10 names)

for W in catalogue-worker search-worker lyrics-worker waveform-worker; do
  MSYS_NO_PATHCONV=1 aws logs tail /ecs/syncwave/$W --since 1h | grep consuming   # consuming <queue> with prefetch N
done
cd -
```

A service that isn't in this session's `SERVICES` returns the
`UNKNOWN_SERVICE` 404 and shows up as `MISSING` in the tables.

---

## 4. End-to-end test

`tests/integration/upload-flow.py` is the test CI runs on `staging`. Pointed
at the ALB, it uploads a generated song with lyrics through
`/api/upload/uploads`, waits until the Catalogue reports it `READY` (so
RabbitMQ and the Lyrics, Waveform and Catalogue workers all did their part),
checks the timed lyrics and the waveform, and streams the audio back through
`/api/streaming`. It needs only Python's standard library.

```sh
cd infrastructure/aws                  # from the repo root
ALB=$(terraform -chdir=platform output -raw base_url)
python ../../tests/integration/upload-flow.py --base-url $ALB
cd -
```

You should see a `PASS` line per step, then a JSON report with
`"result": "PASS"`, the `song_id` and the `title` (`upload-flow-<run id>`).
If it stops with `FAIL`, the message names the step that timed out; the logs
of the worker behind it say why (`MSYS_NO_PATHCONV=1 aws logs tail /ecs/syncwave/lyrics-worker`,
`waveform-worker`, `catalogue-worker` or `upload-publisher`; see [7 Debug](#7-debug)).
Search indexes the song once the Catalogue publishes `SongReady`:

```sh
SONG_ID=<the song_id from the report>
curl -s "$ALB/api/search/search?q=upload-flow" | head -c 300; echo        # the song is listed
```

Then the song request orchestrator, which returns audio, lyrics and waveform
together for a playlist. Put the song in a playlist first:

```sh
OWNER=$(python -c "import uuid; print(uuid.uuid4())")
PLAYLIST_ID=$(curl -s -X POST $ALB/api/playlist/playlists -H 'Content-Type: application/json' \
  -d "{\"owner_id\":\"$OWNER\",\"name\":\"e2e\"}" | python -c "import json,sys; print(json.load(sys.stdin)['playlist_id'])")
curl -s -X POST $ALB/api/playlist/playlists/$PLAYLIST_ID/songs -H 'Content-Type: application/json' \
  -d "{\"song_id\":\"$SONG_ID\"}" > /dev/null
curl -s -X POST $ALB/api/orchestrator/playlists/$PLAYLIST_ID/play -H "X-Client-ID: $OWNER" | head -c 300; echo
```

The last command returns JSON for the first song with its lyrics, waveform
points and a base64 audio chunk. Then open `$ALB/` in a browser to try the
three scenarios in the UI (upload, play with lyrics, a Jam in two windows).

---

## 5. Deploy and roll back

**Normal path:** merge to `main`. The service's `deploy` job copies the image
to ECR, registers new task definition revisions, updates both ECS services,
and waits until they are stable.

**By hand** (for example before CI variables are set). Use the content tag
from the build job's log (`IMAGE_TAG=…`) or a branch tag such as `dev`.
You need the GitLab registry login from §1 and the ECR login from step 2.3c
(log in to ECR again if it has been more than 12 hours).

```sh
cd infrastructure/aws                  # from the repo root
SVC=lyrics; TAG=<tag>                  # SVC is the folder under services/
ECR=$(terraform -chdir=platform output -raw ecr_registry)
docker buildx imagetools create --tag $ECR/syncwave/$SVC:$TAG \
  registry.gitlab.com/cs302-2026/g4-team6/syncwave/$SVC:$TAG
terraform -chdir=services/$SVC apply -var image_tag=$TAG            # registers revisions with that image
ECS=$(terraform -chdir=services/$SVC output -json ecs_services | tr '[]",' '    ')   # e.g. lyrics lyrics-worker
for s in $ECS; do
  aws ecs update-service --cluster syncwave --service $s --task-definition syncwave-$s \
    --query 'service.taskDefinition' --output text
done
aws ecs wait services-stable --cluster syncwave --services $ECS
cd -
```

`--task-definition syncwave-<name>` without a revision number means the
latest revision. The ECS service names come from the stack because they
don't always match the folder: `audio_transmitter` runs `streaming`,
`song_request_orchestrator` runs `orchestrator`, `upload` runs `upload` and
`upload-publisher`.

**Roll back** to an earlier revision:

```sh
aws ecs list-task-definitions --family-prefix syncwave-lyrics --sort DESC --max-items 5 \
  --query 'taskDefinitionArns' --output table
aws ecs update-service --cluster syncwave --service lyrics --task-definition syncwave-lyrics:<revision>
aws ecs wait services-stable --cluster syncwave --services lyrics
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
cd infrastructure/aws                  # from the repo root
SVC=lyrics                             # the folder under services/
ECS=$(terraform -chdir=services/$SVC output -json ecs_services | tr '[]",' '    ')   # e.g. lyrics lyrics-worker
# The image tag the stack's first ECS service is running now
TAG=$(aws ecs describe-task-definition --query 'taskDefinition.containerDefinitions[0].image' --output text \
  --task-definition "$(aws ecs describe-services --cluster syncwave --services $(echo $ECS | cut -d' ' -f1) --query 'services[0].taskDefinition' --output text)" \
  | sed 's/.*://'); echo $TAG
terraform -chdir=services/$SVC apply -var image_tag=$TAG             # plus your -var changes
for s in $ECS; do
  aws ecs update-service --cluster syncwave --service $s --task-definition syncwave-$s --query 'service.taskDefinition' --output text
done
aws ecs wait services-stable --cluster syncwave --services $ECS
cd -
```

If you skip the `update-service` step, the change goes live with the next
CI deploy, because the deploy job builds on the latest revision.

Always pass `-var image_tag=$TAG`, with `TAG` from the lines above, when
applying a service stack that CI has already deployed. Otherwise the latest
revision points at the old `:main` seed image until the next deploy.

---

## 7. Debug

```sh
# What ECS last did with a service (failed placements, health check failures, rollbacks)
aws ecs describe-services --cluster syncwave --services lyrics --query 'services[0].events[:8].message'

# Why the most recent task stopped
STOPPED=$(aws ecs list-tasks --cluster syncwave --service-name lyrics --desired-status STOPPED --query 'taskArns[0]' --output text)
aws ecs describe-tasks --cluster syncwave --tasks $STOPPED \
  --query 'tasks[0].{reason:stoppedReason,exit:containers[0].exitCode,detail:containers[0].reason}'

# Logs (Ctrl+C to stop following)
MSYS_NO_PATHCONV=1 aws logs tail /ecs/syncwave/lyrics --follow
MSYS_NO_PATHCONV=1 aws logs tail /ecs/syncwave/lyrics-worker --since 1h

# 502/503 from the ALB: are the API tasks healthy?
aws elbv2 describe-target-health \
  --target-group-arn $(aws elbv2 describe-target-groups --names syncwave-lyrics --query 'TargetGroups[0].TargetGroupArn' --output text) \
  --query 'TargetHealthDescriptions[].TargetHealth'

# A shell inside a running container
TASK=$(aws ecs list-tasks --cluster syncwave --service-name lyrics --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster syncwave --task $TASK --container lyrics --interactive --command sh

# Restart a service (new tasks, same revision)
aws ecs update-service --cluster syncwave --service lyrics-worker --force-new-deployment --query 'service.serviceName'
```

**RabbitMQ:** check queue depth and consumers, inspect the DLQs, clear a queue:

```sh
RABBIT=$(aws ecs list-tasks --cluster syncwave --service-name rabbitmq --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster syncwave --task $RABBIT --container rabbitmq --interactive \
  --command "rabbitmqctl list_queues name messages consumers"
aws ecs execute-command --cluster syncwave --task $RABBIT --container rabbitmq --interactive \
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
| `aws logs tail` says the log group `C:/Program Files/Git/ecs/...` doesn't exist | You left out `MSYS_NO_PATHCONV=1` in Git Bash. |
| Jam plays without Sync, or can't load a playlist | `terraform -chdir=services/jam output dependencies` says `fake` for it: the Sync or Playlist stack wasn't up when Jam was applied. Apply Jam again, then roll it out (§6). Same for Sync and the Catalogue: `terraform -chdir=services/sync output catalogue_mode`. |
| Every Jam or Sync WebSocket drops at once | Expected when `jam` or `sync` restarts or deploys: each runs as exactly one task and keeps its state in memory. The browser reconnects. |
| Playlist, Recommendation, Search or Streaming log connection errors to `catalogue.syncwave.internal` | The Catalogue stack isn't up. Bring it up, or use the fallbacks in §2.3 ("Leaving a service out"). |
| The orchestrator returns 502 for a playlist | One of the services it calls (`playlist`, `streaming`, `lyrics`, `waveform`) isn't up, or the song isn't processed yet. Its log names the failing call. |
| `/api/<service>/...` returns the frontend's HTML | The platform's `/api/*` 404 rule (priority 900) is missing: apply `platform/` again. |

---

## 8. Tear it down (end of every session)

Destroy in this order: the services in reverse apply order (a stack that
reads another's outputs goes first), then the platform, whose outputs they
all read, then the bootstrap bucket, which holds every stack's state. The ECR
repositories, the audio bucket and the state bucket are deleted together with
their contents.

```sh
# The same list as §2.3, in apply order; the loop runs it backwards
SERVICES="catalogue search upload audio_transmitter lyrics waveform playlist recommendation sync jam song_request_orchestrator frontend"

cd infrastructure/aws                  # from the repo root
for SVC in $(echo $SERVICES | tr ' ' '\n' | tac); do
  terraform -chdir=services/$SVC destroy                 # type "yes" for each
done
terraform -chdir=platform destroy                        # ~10 minutes, mostly RDS
terraform -chdir=bootstrap destroy                       # last
cd -
```

Each one should end with `Destroy complete!`. If a destroy fails, fix the
error and run it again before moving on. **Never destroy bootstrap while
another stack still has resources**: their state is deleted with the bucket,
Terraform loses track of them, and they keep being billed until deleted by
hand.

Check that nothing is left:

```sh
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=syncwave \
  --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n' | grep -v ':task-definition/'
```

You should see no output. Task definition revisions are hidden by the
`grep`: they stay behind on purpose (`skip_destroy`) and cost nothing. A
resource deleted in the last few minutes can still be listed; run it again
later before deleting anything by hand.

If you set `AWS_ROLE_ARN` in GitLab (§2.4), delete it now, so that `main`
pipelines stop trying to deploy.

If you no longer need AWS access at all, deactivate your access key (IAM >
Users > Security credentials) and remove its profile from `~/.aws/credentials`.

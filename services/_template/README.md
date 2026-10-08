# <Name> Service

**Owner:** <name> · **Language/framework:** <e.g. Java 21 / Spring Boot>

<One or two sentences: what this service is responsible for, from plan.md §3.>

## Interfaces

| Kind                 | Contract                                    | Notes |
|----------------------|---------------------------------------------|-------|
| REST                 | `contracts/api/<name>.openapi.yaml`         | via gateway at `/api/<name>/...` |
| Events published     | e.g. `LyricsProcessed` (`lyrics.processed`) | `contracts/events/` |
| Events consumed      | e.g. queue `lyrics.song-uploaded`           | |
| gRPC                 | e.g. `syncwave.catalogue.v1.CatalogueService` | `contracts/grpc/` |

## Data owned

<Tables/buckets/objects this service owns, see plan.md §11.>

## Configuration

See `.env.example` for every variable. Locally, Compose sets them
(`compose.yaml`); in production they come from the ECS task definition.

## Run

```sh
# whole stack (from the repo root)
docker compose up -d --build

# just this service, after editing it
docker compose up -d --build <name>
curl http://localhost:8080/api/<name>/health
```

## Failure handling

<What happens when a dependency, the queue or an external API fails, and
what this service deliberately does not handle. You will be asked this in
the Q&A.>

---

## Using this template (delete this section afterwards)

1. Copy this folder to `services/<name>/` (lowercase, matching the root
   `.gitlab-ci.yml` job name) and commit from **your own account**.
2. Replace `template` with `<name>` in `compose.yaml`, `.gitlab-ci.yml`
   and `.env.example`.
3. Replace the `Dockerfile` with your service's build (keep the conventions
   in its header).
4. Add `- services/<name>/compose.yaml` to `include:` in the root
   `docker-compose.yml`.
5. Check that `CONTRACT_PATHS` and the `changes:` list for your trigger job
   in the root `.gitlab-ci.yml` match the contracts your image uses.
6. `docker compose up -d --build`, then
   `curl http://localhost:8080/api/<name>/health` should return 200.

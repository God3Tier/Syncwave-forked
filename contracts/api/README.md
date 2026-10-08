# REST API contracts

One OpenAPI 3.1 file per service, written by its owner **before** the
implementation, so that consumers and the frontend can build against it:

```text
contracts/api/<service>.openapi.yaml      e.g. lyrics.openapi.yaml
```

CI (`contracts:schemas` in the root pipeline) lints every
`*.openapi.yaml` here with Redocly whenever this folder changes. To run the
same check locally (needs Node.js):

```sh
npx @redocly/cli@2 lint contracts/api/*.openapi.yaml
```

## Conventions

- `servers` and `paths` are the service's **own** paths, without the
  `/api/<service>` prefix. The browser calls
  `http://localhost:8080/api/lyrics/songs/{song_id}/lyrics`, and the
  gateway forwards `/songs/{song_id}/lyrics` to the Lyrics Service.
- Every service documents `GET /health`.
- Use the shared ID formats, field naming, error shape and timestamp
  rules from [`../README.md`](../README.md).
- Lists that can grow take `?limit=` (default 20, max 100) and return
  `{"items": [...], "next_cursor": "..." | null}`.

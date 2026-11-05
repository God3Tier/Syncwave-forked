# Recommendation Service

**Owner:** Hayyun · **Language/framework:** Python 3.12 / FastAPI, httpx

Recommends songs for the Discover & Listen scenario (plan.md §3.8, §5). It asks
the Catalogue for songs that are ready to play and uses the current weather as
**one supporting signal** to order them. Weather is optional: without it, or
when the Weather API fails, the service still recommends.

> **Status:** both dependencies are **real by default**: the Weather API is Open-Meteo
> (`WEATHER_MODE=open-meteo`) and songs come from the Catalogue Service
> (`CATALOGUE_MODE=http`). Stubs remain for running on their own. See
> [Stubs](#stubs-and-what-is-assumed).

## Interfaces

| Kind             | Contract                                                                                   | Notes |
|------------------|--------------------------------------------------------------------------------------------|-------|
| REST             | [`contracts/api/recommendation.openapi.yaml`](../../contracts/api/recommendation.openapi.yaml) | via gateway at `/api/recommendation/...` |
| Calls            | Catalogue Service `GET /songs` (assumed), Open-Meteo (weather)                             | see below |
| Events published | none                                                                                       | |
| Events consumed  | none                                                                                       | |
| gRPC             | none                                                                                       | |

```text
browser ──> gateway /api/recommendation/recommendations?lat=&lon= ──> recommendation
                                                                         ├──> Catalogue  (READY songs)
                                                                         └──> Weather API (optional signal)
```

`GET /recommendations?lat=&lon=&limit=` returns `{items, weather_used, weather}`.
`lat` and `lon` go together or not at all; `limit` is 1 to 50 (default 10).
`GET /health` is the liveness check.

## How it ranks

1. Ask the Catalogue for `READY` songs, so every result can be streamed.
2. If a location was sent, ask the Weather API for the weather there.
3. Songs whose `mood` suits the weather come first (`reason: WEATHER_MATCH`),
   then the rest in the Catalogue's order (`reason: GENERAL`).

| Weather               | Suitable moods                         |
|-----------------------|----------------------------------------|
| RAIN, STORM           | mellow, calm, chill, melancholy        |
| CLOUDY                | mellow, chill, focus                   |
| FOG, SNOW             | calm, chill, ambient, romantic         |
| CLEAR                 | upbeat, energetic                      |
| OTHER                 | none                                   |

Both mood vocabularies work: the four a user can pick on upload (calm, mellow,
upbeat, energetic) and the ones the Catalogue derives on its own (chill,
melancholy, romantic, focus, ambient, energetic). Matching ignores case.

`weather_used` is `true` only if the weather actually changed the result (some
song is a `WEATHER_MATCH`). The logic is plain functions in `ranking.py`.

**Limit:** `mood` is not in the shared Song contract. A song without one can
never be a weather match, so until the Catalogue provides a `mood` or `genre`
the weather signal can only be as good as that field.

## Stubs and what is assumed

| Dependency  | Default (real)                        | Stub, to run on its own        |
|-------------|---------------------------------------|--------------------------------|
| Catalogue   | the Catalogue Service (`CATALOGUE_MODE=http`, `CATALOGUE_URL`) | 8 fixed demo songs (`CATALOGUE_MODE=stub`) |
| Weather API | Open-Meteo (`WEATHER_MODE=open-meteo`, needs internet, no key) | the same condition for every location (`WEATHER_MODE=stub`) |

- The stub songs have fixed ids that **do not exist** in the real Catalogue or
  Streaming Service, so a browser cannot play them.
- `HttpCatalogue` is written and tested against a mock, but the endpoint it
  calls is an **assumption**, not agreed with the Catalogue owner:

  ```text
  GET {CATALOGUE_URL}/songs?processing_status=READY&limit=N
  200 {"items": [{"song_id", "title", "artist", "duration_ms", "mood"?}], "next_cursor": ...}
  ```

  If the Catalogue's real API differs, only `catalogue.py` changes.
- `WEATHER_MODE=off` behaves like a Weather API that is down. It exists to see
  the fallback working locally.
- `WEATHER_MODE=open-meteo` calls [Open-Meteo](https://open-meteo.com), which
  needs **no API key**, for the current weather at `lat`/`lon`. Its WMO weather
  code is mapped to the contract's `condition` (0-1 CLEAR, 2-3 CLOUDY, 45/48 FOG,
  51-67 and 80-82 RAIN, 71-77 and 85-86 SNOW, 95-99 STORM, anything else OTHER).
  Any failure becomes the same "no weather" fallback as above. Open-Meteo's free
  tier is for non-commercial use, which fits this project.

## Data owned

None. The service has no database: it holds no state between requests, and
reads songs and weather on every call.

## Configuration

See `.env.example` for every variable. Locally, Compose sets them
(`compose.yaml`); in production they come from the ECS task definition.

| Variable                    | Default                  | Meaning |
|-----------------------------|--------------------------|---------|
| `CATALOGUE_MODE`            | `http`                   | `stub` or `http` |
| `CATALOGUE_URL`             | `http://catalogue:8080`  | the Catalogue Service (`http` mode) |
| `CATALOGUE_TIMEOUT_SECONDS` | `3`                      | longer calls count as the Catalogue being down |
| `CANDIDATE_LIMIT`           | `100`                    | songs requested before ranking (at least `limit`) |
| `WEATHER_MODE`              | `open-meteo`             | `stub`, `off` or `open-meteo` |
| `WEATHER_URL`               | `https://api.open-meteo.com/v1/forecast` | the Open-Meteo endpoint (`open-meteo` mode) |
| `WEATHER_STUB_CONDITION`    | `RAIN`                   | what the stub returns |
| `WEATHER_TIMEOUT_SECONDS`   | `2`                      | a slower lookup is abandoned |

An invalid value stops the service at start-up instead of running in the wrong mode.

## Run

```sh
# whole stack (from the repo root)
docker compose up -d --build

# just this service, after editing it
docker compose up -d --build recommendation
curl "http://localhost:8080/api/recommendation/recommendations?lat=1.35&lon=103.82"
```

## Test

```sh
cd services/recommendation
pip install -r requirements-dev.txt
pytest
ruff check src tests && ruff format --check src tests
```

The tests need no network or Docker: the Catalogue and the Weather API are
replaced by fakes, and `HttpCatalogue` is tested against a mock server.
`test_contract.py` fails if the API stops matching
`contracts/api/recommendation.openapi.yaml`.

## Failure handling

| What fails                                   | What happens |
|----------------------------------------------|--------------|
| No location sent                             | Weather is not asked. `200`, `weather_used: false`. |
| Weather API down, errors, or returns garbage | Logged as a warning. `200`, `weather_used: false`. |
| Weather API too slow (`WEATHER_TIMEOUT_SECONDS`) | The lookup is abandoned. Same as above. |
| Weather matches no song                      | `200`, `weather_used: false`: weather is only reported when it changed the result. |
| Catalogue down, slow or unreadable           | `502 CATALOGUE_UNAVAILABLE`. There are no songs to recommend, so this is a real error. |
| No `READY` songs                             | `200` with an empty `items`. |

The weather handler catches every exception on purpose: a bug in a weather
provider must never stop someone listening. The service itself stays healthy
when the Catalogue is down (`/health` only says the process is alive).

**Not handled on purpose:** caching weather or catalogue responses, per-user
personalisation, recommending playlists, and rate limiting.

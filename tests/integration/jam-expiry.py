#!/usr/bin/env python3
"""Verify the Jam service expires a persisted room without an open room page."""

import argparse
import asyncio
import json
import os
import time
import uuid
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

Json = dict[str, Any]


class FlowError(Exception):
    pass


class Api:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, data: Json | None = None, expected: int = 200) -> Json:
        headers = {"Accept": "application/json"}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != expected:
                    raise FlowError(f"{method} {path}: HTTP {response.status}")
                raw = response.read(1_000_001)
        except HTTPError as error:
            detail = error.read(1000).decode("utf-8", errors="replace")
            error.close()
            raise FlowError(f"{method} {path}: HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise FlowError(f"{method} {path}: {error}") from error
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise FlowError(f"{path}: expected a JSON object")
        return result


async def backdate_activity(jam_id: str) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as database:
            await database.execute(
                text(
                    "UPDATE jams SET last_listener_active_at = "
                    "CURRENT_TIMESTAMP - INTERVAL '25 hours' WHERE jam_id = :jam_id"
                ),
                {"jam_id": jam_id},
            )
    finally:
        await engine.dispose()


def run(base_url: str, timeout: float, report_path: Path) -> int:
    run_id = uuid.uuid4().hex
    report: Json = {"run_id": run_id, "result": "FAIL", "checks": []}
    api = Api(base_url, 10)
    started = time.monotonic()
    try:
        credentials = {"username": f"expiry_{run_id[:16]}", "password": f"Expiry-{run_id}"}
        api.call("POST", "/api/auth/signup", credentials, expected=201)
        api.call("POST", "/api/auth/login", credentials)
        jam = api.call("POST", "/api/jam/jams", {}, expected=201)
        jam_id = str(uuid.UUID(jam["jam_id"]))
        report["jam_id"] = jam_id
        report["checks"].append("created a persisted Jam through the public API")

        asyncio.run(backdate_activity(jam_id))
        report["checks"].append("backdated server activity with no room WebSocket open")

        deadline = time.monotonic() + timeout
        retained = jam
        while time.monotonic() < deadline:
            retained = api.call("GET", f"/api/jam/jams/{jam_id}")
            if retained.get("lifecycle_state") == "ENDED":
                break
            time.sleep(0.5)
        if retained.get("lifecycle_state") != "ENDED":
            raise FlowError("Jam did not close after its persisted activity expired")
        report["checks"].append("background sweep closed the Jam without an open room page")

        try:
            api.call("POST", f"/api/jam/jams/{jam_id}/queue", {"song_id": str(uuid.uuid4())})
        except FlowError as error:
            if "HTTP 409" not in str(error):
                raise
        else:
            raise FlowError("closed Jam accepted a queue mutation")
        report["checks"].append("closed Jam remains readable and rejects mutations")
        report["result"] = "PASS"
        return 0
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        return 1
    finally:
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://gateway:8080")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--report", type=Path, default=Path("/tmp/jam-expiry-report.json"))
    args = parser.parse_args()
    return run(args.base_url, args.timeout, args.report)


if __name__ == "__main__":
    raise SystemExit(main())

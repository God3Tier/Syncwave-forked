#!/usr/bin/env python3
"""Run disruptive backend checks from the Docker CLI host, one fault at a time.

Requires a quiet, disposable, already running root Compose stack. Restores
services in finally blocks. No containers, queues, volumes or songs are deleted;
only this run's playlist is deleted. Uses Python's standard library.
"""

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
CONTROLLED = {"s3", "upload-publisher", "lyrics-worker", "waveform-worker", "playlist"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_upload():
    path = Path(__file__).with_name("upload-flow.py")
    spec = importlib.util.spec_from_file_location("fault_upload_helpers", path)
    require(spec is not None and spec.loader is not None, "Missing upload-flow.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Scenario:
    def __init__(self, args, report):
        self.args, self.report = args, report
        self.upload = load_upload()
        self.api = self.upload.Api(args.base_url, args.request_timeout)
        self.stopped, self.paused = set(), set()
        self.playlists = []
        self.compose = ["docker", "compose"]
        if args.project_name:
            self.compose += ["--project-name", args.project_name]

    def docker(self, *arguments, seconds=120):
        result = subprocess.run(
            [*self.compose, *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=seconds,
            check=False,
        )
        require(
            result.returncode == 0,
            f"docker compose {' '.join(arguments)} failed: {result.stderr[-3000:]}",
        )
        return result.stdout

    def preflight(self):
        raw = self.docker("ps", "--all", "--format", "json").strip()
        rows = json.loads(raw) if raw.startswith("[") else [json.loads(s) for s in raw.splitlines()]
        states = {row["Service"]: row["State"] for row in rows}
        required = CONTROLLED | {"upload", "catalogue", "jam", "sync", "audio_transmitter"}
        require(
            all(states.get(service) == "running" for service in required),
            f"Start all backend services before this test; current states: {states}",
        )
        self.report["initial_states"] = {service: states[service] for service in sorted(required)}
        for path in (
            "/api/upload/ready",
            "/api/catalogue/health",
            "/api/lyrics/health",
            "/api/waveform/health",
            "/api/streaming/health",
            "/api/playlist/health",
            "/api/jam/ready",
            "/api/sync/health",
        ):
            self.api.request(path)

    def control(self, action, service):
        require(service in CONTROLLED, "Unexpected disruption target")
        # Track BEFORE the command: even a timeout/ambiguous response must restore.
        if action == "stop":
            self.stopped.add(service)
        elif action == "pause":
            self.paused.add(service)
        if action == "restart":
            self.docker(action, "--no-deps", service)
        else:
            self.docker(action, service)
        if action in {"start", "restart"}:
            self.stopped.discard(service)
        elif action == "unpause":
            self.paused.discard(service)

    def http(
        self,
        method,
        path,
        *,
        data=None,
        content_type="application/json",
        expected=200,
        seconds=None,
    ):
        headers = {
            "Content-Type": content_type,
            "X-Jam-Token": os.getenv("MOCK_JAM_TOKEN", "local-jam-member-token"),
        }
        body = data if isinstance(data, bytes) or data is None else json.dumps(data).encode()
        request = Request(
            self.args.base_url.rstrip("/") + path, data=body, headers=headers, method=method
        )
        try:
            response = urlopen(request, timeout=seconds or self.args.request_timeout)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read(2_000_001)
            allowed = {expected} if isinstance(expected, int) else set(expected)
            require(
                response.code in allowed,
                f"{method} {path}: expected {expected}, got {response.code}: {raw[:1000]!r}",
            )
        return json.loads(raw) if raw else None

    def wait(self, check, label):
        deadline = time.monotonic() + self.args.timeout
        last = None
        while time.monotonic() < deadline:
            try:
                done, last = check()
                if done:
                    return last
            except (HTTPError, URLError, OSError, self.upload.FlowError) as exc:
                last = str(exc)
            time.sleep(1)
        raise RuntimeError(f"Timed out: {label}; last: {last}")

    def wait_status(self, path, field, target):
        def check():
            result = self.api.json(path, allow_missing=True)
            return result is not None and result.get(field) == target, result

        return self.wait(check, f"{path}: {field}={target}")

    def submit(self, label, *, audio=None):
        audio = self.upload.audio_fixture() if audio is None else audio
        title = f"fault-{self.report['run_id']}-{label}"
        body, content_type = self.upload.multipart(title, audio)
        receipt = self.api.json(
            "/api/upload/uploads", data=body, content_type=content_type, expected_status=202
        )
        require(receipt["title"] == title, "Upload returned wrong fixture title")
        self.report["fixtures"].append(receipt)
        return receipt, audio

    def verify(self, receipt, audio):
        evidence = {
            key: receipt[key]
            for key in ("song_id", "event_id", "title", "audio_reference", "lyrics_reference")
        }
        self.upload.verify(self.api, self.args.timeout, evidence, audio=audio)
        return evidence

    def corrupt_audio(self):
        # Recognizable WAV signature passes ingestion; missing RIFF chunks must
        # fail in the real decoder rather than in Upload's header validation.
        receipt, _ = self.submit("corrupt", audio=b"RIFF\x08\x00\x00\x00WAVEbroken")
        song_id = receipt["song_id"]
        wave = self.wait_status(f"/api/waveform/songs/{song_id}/waveform", "status", "FAILED")
        require(
            wave["error"]["code"] == "AUDIO_UNDECODABLE" and wave["error"]["message"],
            "Decoder failure lacks expected actionable error",
        )
        catalogue = self.wait_status(
            f"/api/catalogue/songs/{song_id}", "processing_status", "PARTIAL"
        )
        require(
            catalogue["lyrics_status"] == "READY" and catalogue["waveform_status"] == "FAILED",
            "Corrupt audio incorrectly blocked valid lyrics",
        )
        return {"song_id": song_id, "waveform": wave, "catalogue": catalogue}

    def s3_outage(self):
        self.control("stop", "s3")
        try:
            body, content_type = self.upload.multipart(
                f"fault-{self.report['run_id']}-s3-down", self.upload.audio_fixture()
            )
            failed = self.http(
                "POST",
                "/api/upload/uploads",
                data=body,
                content_type=content_type,
                expected=503,
                seconds=90,
            )
            require(failed["error"]["code"] == "STORAGE_UNAVAILABLE", "Wrong S3 outage error")
            song_id = str(uuid.UUID(failed["error"]["message"].rsplit(" ", 1)[-1]))
            receipt = self.api.json(f"/api/upload/uploads/{song_id}")
            self.report["fixtures"].append(receipt)
            require(
                receipt["status"] == "FAILED" and receipt["publish_attempts"] == 0,
                "S3 failure queued or published an incomplete upload",
            )
            self.http("GET", f"/api/catalogue/songs/{song_id}", expected=404)
        finally:
            self.control("start", "s3")
        self.wait(
            lambda: (self.api.json("/api/upload/ready") is not None, "ready"),
            "S3 and Upload recover",
        )
        recovered, audio = self.submit("s3-restored")
        return {"failed_upload": receipt, "recovered_upload": self.verify(recovered, audio)}

    def publisher_restart(self):
        self.control("stop", "upload-publisher")
        try:
            receipt, audio = self.submit("publisher-pending")
            pending = self.api.json(f"/api/upload/uploads/{receipt['song_id']}")
            require(
                pending["status"] == "PENDING" and pending["publish_attempts"] == 0,
                "Fixture was not durably pending while publisher was stopped",
            )
        finally:
            self.control("restart", "upload-publisher")
        result = self.verify(receipt, audio)
        require(result["event_id"] == pending["event_id"], "Publisher recovery changed event ID")
        return {"pending": pending, "recovered": result}

    def worker_restart(self):
        for service in ("lyrics-worker", "waveform-worker"):
            self.control("stop", service)
        try:
            receipt, audio = self.submit("workers-pending")
            self.wait_status(f"/api/upload/uploads/{receipt['song_id']}", "status", "PUBLISHED")
            waiting = self.wait_status(
                f"/api/catalogue/songs/{receipt['song_id']}", "processing_status", "PROCESSING"
            )
            require(
                waiting["lyrics_status"] != "READY" and waiting["waveform_status"] != "READY",
                "Fixture processed while both workers were stopped",
            )
        finally:
            for service in ("lyrics-worker", "waveform-worker"):
                self.control("restart", service)
        return {"pending": waiting, "recovered": self.verify(receipt, audio)}

    def playlist_and_timeout(self):
        ready = self.api.json("/api/catalogue/songs?processing_status=READY&limit=2")["items"]
        require(len(ready) == 2, "Need two READY songs from prior scenarios")
        owner = str(uuid.uuid4())
        playlist = self.http(
            "POST",
            "/api/playlist/playlists",
            data={"owner_id": owner, "name": f"fault-{self.report['run_id']}"},
            expected=201,
        )
        playlist_id = playlist["playlist_id"]
        self.playlists.append(playlist_id)
        path = f"/api/playlist/playlists/{playlist_id}"
        for song in ready:
            self.http("POST", path + "/songs", data={"song_id": song["song_id"]})
        before = self.http("GET", path)
        self.control("restart", "playlist")
        after = self.wait(lambda: (True, self.api.json(path)), "Playlist restart")
        require(after == before, "Playlist content/order did not survive restart")

        # Warm Jam's real Playlist gRPC channel before freezing the dependency.
        request = {"owner_id": owner, "playlist_id": playlist_id}
        warm = self.http("POST", "/api/jam/jams", data=request, expected=201)
        self.report["retained_jams"].append(warm["jam_id"])
        self.control("pause", "playlist")
        try:
            started = time.monotonic()
            failure = self.http("POST", "/api/jam/jams", data=request, expected=503, seconds=10)
            elapsed = time.monotonic() - started
            require(
                0.4 <= elapsed < 5,
                f"Expected a bounded real dependency timeout, got {elapsed:.3f}s",
            )
        finally:
            self.control("unpause", "playlist")

        def usable_again():
            result = self.http("POST", "/api/jam/jams", data=request, expected=(201, 503))
            return "jam_id" in result, result

        recovered = self.wait(usable_again, "Jam reconnects to unpaused Playlist")
        self.report["retained_jams"].append(recovered["jam_id"])
        return {
            "playlist_id": playlist_id,
            "order_preserved": True,
            "timeout_seconds": round(elapsed, 3),
            "error": failure,
            "recovered_jam_id": recovered["jam_id"],
        }

    def owner_permissions(self):
        owner, member = str(uuid.uuid4()), str(uuid.uuid4())
        jam = self.http("POST", "/api/jam/jams", data={"owner_id": owner}, expected=201)
        jam_id = jam["jam_id"]
        self.report["retained_jams"].append(jam_id)
        path = f"/api/jam/jams/{jam_id}"
        self.http("POST", path + "/members", data={"participant_id": member})
        ready = self.api.json("/api/catalogue/songs?processing_status=READY&limit=1")["items"]
        require(bool(ready), "Need a READY fixture for active Jam authorization checks")
        self.http("POST", path + "/queue", data={"actor_id": owner, "song_id": ready[0]["song_id"]})
        self.http(
            "POST",
            path + "/playback/start",
            data={"actor_id": owner, "request_id": str(uuid.uuid4())},
        )
        before = self.http("GET", path)
        require(before["sync_generation"] is not None, "Jam has no active playback generation")
        rejected = []
        for action in ("start", "pause", "resume", "seek", "skip"):
            body = {"actor_id": member, "request_id": str(uuid.uuid4())}
            if action == "seek":
                body["position_ms"] = 1000
            self.http("POST", path + f"/playback/{action}", data=body, expected=403)
            require(self.http("GET", path) == before, f"Unauthorized {action} changed Jam state")
            rejected.append(action)
        return {"jam_id": jam_id, "rejected_actions": rejected, "state_unchanged": True}

    def cleanup(self):
        errors = []
        # Resume a frozen service before starting stopped ones.
        for action, targets in (("unpause", self.paused), ("start", self.stopped)):
            for service in sorted(targets.copy()):
                try:
                    self.control(action, service)
                except Exception as exc:
                    errors.append(f"{service}: {exc}")
        for playlist_id in self.playlists:
            try:
                self.http("DELETE", f"/api/playlist/playlists/{playlist_id}", expected=204)
            except Exception as exc:
                errors.append(f"playlist {playlist_id}: {exc}")
        return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--project-name")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--request-timeout", type=float, default=15)
    parser.add_argument(
        "--report", type=Path, default=Path(__file__).with_name("failure-recovery-report.json")
    )
    args = parser.parse_args()

    def terminate(_signal, _frame):
        raise KeyboardInterrupt("termination requested")

    signal.signal(signal.SIGTERM, terminate)
    address = urlsplit(args.base_url)
    if address.scheme not in {"http", "https"} or not address.netloc:
        parser.error("--base-url must be an HTTP(S) gateway URL")
    if any(not 0 < value < float("inf") for value in (args.timeout, args.request_timeout)):
        parser.error("timeouts must be finite positive numbers")
    report = {
        "run_id": uuid.uuid4().hex,
        "result": "FAIL",
        "checks": [],
        "fixtures": [],
        "retained_jams": [],
        "cleanup": {},
        "scope": "Disruptive backend tests; only run against a disposable quiet stack",
        "retained_data": "Generated songs, S3 objects, failed audio DLQ entry and test Jams",
    }
    started = time.monotonic()
    scenario = Scenario(args, report)
    try:
        scenario.preflight()
        for name in (
            "corrupt_audio",
            "s3_outage",
            "publisher_restart",
            "worker_restart",
            "playlist_and_timeout",
            "owner_permissions",
        ):
            evidence = {"name": name, "result": "FAIL"}
            report["checks"].append(evidence)
            evidence["evidence"] = getattr(scenario, name)()
            evidence["result"] = "PASS"
            print(f"PASS {name}", flush=True)
        report["result"] = "PASS"
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"FAIL {report['error']}", file=sys.stderr, flush=True)
    finally:
        errors = scenario.cleanup()
        report["cleanup"] = {
            "services_restored_and_playlists_deleted": not errors,
            "errors": errors,
        }
        if errors:
            report["result"] = "FAIL"
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

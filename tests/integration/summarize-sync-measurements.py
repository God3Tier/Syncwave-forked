#!/usr/bin/env python3
"""Summarize real CSV measurements; never generate measurements or estimates.

At least 20 runs, each with a laptop and two phones, plus delayed-client and
reconnect observations are required. Audible times must share a recording
reference within each run. See ITEM4_RUNBOOK.md for the recording procedure.
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(row, key, *, nonnegative=False):
    value = float(row[key])
    require(
        math.isfinite(value) and (not nonnegative or value >= 0),
        f"{key} must be a finite {'nonnegative ' if nonnegative else ''}measurement",
    )
    return value


def percentile(values, fraction):
    values = sorted(values)
    point = (len(values) - 1) * fraction
    low, high = math.floor(point), math.ceil(point)
    return values[low] + (values[high] - values[low]) * (point - low)


def read(path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def analyze(args, report):
    runs = defaultdict(list)
    for row in read(args.starts):
        require(
            all(
                (row.get(key) or "").strip()
                for key in (
                    "run_id",
                    "device_id",
                    "device_type",
                    "browser_version",
                    "network",
                    "measurement_method",
                    "evidence_ref",
                )
            ),
            "Missing start evidence/device details",
        )
        require(
            row["measurement_method"] == "external_audio_recording",
            "Audible timing must come from external_audio_recording, not browser timers",
        )
        row["audible_start_ms"] = number(row, "audible_start_ms", nonnegative=True)
        row["timer_start_error_ms"] = number(row, "timer_start_error_ms")
        row["max_abs_drift_ms"] = number(row, "max_abs_drift_ms", nonnegative=True)
        count = number(row, "correction_count", nonnegative=True)
        require(count.is_integer(), "correction_count must be an integer")
        samples = number(row, "clock_samples", nonnegative=True)
        require(
            samples.is_integer() and samples >= 5, "Each device needs at least five clock samples"
        )
        runs[row["run_id"]].append(row)
    require(len(runs) >= 20, f"Need at least 20 measured runs; found {len(runs)}")
    spreads, timer_spreads = [], []
    report["runs"] = []
    for run_id, rows in sorted(runs.items()):
        require(len({row["device_id"] for row in rows}) == len(rows), "Duplicate device/run row")
        kinds = [row["device_type"] for row in rows]
        require(
            kinds.count("laptop") >= 1 and kinds.count("phone") >= 2,
            f"{run_id}: need a laptop and two phones",
        )
        require(
            len({row["evidence_ref"] for row in rows}) == 1,
            f"{run_id}: audible starts need one common recording/time reference",
        )
        audible = [row["audible_start_ms"] for row in rows]
        timer = [row["timer_start_error_ms"] for row in rows]
        spread, timer_spread = max(audible) - min(audible), max(timer) - min(timer)
        spreads.append(spread)
        timer_spreads.append(timer_spread)
        report["runs"].append(
            {
                "run_id": run_id,
                "audible_spread_ms": spread,
                "timer_spread_ms": timer_spread,
                "measurements": rows,
            }
        )
    events = read(args.events)
    seen = set()
    for event in events:
        require(event.get("run_id") in runs, "Recovery event references an unknown run")
        require(
            event.get("device_id") in {r["device_id"] for r in runs[event["run_id"]]},
            "Recovery event references an unknown device",
        )
        require(bool((event.get("evidence_ref") or "").strip()), "Recovery event has no evidence")
        require(event["event_type"] in {"delayed_client", "reconnect"}, "Unknown recovery event")
        event["recovery_time_ms"] = number(event, "recovery_time_ms", nonnegative=True)
        event["post_recovery_abs_drift_ms"] = number(
            event, "post_recovery_abs_drift_ms", nonnegative=True
        )
        event["room_timeline_restarted"] = (
            (event.get("room_timeline_restarted") or "").strip().lower()
        )
        require(
            event["room_timeline_restarted"] in {"true", "false"},
            "room_timeline_restarted must be true or false",
        )
        seen.add(event["event_type"])
    require(
        seen == {"delayed_client", "reconnect"}, "Need delayed-client AND reconnect measurements"
    )
    report["audible_start_spread_ms"] = {
        "p50": percentile(spreads, 0.5),
        "p95": percentile(spreads, 0.95),
        "max": max(spreads),
    }
    report["timer_start_spread_ms"] = {
        "p50": percentile(timer_spreads, 0.5),
        "p95": percentile(timer_spreads, 0.95),
        "max": max(timer_spreads),
    }
    report["events"] = events
    report["targets"] = {
        "audible_p95_ms": args.start_spread_target_ms,
        "recovery_drift_ms": args.recovery_drift_target_ms,
    }
    passed = report["audible_start_spread_ms"]["p95"] <= args.start_spread_target_ms and all(
        event["post_recovery_abs_drift_ms"] <= args.recovery_drift_target_ms
        and event["room_timeline_restarted"].lower() == "false"
        for event in events
    )
    report["result"] = "PASS" if passed else "FAIL"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starts", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--start-spread-target-ms", type=float, default=100)
    parser.add_argument("--recovery-drift-target-ms", type=float, default=80)
    args = parser.parse_args()
    if any(
        not 0 < value < float("inf")
        for value in (args.start_spread_target_ms, args.recovery_drift_target_ms)
    ):
        parser.error("targets must be finite positive numbers")
    report = {"result": "INCOMPLETE", "scope": "User-supplied physical audio measurements"}
    try:
        analyze(args, report)
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        report["error"] = str(exc)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

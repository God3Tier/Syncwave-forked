#!/usr/bin/env python3
"""Check deployed app images have blocking child test jobs and retained results.

Static CI configuration check only. Does not execute tests or contact GitLab.
Requires PyYAML; understands this repository's local service.yml inheritance.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def merge(base, overrides):
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolve(name, jobs, trail=()):
    require(name not in trail, f"Circular CI inheritance: {name}")
    job = jobs[name]
    result = {}
    parents = job.get("extends", [])
    if isinstance(parents, str):
        parents = [parents]
    for parent in parents:
        result = merge(result, resolve(parent, jobs, (*trail, name)))
    return merge(result, job)


def applications(path, seen=None):
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        return set()
    seen.add(path)
    model, result = read(path), set()
    for item in model.get("include", []):
        paths = item.get("path") if isinstance(item, dict) else item
        for child in paths if isinstance(paths, list) else [paths]:
            result |= applications(path.parent / child, seen)
    for service in model.get("services", {}).values():
        if "build" not in service or "test" in service.get("profiles", []):
            continue
        build = service["build"]
        context = build["context"] if isinstance(build, dict) else build
        directory = (path.parent / context).resolve()
        require(directory.is_relative_to(ROOT), "Application context is outside the repository")
        result.add(directory.relative_to(ROOT).as_posix())
    return result


def inspect(report):
    parent = read(ROOT / ".gitlab-ci.yml")
    shared = read(ROOT / "ci/service.yml")
    deployed = applications(ROOT / "docker-compose.yml")
    require(bool(deployed), "No deployed application images discovered")
    for directory in sorted(deployed):
        evidence = {"service_dir": directory, "result": "FAIL"}
        report["services"].append(evidence)
        child_path = f"{directory}/.gitlab-ci.yml"
        child = read(ROOT / child_path)
        triggers = []
        for name, job in parent.items():
            if name.startswith(".") or not isinstance(job, dict) or "trigger" not in job:
                continue
            included = job["trigger"].get("include")
            if included == child_path or included == [{"local": child_path}]:
                effective = resolve(name, parent)
                require(
                    effective["trigger"].get("strategy") in {"depend", "mirror"},
                    f"{directory}: parent does not wait for child test failures",
                )
                require(not effective.get("allow_failure", False), f"{directory}: optional trigger")
                triggers.append(name)
        require(bool(triggers), f"{directory}: missing parent pipeline trigger")
        jobs = {**shared, **child}
        tests = []
        for name, job in child.items():
            if name.startswith(".") or not isinstance(job, dict) or "script" not in job:
                continue
            effective = resolve(name, jobs)
            if effective.get("stage") != "test":
                continue
            require(not effective.get("allow_failure", False), f"{directory}/{name}: optional test")
            require(
                effective.get("when", "on_success") != "manual", f"{directory}/{name}: manual test"
            )
            script = effective["script"]
            require(
                isinstance(script, list) and all(isinstance(line, str) for line in script),
                f"{directory}/{name}: invalid script",
            )
            require(
                any(
                    command in "\n".join(script)
                    for command in ("pytest", "cargo test", "make test", "vitest")
                ),
                f"{directory}/{name}: no recognized unit-test invocation",
            )
            artifacts = effective.get("artifacts", {})
            require(
                artifacts.get("when") == "always", f"{directory}/{name}: failure results discarded"
            )
            require(
                artifacts.get("paths") or artifacts.get("reports", {}).get("junit"),
                f"{directory}/{name}: no test artifacts",
            )
            tests.append({"job": name, "artifacts": artifacts})
        require(bool(tests), f"{directory}: no blocking unit-test jobs found")
        evidence.update(result="PASS", parent_triggers=triggers, test_jobs=tests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = {
        "result": "FAIL",
        "scope": "CI configuration coverage; not unit-test execution results",
        "services": [],
    }
    try:
        inspect(report)
        report["result"] = "PASS"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(report, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

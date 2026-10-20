"""Fixture builders for release qualification contract tests."""

from __future__ import annotations

import copy
from pathlib import Path
from types import ModuleType


def _qualification_inventory(tool: ModuleType) -> tuple[bytes, dict[str, object]]:
    inventory_path = (
        Path(__file__).resolve().parents[1] / ".github" / "release-qualification.json"
    )
    raw = inventory_path.read_bytes()
    return raw, tool._qualification.load_inventory(raw)


def _qualification_evidence(
    manifest: dict[str, object],
    entry: dict[str, object],
    *,
    digest: str,
    run_id: int,
    job_id: int,
    attempt: int,
    scenario: str = "pass",
) -> dict[str, object]:
    job = entry["job"]
    binding = {
        "repository": manifest["repository"],
        "candidate_id": manifest["candidate_id"],
        "generation": manifest["generation"],
        "checked_out_sha": manifest["sha"],
        "expected_core_version": manifest["core_version"],
        "installed_core_version": manifest["core_version"],
        "inventory_digest": digest,
        "workflow_run_id": run_id,
        "job_id": job_id,
        "job_name": job["name"],
        "attempt": attempt,
    }
    if entry["evidence_kind"] == "command":
        missing_bindings = ["required_binding"] if scenario == "bindings" else []
        conclusion = (
            "failure" if scenario in {"bindings", "command-failure"} else "success"
        )
        return {
            "schema_version": 1,
            "kind": "command",
            "binding": binding,
            "steps": [
                {
                    "name": "Check pinned core bindings",
                    "status": "completed",
                    "conclusion": conclusion,
                    "exit_status": 1 if conclusion == "failure" else 0,
                }
            ],
            "missing_bindings": missing_bindings,
            "diagnostics": [],
        }
    collected = 2
    passed = 2
    failed = errors = skipped = 0
    collection_failed = False
    exit_status = 0
    node_ids: list[str] = []
    if scenario == "tests":
        passed, failed, exit_status = 1, 1, 1
        node_ids = ["tests/test_qualification.py::test_breaks"]
    elif scenario == "collection":
        collected, passed, collection_failed, exit_status = 1, 1, True, 2
    elif scenario == "zero":
        collected, passed = 0, 0
    elif scenario == "bad-counts":
        collected, passed = 3, 2
    elif scenario == "binding":
        binding["candidate_id"] = "candidate-stale"
    return {
        "schema_version": 1,
        "kind": "pytest",
        "binding": binding,
        "collected": collected,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "collection_failed": collection_failed,
        "exit_status": exit_status,
        "first_failing_node_ids": node_ids,
        "flaky_lines": ["FLAKY: tests/test_qualification.py::test_flaky"]
        if scenario == "tests"
        else [],
    }


def _qualification_job_record(
    manifest: dict[str, object],
    entry: dict[str, object],
    *,
    digest: str,
    run_id: int,
    job_id: int,
    attempt: int,
    scenario: str = "pass",
) -> dict[str, object]:
    job = entry["job"]
    conclusion = "success"
    status = "completed"
    evidence = None
    if entry["evidence_kind"] in {"pytest", "command"}:
        evidence = _qualification_evidence(
            manifest,
            entry,
            digest=digest,
            run_id=run_id,
            job_id=job_id,
            attempt=attempt,
            scenario=scenario,
        )
        if scenario in {"tests", "collection", "bindings", "command-failure"}:
            conclusion = "failure"
        if scenario == "skipped":
            conclusion = "skipped"
    if scenario == "in-progress":
        status, conclusion = "in_progress", None
    record: dict[str, object] = {
        "workflow_file": entry["workflow"],
        "workflow_job_id": job["id"],
        "matrix": copy.deepcopy(job["matrix"]),
        "job_id": job_id,
        "job_name": job["name"],
        "workflow_run_id": run_id,
        "execution_attempt": attempt,
        "status": status,
        "conclusion": conclusion,
        "url": f"https://github.com/sase-org/sase/actions/runs/{run_id}/job/{job_id}",
        "started_at": f"2026-10-19T20:0{attempt}:00Z",
        "completed_at": f"2026-10-19T20:1{attempt}:00Z",
        "steps": [
            {"name": "setup", "status": "completed", "conclusion": "success"},
            {
                "name": "run",
                "status": "completed" if status == "completed" else status,
                "conclusion": conclusion,
            },
            *[
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in entry.get("required_reporting_steps", [])
            ],
        ],
    }
    if evidence is not None:
        record["evidence"] = evidence
    return record


def _qualification_bundle(
    tool: ModuleType,
    manifest: dict[str, object],
    *,
    run_id: int = 700,
    scenarios: list[dict[str, str]] | None = None,
    missing_jobs: set[str] | None = None,
    advisory_failures: set[str] | None = None,
) -> dict[str, object]:
    raw, inventory = _qualification_inventory(tool)
    digest = tool._qualification.inventory_digest(raw)
    checks = inventory["checks"]
    scenarios = scenarios or [{}]
    attempts: list[dict[str, object]] = []
    previous: dict[str, dict[str, object]] = {}
    next_job_id = 1000
    for attempt, scenario_map in enumerate(scenarios, start=1):
        jobs: list[dict[str, object]] = []
        for index, entry in enumerate(checks):
            check_id = entry["id"]
            if attempt == len(scenarios) and missing_jobs and check_id in missing_jobs:
                continue
            scenario = scenario_map.get(check_id, "pass")
            if attempt > 1 and check_id not in scenario_map and check_id in previous:
                jobs.append(copy.deepcopy(previous[check_id]))
                continue
            next_job_id += 1
            if entry["disposition"] == "advisory" and check_id in (
                advisory_failures or set()
            ):
                scenario = "advisory-failure"
            record = _qualification_job_record(
                manifest,
                entry,
                digest=digest,
                run_id=run_id,
                job_id=next_job_id,
                attempt=attempt,
                scenario=scenario,
            )
            if scenario == "advisory-failure":
                record["conclusion"] = "failure"
                record["steps"] = [
                    {"name": "advisory", "status": "completed", "conclusion": "failure"}
                ]
            jobs.append(record)
            previous[check_id] = record
        attempts.append({"attempt": attempt, "jobs": jobs})
    return {
        "schema_version": 1,
        "repository": manifest["repository"],
        "candidate_id": manifest["candidate_id"],
        "generation": manifest["generation"],
        "sha": manifest["sha"],
        "expected_core_version": manifest["core_version"],
        "inventory_digest": digest,
        "workflow_run_id": run_id,
        "current_attempt": len(attempts),
        "attempts": attempts,
    }


def _qualification_result(
    tool: ModuleType,
    manifest: dict[str, object],
    bundle: dict[str, object],
) -> dict[str, object]:
    raw, _ = _qualification_inventory(tool)
    return tool._qualification.evaluate_qualification(manifest, raw, bundle)


def _failure_with_class(
    report: dict[str, object], failure_class: str
) -> dict[str, object]:
    failures = report["failures"]
    return next(
        failure for failure in failures if failure["failure_class"] == failure_class
    )


failure_with_class = _failure_with_class
qualification_bundle = _qualification_bundle
qualification_inventory = _qualification_inventory
qualification_result = _qualification_result


__all__ = [
    "_failure_with_class",
    "_qualification_bundle",
    "_qualification_inventory",
    "_qualification_result",
    "failure_with_class",
    "qualification_bundle",
    "qualification_inventory",
    "qualification_result",
]

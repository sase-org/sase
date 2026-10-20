#!/usr/bin/env python3
"""Evaluate candidate-bound N1 qualification evidence and rerun provenance."""

from __future__ import annotations

import base64
import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any


_inventory_path = Path(__file__).with_name("_release_qualification_inventory.py")
_inventory_loader = SourceFileLoader(
    "release_qualification_inventory_tool", str(_inventory_path)
)
_inventory_spec = importlib.util.spec_from_file_location(
    "release_qualification_inventory_tool",
    _inventory_path,
    loader=_inventory_loader,
)
if _inventory_spec is None or _inventory_spec.loader is None:
    raise RuntimeError(
        f"cannot load qualification inventory helpers at {_inventory_path}"
    )
_inventory = importlib.util.module_from_spec(_inventory_spec)
sys.modules[_inventory_spec.name] = _inventory
_inventory_spec.loader.exec_module(_inventory)

INVENTORY_SCHEMA_VERSION = _inventory.INVENTORY_SCHEMA_VERSION
JOB_BUNDLE_SCHEMA_VERSION = _inventory.JOB_BUNDLE_SCHEMA_VERSION
EVIDENCE_SCHEMA_VERSION = _inventory.EVIDENCE_SCHEMA_VERSION
QUALIFICATION_SCHEMA_VERSION = _inventory.QUALIFICATION_SCHEMA_VERSION
FAILURE_CLASSES = _inventory.FAILURE_CLASSES
PYTEST_COUNT_FIELDS = _inventory.PYTEST_COUNT_FIELDS
BINDING_FIELDS = _inventory.BINDING_FIELDS
QualificationInputError = _inventory.QualificationInputError
strict_json_loads = _inventory.strict_json_loads
inventory_digest = _inventory.inventory_digest
_require_keys = _inventory._require_keys
_is_int = _inventory._is_int
load_inventory = _inventory.load_inventory
load_inventory_file = _inventory.load_inventory_file
load_job_bundle_file = _inventory.load_job_bundle_file


def _failure(
    job: str,
    failure_class: str,
    *diagnostics: str,
    first_failing_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    if failure_class not in FAILURE_CLASSES:
        raise AssertionError(f"unknown qualification failure class {failure_class!r}")
    return {
        "job": job,
        "failure_class": failure_class,
        "first_failing_node_ids": list(first_failing_node_ids or []),
        "diagnostics": [diagnostic for diagnostic in diagnostics if diagnostic],
    }


def _report(
    *,
    manifest: dict[str, Any],
    digest: str,
    workflow_run_id: int | None,
    current_attempt: int | None,
    failures: list[dict[str, Any]],
    advisories: list[dict[str, Any]] | None = None,
    attempt_results: list[dict[str, Any]] | None = None,
    input_error: str = "",
) -> dict[str, Any]:
    verdict = "pass" if not failures else "red"
    rerun_eligible = False
    rerun_reason = "qualification is green" if verdict == "pass" else ""
    if not rerun_reason:
        if (
            current_attempt == 1
            and failures
            and all(failure["failure_class"] == "tests" for failure in failures)
        ):
            rerun_eligible = True
            rerun_reason = "first attempt failed only in collected tests"
        elif current_attempt is not None and current_attempt > 1:
            rerun_reason = "a second qualification attempt is never rerun-eligible"
        else:
            rerun_reason = (
                "collection, harness, missing, or zero evidence is not rerun-eligible"
            )
    if input_error:
        rerun_eligible = False
        rerun_reason = "qualification inputs were unreadable"
    identity = {
        "repository": manifest.get("repository"),
        "candidate_id": manifest.get("candidate_id"),
        "generation": manifest.get("generation"),
        "sha": manifest.get("sha"),
        "expected_core_version": manifest.get("core_version"),
    }
    report = {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        **identity,
        "inventory_digest": digest,
        "workflow_run_id": workflow_run_id,
        "current_attempt": current_attempt,
        "verdict": verdict,
        "failures": failures,
        "advisories": advisories or [],
        "attempt_results": attempt_results or [],
        "rerun_eligible": rerun_eligible,
        "rerun_reason": rerun_reason,
        "input_error": input_error or None,
    }
    report["reason"] = "" if verdict == "pass" else qualify_failure_summary(report)
    return report


def _bundle_shape(bundle: Any) -> tuple[int, int, list[dict[str, Any]]]:
    if not isinstance(bundle, dict):
        raise QualificationInputError("job history must be an object")
    keys = {
        "schema_version",
        "repository",
        "candidate_id",
        "generation",
        "sha",
        "expected_core_version",
        "inventory_digest",
        "workflow_run_id",
        "current_attempt",
        "attempts",
    }
    _require_keys(bundle, keys, keys, where="job history")
    if bundle["schema_version"] != JOB_BUNDLE_SCHEMA_VERSION:
        raise QualificationInputError(
            f"unknown job history schema_version {bundle['schema_version']!r}"
        )
    if not _is_int(bundle["workflow_run_id"]) or bundle["workflow_run_id"] <= 0:
        raise QualificationInputError(
            "job history workflow_run_id must be a positive integer"
        )
    if not _is_int(bundle["current_attempt"]) or bundle["current_attempt"] < 1:
        raise QualificationInputError(
            "job history current_attempt must be a positive integer"
        )
    attempts = bundle["attempts"]
    if not isinstance(attempts, list) or not attempts:
        raise QualificationInputError("job history has no attempt snapshots")
    if bundle["current_attempt"] > 2:
        raise QualificationInputError(
            "qualification allows at most one job-level rerun"
        )
    if len(attempts) != bundle["current_attempt"]:
        raise QualificationInputError("job history omits one or more workflow attempts")
    normalized: list[dict[str, Any]] = []
    for index, snapshot in enumerate(attempts, start=1):
        if not isinstance(snapshot, dict):
            raise QualificationInputError(f"attempts[{index - 1}] must be an object")
        _require_keys(
            snapshot,
            {"attempt", "jobs"},
            {"attempt", "jobs"},
            where=f"attempts[{index - 1}]",
        )
        if snapshot["attempt"] != index:
            raise QualificationInputError(
                "job history attempts must be contiguous from 1"
            )
        if not isinstance(snapshot["jobs"], list):
            raise QualificationInputError(f"attempt {index} jobs must be a list")
        seen_ids: set[int] = set()
        rows: list[dict[str, Any]] = []
        for row_index, raw_record in enumerate(snapshot["jobs"]):
            where = f"attempt {index} jobs[{row_index}]"
            if not isinstance(raw_record, dict):
                raise QualificationInputError(f"{where} must be an object")
            allowed = {
                "workflow_file",
                "workflow_job_id",
                "matrix",
                "job_id",
                "job_name",
                "workflow_run_id",
                "execution_attempt",
                "status",
                "conclusion",
                "url",
                "started_at",
                "completed_at",
                "steps",
                "evidence_file",
                "evidence",
                "evidence_error",
                "evidence_error_class",
            }
            required = allowed - {
                "evidence_file",
                "evidence",
                "evidence_error",
                "evidence_error_class",
            }
            _require_keys(raw_record, required, allowed, where=where)
            record = raw_record
            if not _is_int(record["job_id"]) or record["job_id"] <= 0:
                raise QualificationInputError(f"{where}.job_id must be positive")
            if record["job_id"] in seen_ids:
                raise QualificationInputError(
                    f"attempt {index} has duplicate authoritative job id {record['job_id']}"
                )
            seen_ids.add(record["job_id"])
            if not _is_int(record["workflow_run_id"]) or record["workflow_run_id"] <= 0:
                raise QualificationInputError(
                    f"{where}.workflow_run_id must be positive"
                )
            if not _is_int(record["execution_attempt"]) or not (
                1 <= record["execution_attempt"] <= index
            ):
                raise QualificationInputError(f"{where}.execution_attempt is invalid")
            if not isinstance(record["workflow_file"], str) or not isinstance(
                record["workflow_job_id"], str
            ):
                raise QualificationInputError(f"{where} workflow mapping is invalid")
            if not isinstance(record["job_name"], str) or not isinstance(
                record["matrix"], dict
            ):
                raise QualificationInputError(f"{where} job identity is invalid")
            if not isinstance(record["status"], str) or not (
                isinstance(record["conclusion"], str) or record["conclusion"] is None
            ):
                raise QualificationInputError(
                    f"{where} status or conclusion is invalid"
                )
            if not isinstance(record["url"], str) or not isinstance(
                record["steps"], list
            ):
                raise QualificationInputError(f"{where} URL or steps are invalid")
            for timestamp in ("started_at", "completed_at"):
                if record[timestamp] is not None and not isinstance(
                    record[timestamp], str
                ):
                    raise QualificationInputError(
                        f"{where}.{timestamp} must be text or null"
                    )
            if "evidence" in record and not isinstance(record["evidence"], dict):
                raise QualificationInputError(f"{where}.evidence must be an object")
            if "evidence_error" in record and not isinstance(
                record["evidence_error"], str
            ):
                raise QualificationInputError(f"{where}.evidence_error must be text")
            if "evidence_error_class" in record and record[
                "evidence_error_class"
            ] not in {
                "missing",
                "harness",
            }:
                raise QualificationInputError(
                    f"{where}.evidence_error_class is invalid"
                )
            rows.append(record)
        normalized.append({"attempt": index, "jobs": rows})
    return bundle["workflow_run_id"], bundle["current_attempt"], normalized


def _identity_errors(
    manifest: dict[str, Any], bundle: dict[str, Any], digest: str
) -> list[str]:
    expected = {
        "repository": manifest.get("repository"),
        "candidate_id": manifest.get("candidate_id"),
        "generation": manifest.get("generation"),
        "sha": manifest.get("sha"),
        "expected_core_version": manifest.get("core_version"),
        "inventory_digest": digest,
    }
    return [
        f"{field} mismatch: expected {value!r}, got {bundle.get(field)!r}"
        for field, value in expected.items()
        if bundle.get(field) != value
    ]


def _entry_matches(record: dict[str, Any], entry: dict[str, Any]) -> bool:
    job = entry["job"]
    return (
        record.get("workflow_file") == entry["workflow"]
        and record.get("workflow_job_id") == job["id"]
        and record.get("job_name") == job["name"]
        and record.get("matrix") == job["matrix"]
    )


def _find_record(
    snapshot: dict[str, Any], entry: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    matches = [record for record in snapshot["jobs"] if _entry_matches(record, entry)]
    if len(matches) > 1:
        return None, f"ambiguous duplicate job mapping for {entry['id']}"
    if not matches:
        return None, None
    return matches[0], None


def _record_summary(record: dict[str, Any], *, carried: bool = False) -> dict[str, Any]:
    return {
        "job_id": record.get("job_id"),
        "job_name": record.get("job_name"),
        "workflow_file": record.get("workflow_file"),
        "workflow_job_id": record.get("workflow_job_id"),
        "matrix": record.get("matrix"),
        "conclusion": record.get("conclusion"),
        "status": record.get("status"),
        "attempt": record.get("execution_attempt"),
        "url": record.get("url"),
        "carried_forward": carried,
    }


_evidence_path = Path(__file__).with_name("_release_qualification_evidence.py")
_evidence_loader = SourceFileLoader(
    "release_qualification_evidence_tool", str(_evidence_path)
)
_evidence_spec = importlib.util.spec_from_file_location(
    "release_qualification_evidence_tool",
    _evidence_path,
    loader=_evidence_loader,
)
if _evidence_spec is None or _evidence_spec.loader is None:
    raise RuntimeError(
        f"cannot load qualification evidence validators at {_evidence_path}"
    )
_evidence = importlib.util.module_from_spec(_evidence_spec)
sys.modules[_evidence_spec.name] = _evidence
_evidence_spec.loader.exec_module(_evidence)
_valid_pytest_evidence = _evidence._valid_pytest_evidence
_valid_command_evidence = _evidence._valid_command_evidence


def _evaluate_record(
    entry: dict[str, Any],
    record: dict[str, Any] | None,
    *,
    manifest: dict[str, Any],
    digest: str,
    workflow_run_id: int,
    duplicate_error: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    job_name = entry["job"]["name"]
    if duplicate_error:
        return None, _failure(job_name, "harness", duplicate_error)
    if record is None:
        return None, _failure(job_name, "missing", "required blocking job is absent")
    if record.get("workflow_run_id") != workflow_run_id:
        return _record_summary(record), _failure(
            job_name,
            "harness",
            f"workflow_run_id mismatch: expected {workflow_run_id}, "
            f"got {record.get('workflow_run_id')!r}",
        )
    reporting_steps = entry["required_reporting_steps"]
    for step_name in reporting_steps:
        matching_steps = [
            step
            for step in record["steps"]
            if isinstance(step, dict) and step.get("name") == step_name
        ]
        if not matching_steps:
            return _record_summary(record), _failure(
                job_name,
                "missing",
                f"required reporting step {step_name!r} is absent",
            )
        if len(matching_steps) != 1:
            return _record_summary(record), _failure(
                job_name,
                "harness",
                f"required reporting step {step_name!r} is ambiguous",
            )
        step = matching_steps[0]
        if step.get("status") != "completed" or step.get("conclusion") != "success":
            return _record_summary(record), _failure(
                job_name,
                "harness",
                f"required reporting step {step_name!r} concluded "
                f"{step.get('conclusion')!r} with status {step.get('status')!r}",
            )
    if record.get("evidence_error"):
        error_class = record.get("evidence_error_class", "harness")
        return _record_summary(record), _failure(
            job_name, error_class, str(record["evidence_error"])
        )
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return _record_summary(record), _failure(
            job_name,
            "missing",
            "required evidence upload is missing",
        )
    if entry["evidence_kind"] == "pytest":
        failure_class, diagnostics, node_ids = _valid_pytest_evidence(
            evidence,
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
            record=record,
        )
    else:
        failure_class, diagnostics = _valid_command_evidence(
            evidence,
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
            record=record,
        )
        node_ids = []
    summary = _record_summary(record)
    # Preserve the typed payload in every qualification observation. This lets
    # later evaluation recheck the result after the Actions artifact expires.
    summary["evidence"] = evidence
    if failure_class is None:
        if record["status"] != "completed" or record["conclusion"] != "success":
            return summary, _failure(
                job_name,
                "missing",
                f"job is {record['status']}/{record['conclusion']}; success is required",
            )
        return summary, None
    return summary, _failure(
        job_name,
        failure_class,
        *diagnostics,
        first_failing_node_ids=node_ids,
    )


def _record_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left == right


def _check_history(
    entry: dict[str, Any], snapshots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for index, snapshot in enumerate(snapshots):
        record, duplicate = _find_record(snapshot, entry)
        if duplicate:
            problems.append(_failure(entry["job"]["name"], "harness", duplicate))
            previous = record
            continue
        if record is None:
            previous = None
            continue
        attempt = snapshot["attempt"]
        execution_attempt = record["execution_attempt"]
        if index == 0 and execution_attempt != 1:
            problems.append(
                _failure(
                    entry["job"]["name"],
                    "harness",
                    "first job history record must come from attempt 1",
                )
            )
        if index > 0:
            if previous is None:
                if execution_attempt < attempt:
                    problems.append(
                        _failure(
                            entry["job"]["name"],
                            "harness",
                            "carried-forward success has no preceding authoritative job record",
                        )
                    )
            elif execution_attempt < attempt:
                if (
                    previous.get("execution_attempt") != execution_attempt
                    or previous.get("status") != "completed"
                    or previous.get("conclusion") != "success"
                    or not _record_equal(previous, record)
                ):
                    problems.append(
                        _failure(
                            entry["job"]["name"],
                            "harness",
                            "carried-forward job is not the same unchanged successful execution",
                        )
                    )
            elif execution_attempt == attempt:
                if previous.get("conclusion") == "success":
                    problems.append(
                        _failure(
                            entry["job"]["name"],
                            "harness",
                            "successful blocker was rerun; only failed-job reruns are accepted",
                        )
                    )
            else:
                problems.append(
                    _failure(
                        entry["job"]["name"],
                        "harness",
                        "job history skips or misstates an execution attempt",
                    )
                )
        previous = record
    return problems


def _evaluate_snapshot(
    snapshot: dict[str, Any],
    entries: list[dict[str, Any]],
    advisories: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    digest: str,
    workflow_run_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    job_summaries: list[dict[str, Any]] = []
    for entry in entries:
        record, duplicate = _find_record(snapshot, entry)
        summary, failure = _evaluate_record(
            entry,
            record,
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
            duplicate_error=duplicate,
        )
        if summary is not None:
            summary["check_id"] = entry["id"]
            summary["attempt"] = record["execution_attempt"]
            summary["carried_forward"] = (
                record["execution_attempt"] < snapshot["attempt"]
            )
            job_summaries.append(summary)
        if failure is not None:
            failures.append(failure)
    advisory_summaries: list[dict[str, Any]] = []
    for entry in advisories:
        record, duplicate = _find_record(snapshot, entry)
        if record is None:
            advisory_summaries.append(
                {
                    "check_id": entry["id"],
                    "job_name": entry["job"]["name"],
                    "status": "missing",
                    "conclusion": None,
                    "attempt": None,
                    "url": None,
                    "diagnostic": duplicate or "advisory job is absent",
                }
            )
            continue
        healthy = record["status"] == "completed" and record["conclusion"] == "success"
        advisory_summaries.append(
            {
                "check_id": entry["id"],
                "job_id": record["job_id"],
                "job_name": record["job_name"],
                "status": record["status"],
                "conclusion": record["conclusion"],
                "attempt": record["execution_attempt"],
                "url": record["url"],
                "diagnostic": ""
                if healthy and not duplicate
                else duplicate or "advisory job did not pass",
            }
        )
    return failures, job_summaries + [{"_advisory": advisory_summaries}]


def evaluate_qualification(
    manifest: dict[str, Any],
    inventory_bytes: bytes,
    job_bundle: dict[str, Any] | None,
    *,
    job_bundle_error: str = "",
    inventory_error: str = "",
    expected_workflow_run_id: int | None = None,
    expected_attempt: int | None = None,
) -> dict[str, Any]:
    """Return a typed candidate-bound qualification verdict; malformed inputs go red."""
    digest = inventory_digest(inventory_bytes)
    workflow_run_id: int | None = None
    current_attempt: int | None = None
    # Fact-collection or parse failures keep the caller's authoritative
    # run/attempt identity so the generated red observation revalidates as
    # typed QUALIFY_RED instead of a provenance disagreement. Histories that
    # contradict the expected identity still refuse below.
    if inventory_error:
        return _report(
            manifest=manifest,
            digest=digest,
            workflow_run_id=expected_workflow_run_id,
            current_attempt=expected_attempt,
            failures=[_failure("qualification", "missing", inventory_error)],
            input_error=inventory_error,
        )
    try:
        inventory = load_inventory(inventory_bytes)
    except QualificationInputError as exc:
        return _report(
            manifest=manifest,
            digest=digest,
            workflow_run_id=expected_workflow_run_id,
            current_attempt=expected_attempt,
            failures=[_failure("qualification", "harness", str(exc))],
            input_error=str(exc),
        )
    if job_bundle_error:
        return _report(
            manifest=manifest,
            digest=digest,
            workflow_run_id=expected_workflow_run_id,
            current_attempt=expected_attempt,
            failures=[_failure("qualification", "harness", job_bundle_error)],
            input_error=job_bundle_error,
        )
    try:
        if job_bundle is None:
            raise QualificationInputError("job history is missing")
        workflow_run_id, current_attempt, snapshots = _bundle_shape(job_bundle)
    except QualificationInputError as exc:
        return _report(
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
            current_attempt=current_attempt,
            failures=[_failure("qualification", "harness", str(exc))],
            input_error=str(exc),
        )

    if (
        expected_workflow_run_id is not None
        and workflow_run_id != expected_workflow_run_id
    ):
        diagnostic = (
            f"workflow_run_id mismatch: expected {expected_workflow_run_id}, "
            f"got {workflow_run_id}"
        )
        return _report(
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
            current_attempt=current_attempt,
            failures=[_failure("qualification", "harness", diagnostic)],
            input_error=diagnostic,
        )
    if expected_attempt is not None and current_attempt != expected_attempt:
        diagnostic = (
            f"attempt mismatch: expected {expected_attempt}, got {current_attempt}"
        )
        return _report(
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
            current_attempt=current_attempt,
            failures=[_failure("qualification", "harness", diagnostic)],
            input_error=diagnostic,
        )

    identity_errors = _identity_errors(manifest, job_bundle, digest)
    if identity_errors:
        return _report(
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
            current_attempt=current_attempt,
            failures=[_failure("qualification", "harness", *identity_errors)],
            input_error="job history identity does not match candidate or inventory",
        )

    entries = [
        entry
        for entry in inventory["checks"]
        if entry["disposition"] == "blocking"
        and entry["evidence_kind"] in {"pytest", "command"}
    ]
    advisories = [
        entry for entry in inventory["checks"] if entry["disposition"] == "advisory"
    ]
    history_failures: list[dict[str, Any]] = []
    for entry in entries:
        history_failures.extend(_check_history(entry, snapshots))

    attempt_results: list[dict[str, Any]] = []
    current_failures: list[dict[str, Any]] = []
    current_advisories: list[dict[str, Any]] = []
    for snapshot in snapshots:
        failures, summary_rows = _evaluate_snapshot(
            snapshot,
            entries,
            advisories,
            manifest=manifest,
            digest=digest,
            workflow_run_id=workflow_run_id,
        )
        advisory_row = next(
            (row["_advisory"] for row in summary_rows if "_advisory" in row), []
        )
        jobs = [row for row in summary_rows if "_advisory" not in row]
        attempt_results.append(
            {
                "attempt": snapshot["attempt"],
                "verdict": "pass" if not failures else "red",
                "failures": failures,
                "jobs": jobs,
                "advisories": advisory_row,
            }
        )
        if snapshot["attempt"] == current_attempt:
            current_failures = failures
            current_advisories = advisory_row

    failures = [*history_failures, *current_failures]
    if current_attempt == 2:
        first = attempt_results[0]["failures"]
        if not first or any(item["failure_class"] != "tests" for item in first):
            failures.append(
                _failure(
                    "qualification",
                    "harness",
                    "second attempt is not authorized by a first attempt containing only test failures",
                )
            )
    report = _report(
        manifest=manifest,
        digest=digest,
        workflow_run_id=workflow_run_id,
        current_attempt=current_attempt,
        failures=failures,
        advisories=current_advisories,
        attempt_results=attempt_results,
    )
    return report


def make_observation_payload(
    manifest: dict[str, Any],
    inventory_bytes: bytes,
    job_bundle: dict[str, Any] | None,
    *,
    job_bundle_error: str = "",
    inventory_error: str = "",
    expected_workflow_run_id: int | None = None,
    expected_attempt: int | None = None,
) -> dict[str, Any]:
    """Package immutable policy bytes and normalized job payload for an observation."""
    return {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "inventory_bytes_base64": base64.b64encode(inventory_bytes).decode("ascii"),
        "inventory_sha256": inventory_digest(inventory_bytes),
        "job_bundle": job_bundle,
        "job_bundle_error": job_bundle_error or None,
        "inventory_error": inventory_error or None,
        "expected_workflow_run_id": expected_workflow_run_id,
        "expected_attempt": expected_attempt,
        "result": evaluate_qualification(
            manifest,
            inventory_bytes,
            job_bundle,
            job_bundle_error=job_bundle_error,
            inventory_error=inventory_error,
            expected_workflow_run_id=expected_workflow_run_id,
            expected_attempt=expected_attempt,
        ),
    }


def verify_observation_payload(
    manifest: dict[str, Any], payload: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Recompute a stored result from its archived inventory and evidence payload."""
    if not isinstance(payload, dict):
        return None, "qualification observation details are missing"
    required = {
        "schema_version",
        "inventory_bytes_base64",
        "inventory_sha256",
        "job_bundle",
        "job_bundle_error",
        "inventory_error",
        "expected_workflow_run_id",
        "expected_attempt",
        "result",
    }
    try:
        _require_keys(payload, required, required, where="qualification observation")
    except QualificationInputError as exc:
        return None, str(exc)
    if payload["schema_version"] != QUALIFICATION_SCHEMA_VERSION:
        return None, "unknown qualification observation schema"
    encoded = payload["inventory_bytes_base64"]
    if not isinstance(encoded, str):
        return None, "qualification observation inventory bytes are missing"
    try:
        inventory_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        return None, "qualification observation inventory bytes are unreadable"
    digest = inventory_digest(inventory_bytes)
    if digest != payload["inventory_sha256"]:
        return None, "qualification observation inventory digest mismatch"
    error = payload["job_bundle_error"]
    if error is not None and not isinstance(error, str):
        return None, "qualification observation job_bundle_error is malformed"
    inventory_error = payload["inventory_error"]
    if inventory_error is not None and not isinstance(inventory_error, str):
        return None, "qualification observation inventory_error is malformed"
    expected_run_id = payload["expected_workflow_run_id"]
    expected_attempt = payload["expected_attempt"]
    if expected_run_id is not None and not _is_int(expected_run_id):
        return None, "qualification observation expected workflow_run_id is malformed"
    if expected_attempt is not None and not _is_int(expected_attempt):
        return None, "qualification observation expected attempt is malformed"
    computed = evaluate_qualification(
        manifest,
        inventory_bytes,
        payload["job_bundle"],
        job_bundle_error=error or "",
        inventory_error=inventory_error or "",
        expected_workflow_run_id=expected_run_id,
        expected_attempt=expected_attempt,
    )
    if payload["result"] != computed:
        return None, "stored qualification verdict does not match its evidence payload"
    return computed, None


def qualify_failure_summary(report: dict[str, Any]) -> str:
    """Render a compact stable red token for CLI and observation consumers."""
    failures = report.get("failures", [])
    if not failures:
        return "QUALIFY_RED(qualification): verdict is red without a typed failure"
    labels = []
    for failure in failures:
        job = failure.get("job", "qualification")
        kind = failure.get("failure_class", "harness")
        labels.append(f"{job}:{kind}")
    return "QUALIFY_RED(" + ", ".join(labels) + ")"

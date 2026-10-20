#!/usr/bin/env python3
"""Load the N1 policy and evaluate candidate-bound qualification evidence.

This module is shared by ``release_candidate`` and later release reporting tools.
It deliberately performs no network reads: GitHub's attempt-aware job reader
normalizes API responses, and this module validates those records against the
sealed candidate and the exact inventory bytes used for that run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


INVENTORY_SCHEMA_VERSION = 1
JOB_BUNDLE_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
QUALIFICATION_SCHEMA_VERSION = 1

FAILURE_CLASSES = frozenset({"tests", "collection", "zero", "harness", "missing"})
PYTEST_COUNT_FIELDS = frozenset({"collected", "passed", "failed", "errors", "skipped"})
BINDING_FIELDS = (
    "repository",
    "candidate_id",
    "generation",
    "checked_out_sha",
    "expected_core_version",
    "installed_core_version",
    "inventory_digest",
    "workflow_run_id",
    "job_id",
    "job_name",
    "attempt",
)


class QualificationInputError(ValueError):
    """Malformed policy or evidence that must be reported as qualification red."""


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationInputError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def strict_json_loads(raw: bytes, *, source: str) -> Any:
    """Decode UTF-8 JSON while rejecting duplicate object keys."""
    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=_pairs_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationInputError(f"{source} is unreadable JSON: {exc}") from exc


def inventory_digest(raw: bytes) -> str:
    """Hash the exact inventory bytes, including whitespace and line endings."""
    return hashlib.sha256(raw).hexdigest()


def _require_keys(
    value: dict[str, Any], required: set[str], allowed: set[str], *, where: str
) -> None:
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing:
        raise QualificationInputError(f"{where} misses fields {missing}")
    if unknown:
        raise QualificationInputError(f"{where} has unknown fields {unknown}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_mapping_key(entry: dict[str, Any]) -> str:
    job = entry["job"]
    return json.dumps(
        [entry["workflow"], job["id"], job["matrix"]],
        sort_keys=True,
        separators=(",", ":"),
    )


def load_inventory(raw: bytes) -> dict[str, Any]:
    """Parse and strictly validate one versioned N1 inventory."""
    inventory = strict_json_loads(raw, source="qualification inventory")
    if not isinstance(inventory, dict):
        raise QualificationInputError("qualification inventory root must be an object")
    _require_keys(
        inventory,
        {"schema_version", "admission_policy", "checks"},
        {"schema_version", "admission_policy", "checks"},
        where="qualification inventory",
    )
    if inventory["schema_version"] != INVENTORY_SCHEMA_VERSION:
        raise QualificationInputError(
            "unknown qualification inventory schema_version "
            f"{inventory['schema_version']!r}; expected {INVENTORY_SCHEMA_VERSION}"
        )

    policy = inventory["admission_policy"]
    if not isinstance(policy, dict):
        raise QualificationInputError("admission_policy must be an object")
    _require_keys(
        policy,
        {"id", "workflow", "classification", "evidence_kind"},
        {"id", "workflow", "classification", "evidence_kind"},
        where="admission_policy",
    )
    if (
        policy["id"] != "master-gate"
        or policy["classification"] != "admission"
        or policy["evidence_kind"] != "admission_policy"
        or not isinstance(policy["workflow"], str)
        or not policy["workflow"].startswith(".github/workflows/")
    ):
        raise QualificationInputError(
            "admission_policy must identify the existing Master Gate policy "
            "without expanding its job list"
        )

    checks = inventory["checks"]
    if not isinstance(checks, list):
        raise QualificationInputError("inventory checks must be a list")
    if not checks:
        raise QualificationInputError("inventory has no release checks")

    ids: set[str] = set()
    mappings: set[str] = set()
    blocking: list[dict[str, Any]] = []
    qualification: list[dict[str, Any]] = []
    exercises: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(checks):
        where = f"checks[{index}]"
        if not isinstance(raw_entry, dict):
            raise QualificationInputError(f"{where} must be an object")
        if "required_legs" in raw_entry:
            allowed = {
                "id",
                "workflow",
                "job",
                "classification",
                "disposition",
                "evidence_kind",
                "required_legs",
                "required_reporting_steps",
            }
        else:
            allowed = {
                "id",
                "workflow",
                "job",
                "classification",
                "disposition",
                "evidence_kind",
                "required_reporting_steps",
            }
        _require_keys(
            raw_entry,
            {"id", "workflow", "job", "classification", "disposition", "evidence_kind"},
            allowed,
            where=where,
        )
        entry = raw_entry
        if not isinstance(entry["id"], str) or not entry["id"].strip():
            raise QualificationInputError(f"{where}.id must be a non-empty string")
        if entry["id"] in ids:
            raise QualificationInputError(
                f"duplicate inventory check id {entry['id']!r}"
            )
        ids.add(entry["id"])
        if (
            not isinstance(entry["workflow"], str)
            or not entry["workflow"].startswith(".github/workflows/")
            or not entry["workflow"].endswith((".yml", ".yaml"))
        ):
            raise QualificationInputError(
                f"{where}.workflow must map to a checked-in workflow file"
            )
        job = entry["job"]
        if not isinstance(job, dict):
            raise QualificationInputError(f"{where}.job must be an object")
        _require_keys(
            job,
            {"id", "name", "matrix"},
            {"id", "name", "matrix"},
            where=f"{where}.job",
        )
        if (
            not isinstance(job["id"], str)
            or not job["id"].strip()
            or not isinstance(job["name"], str)
            or not job["name"].strip()
            or not isinstance(job["matrix"], dict)
            or not all(isinstance(key, str) for key in job["matrix"])
        ):
            raise QualificationInputError(f"{where}.job has an invalid mapping")
        mapping = _check_mapping_key(entry)
        if mapping in mappings:
            raise QualificationInputError(
                f"duplicate or conflicting workflow/job mapping at {where}: {mapping}"
            )
        mappings.add(mapping)
        if entry["classification"] != "release":
            raise QualificationInputError(
                f"{where}.classification must be 'release'; admission policy is separate"
            )
        disposition = entry["disposition"]
        evidence_kind = entry["evidence_kind"]
        if disposition not in {"blocking", "advisory"}:
            raise QualificationInputError(f"{where}.disposition is unknown")
        if evidence_kind not in {"pytest", "command", "exercise", "job"}:
            raise QualificationInputError(f"{where}.evidence_kind is unknown")
        if disposition == "blocking":
            blocking.append(entry)
            if evidence_kind in {"pytest", "command"}:
                reporting_steps = entry.get("required_reporting_steps")
                if (
                    not isinstance(reporting_steps, list)
                    or not reporting_steps
                    or not all(
                        isinstance(step, str) and step for step in reporting_steps
                    )
                    or len(set(reporting_steps)) != len(reporting_steps)
                ):
                    raise QualificationInputError(
                        f"blocking check {entry['id']!r} has unmapped reporting evidence"
                    )
                qualification.append(entry)
            elif evidence_kind == "exercise":
                if "required_reporting_steps" in entry:
                    raise QualificationInputError(
                        f"exercise check {entry['id']!r} cannot map CI reporting steps"
                    )
                exercises.append(entry)
            else:
                raise QualificationInputError(
                    f"blocking check {entry['id']!r} has unmapped required evidence"
                )
        elif evidence_kind != "job":
            raise QualificationInputError(
                f"advisory check {entry['id']!r} must use job evidence"
            )

    if not blocking:
        raise QualificationInputError(
            "inventory has an empty blocking release inventory"
        )
    if not qualification:
        raise QualificationInputError(
            "inventory has no mapped blocking qualification evidence"
        )
    expected_legs = [
        {"os": "ubuntu-latest", "artifact": "wheel"},
        {"os": "ubuntu-latest", "artifact": "sdist"},
        {"os": "macos-latest", "artifact": "wheel"},
        {"os": "macos-latest", "artifact": "sdist"},
    ]
    if len(exercises) != 1 or exercises[0].get("required_legs") != expected_legs:
        raise QualificationInputError(
            "inventory must map the existing four Linux/macOS wheel/sdist exercise legs"
        )
    return inventory


def load_inventory_file(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Read and validate inventory bytes, returning both bytes and parsed policy."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QualificationInputError(f"cannot read inventory {path}: {exc}") from exc
    return raw, load_inventory(raw)


def load_job_bundle_file(path: Path, evidence_dir: Path) -> dict[str, Any]:
    """Load normalized Actions job history and inline each referenced evidence file."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QualificationInputError(f"cannot read job history {path}: {exc}") from exc
    bundle = strict_json_loads(raw, source=f"job history {path}")
    if not isinstance(bundle, dict):
        raise QualificationInputError("job history root must be an object")
    root = evidence_dir.resolve()
    attempts = bundle.get("attempts")
    if not isinstance(attempts, list):
        return bundle
    for attempt_row in attempts:
        if not isinstance(attempt_row, dict) or not isinstance(
            attempt_row.get("jobs"), list
        ):
            continue
        for record in attempt_row["jobs"]:
            if not isinstance(record, dict) or "evidence_file" not in record:
                continue
            relative = record["evidence_file"]
            if not isinstance(relative, str) or not relative:
                record["evidence_error"] = "evidence_file must be a relative path"
                record["evidence_error_class"] = "harness"
                continue
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                record["evidence_error"] = (
                    "evidence_file escapes its artifact directory"
                )
                record["evidence_error_class"] = "harness"
                continue
            evidence_path = (root / relative_path).resolve()
            if not evidence_path.is_relative_to(root):
                record["evidence_error"] = (
                    "evidence_file escapes its artifact directory"
                )
                record["evidence_error_class"] = "harness"
                continue
            try:
                evidence_raw = evidence_path.read_bytes()
            except OSError as exc:
                record["evidence_error"] = (
                    f"evidence upload is missing or unreadable: {exc}"
                )
                record["evidence_error_class"] = "missing"
                continue
            try:
                record["evidence"] = strict_json_loads(
                    evidence_raw, source=f"evidence {relative}"
                )
            except QualificationInputError as exc:
                record["evidence_error"] = str(exc)
                record["evidence_error_class"] = "harness"
    return bundle

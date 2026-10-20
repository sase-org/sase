#!/usr/bin/env python3
"""Validate the typed pytest and command evidence payloads."""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any


_inventory_path = Path(__file__).with_name("_release_qualification_inventory.py")
_inventory_loader = SourceFileLoader(
    "release_qualification_evidence_inventory_tool", str(_inventory_path)
)
_inventory_spec = importlib.util.spec_from_file_location(
    "release_qualification_evidence_inventory_tool",
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

BINDING_FIELDS = _inventory.BINDING_FIELDS
EVIDENCE_SCHEMA_VERSION = _inventory.EVIDENCE_SCHEMA_VERSION
PYTEST_COUNT_FIELDS = _inventory.PYTEST_COUNT_FIELDS
QualificationInputError = _inventory.QualificationInputError
_is_int = _inventory._is_int
_require_keys = _inventory._require_keys


def _binding_diagnostics(
    evidence: dict[str, Any],
    *,
    manifest: dict[str, Any],
    digest: str,
    workflow_run_id: int,
    record: dict[str, Any],
) -> list[str]:
    binding = evidence.get("binding")
    if not isinstance(binding, dict):
        return ["evidence binding is missing or is not an object"]
    expected = {
        "repository": manifest.get("repository"),
        "candidate_id": manifest.get("candidate_id"),
        "generation": manifest.get("generation"),
        "checked_out_sha": manifest.get("sha"),
        "expected_core_version": manifest.get("core_version"),
        "installed_core_version": manifest.get("core_version"),
        "inventory_digest": digest,
        "workflow_run_id": workflow_run_id,
        "job_id": record.get("job_id"),
        "job_name": record.get("job_name"),
        "attempt": record.get("execution_attempt"),
    }
    problems: list[str] = []
    for field in BINDING_FIELDS:
        if binding.get(field) != expected[field]:
            problems.append(
                f"binding {field} mismatch: expected {expected[field]!r}, "
                f"got {binding.get(field)!r}"
            )
    unknown = sorted(binding.keys() - set(BINDING_FIELDS))
    if unknown:
        problems.append(f"binding has unknown fields {unknown}")
    missing = sorted(set(BINDING_FIELDS) - binding.keys())
    if missing:
        problems.append(f"binding misses fields {missing}")
    return problems


def _valid_pytest_evidence(
    evidence: dict[str, Any],
    *,
    manifest: dict[str, Any],
    digest: str,
    workflow_run_id: int,
    record: dict[str, Any],
) -> tuple[str | None, list[str], list[str]]:
    required = {
        "schema_version",
        "kind",
        "binding",
        "collected",
        "passed",
        "failed",
        "errors",
        "skipped",
        "collection_failed",
        "exit_status",
        "first_failing_node_ids",
        "flaky_lines",
    }
    try:
        _require_keys(evidence, required, required, where="pytest evidence")
    except QualificationInputError as exc:
        return "harness", [str(exc)], []
    if (
        evidence["schema_version"] != EVIDENCE_SCHEMA_VERSION
        or evidence["kind"] != "pytest"
    ):
        return "harness", ["pytest evidence schema or kind is unknown"], []
    binding_problems = _binding_diagnostics(
        evidence,
        manifest=manifest,
        digest=digest,
        workflow_run_id=workflow_run_id,
        record=record,
    )
    if binding_problems:
        return "harness", binding_problems, []
    counts = [
        evidence.get(field)
        for field in ("collected", "passed", "failed", "errors", "skipped")
    ]
    if not all(_is_int(count) and count >= 0 for count in counts):
        return "harness", ["pytest counts must be non-negative integers"], []
    if not isinstance(evidence["collection_failed"], bool):
        return "harness", ["collection_failed must be boolean"], []
    if not _is_int(evidence["exit_status"]):
        return "harness", ["pytest exit_status must be an integer"], []
    node_ids = evidence["first_failing_node_ids"]
    flaky_lines = evidence["flaky_lines"]
    if not isinstance(node_ids, list) or not all(
        isinstance(node, str) for node in node_ids
    ):
        return "harness", ["first_failing_node_ids must be a list of strings"], []
    if not isinstance(flaky_lines, list) or not all(
        isinstance(line, str) and line.startswith("FLAKY:") for line in flaky_lines
    ):
        return "harness", ["flaky_lines must contain verbatim FLAKY: lines"], []
    if evidence["collection_failed"]:
        return "collection", ["pytest collection reported an error"], node_ids
    if evidence["collected"] == 0:
        return "zero", ["pytest collected zero tests"], node_ids
    if sum(counts[1:]) != evidence["collected"]:
        return (
            "harness",
            ["pytest outcome counts do not equal collected count"],
            node_ids,
        )
    failed = evidence["failed"] + evidence["errors"]
    if failed:
        if record["status"] != "completed" or record["conclusion"] in {
            "cancelled",
            "timed_out",
            "skipped",
        }:
            return (
                "missing",
                ["job did not complete successfully with its pytest report"],
                node_ids,
            )
        return (
            "tests",
            [
                f"pytest reported {evidence['failed']} failed and {evidence['errors']} errors"
            ],
            node_ids,
        )
    if evidence["exit_status"] != 0:
        return (
            "harness",
            [f"pytest exited {evidence['exit_status']} without failed test outcomes"],
            node_ids,
        )
    if record["status"] != "completed" or record["conclusion"] != "success":
        failure_class = (
            "missing"
            if record["conclusion"] in {"cancelled", "timed_out", "skipped", None}
            or record["status"] != "completed"
            else "harness"
        )
        return (
            failure_class,
            [
                f"job conclusion is {record['conclusion']!r} despite a clean pytest report"
            ],
            node_ids,
        )
    return None, [], []


def _valid_command_evidence(
    evidence: dict[str, Any],
    *,
    manifest: dict[str, Any],
    digest: str,
    workflow_run_id: int,
    record: dict[str, Any],
) -> tuple[str | None, list[str]]:
    required = {
        "schema_version",
        "kind",
        "binding",
        "steps",
        "missing_bindings",
        "diagnostics",
    }
    try:
        _require_keys(evidence, required, required, where="command evidence")
    except QualificationInputError as exc:
        return "harness", [str(exc)]
    if (
        evidence["schema_version"] != EVIDENCE_SCHEMA_VERSION
        or evidence["kind"] != "command"
    ):
        return "harness", ["command evidence schema or kind is unknown"]
    count_fields = sorted(PYTEST_COUNT_FIELDS & evidence.keys())
    if count_fields:
        return "harness", [
            f"command evidence must not invent pytest counts {count_fields}"
        ]
    binding_problems = _binding_diagnostics(
        evidence,
        manifest=manifest,
        digest=digest,
        workflow_run_id=workflow_run_id,
        record=record,
    )
    if binding_problems:
        return "harness", binding_problems
    steps = evidence["steps"]
    missing_bindings = evidence["missing_bindings"]
    diagnostics = evidence["diagnostics"]
    if not isinstance(steps, list) or not steps:
        return "harness", ["command evidence has no completed step outcomes"]
    if not isinstance(missing_bindings, list) or not all(
        isinstance(item, str) for item in missing_bindings
    ):
        return "harness", ["missing_bindings must be a list of strings"]
    if not isinstance(diagnostics, list) or not all(
        isinstance(item, str) for item in diagnostics
    ):
        return "harness", ["command diagnostics must be a list of strings"]
    step_problems: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {
            "name",
            "status",
            "conclusion",
            "exit_status",
        }:
            step_problems.append(f"step {index} has malformed outcome fields")
            continue
        if not isinstance(step["name"], str) or not step["name"]:
            step_problems.append(f"step {index} has no name")
        if step["status"] != "completed":
            step_problems.append(f"step {step.get('name', index)!r} did not complete")
        if step["conclusion"] != "success" or step["exit_status"] != 0:
            step_problems.append(
                f"step {step.get('name', index)!r} concluded "
                f"{step.get('conclusion')!r} (exit {step.get('exit_status')!r})"
            )
    if missing_bindings:
        step_problems.append("missing bindings: " + ", ".join(missing_bindings))
    step_problems.extend(diagnostics)
    if record["status"] != "completed" or record["conclusion"] != "success":
        step_problems.append(f"job conclusion is {record['conclusion']!r}, not success")
    return ("harness", step_problems) if step_problems else (None, [])

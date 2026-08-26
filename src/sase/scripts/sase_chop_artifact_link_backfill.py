#!/usr/bin/env python3
"""Retroactive artifact-link derivation, outbox drain, and repair sweep.

An hourly housekeeping chop, since it may scan substantial local state. It
owns four bounded jobs per enabled project, each reporting what it did:

1. the retroactive derivation sweep over documents that predate the epic;
2. the read-outbox drain for agents that have since published;
3. the cross-workspace ``reconcile_aggregate()`` sweep;
4. the dangling-ref repair pass driven by git rename history.

Job 1 is resumable: a per-project checkpoint of already-swept refs persists
across ticks under a bounded per-tick time budget, so a long tail of
pre-existing documents converges over several hours without redoing already
-processed work, and logs how many documents remain for the next tick.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.sdd.artifact_link_backfill import (
    reconcile_and_repair_artifact_links,
    run_artifact_link_backfill_batch,
)
from sase.sdd.artifact_link_outbox import drain_artifact_link_outbox
from sase.sdd.artifact_link_store import resolve_artifact_link_store

_STATE_FILENAME = "artifact_link_backfill.json"
_STATE_SCHEMA_VERSION = 1
_CHOP = "artifact_link_backfill"
_SWEEP_BATCH_SIZE = 500
_WORKSPACE_HINT_ENV = (
    "SASE_GH_WORKSPACE_DIR",
    "SASE_ACTIVE_PROJECT_DIR",
    "SASE_SDD_DIR",
)
# Bounds only the sweep (job 1); the drain and reconcile/repair jobs already
# bound their own work and run for every project regardless of this budget.
_SWEEP_WORK_BUDGET_SECONDS = 45.0
# Bounds the whole chop, well under the axe-configured 300s timeout, so a
# slowdown degrades into a logged deferral instead of a silent SIGKILL.
_CHOP_WORK_BUDGET_SECONDS = 240.0


def _enabled_project_records() -> list[ProjectRecordWire]:
    records = [
        record
        for record in list_project_records(
            sase_projects_dir(),
            include_states=("enabled",),
            include_home=False,
            projects_only=True,
        )
        if record.is_project and record.workspace_dir
    ]
    return _prefer_current_workspace_record(records, cwd=Path.cwd())


def _prefer_current_workspace_record(
    records: list[ProjectRecordWire], *, cwd: Path
) -> list[ProjectRecordWire]:
    found = _current_workspace_marker(cwd)
    if found is None:
        return records
    workspace_root, marker = found
    project_refs = {
        str(value)
        for value in (marker.project_name, marker.project_key)
        if isinstance(value, str) and value
    }
    if not project_refs:
        return records
    preferred = str(Path(workspace_root).expanduser().resolve(strict=False))
    adjusted: list[ProjectRecordWire] = []
    for record in records:
        names = {
            record.project_name,
            *(record.aliases or ()),
        }
        if record.display_name:
            names.add(record.display_name)
        if project_refs & names:
            adjusted.append(replace(record, workspace_dir=preferred))
        else:
            adjusted.append(record)
    return adjusted


def _current_workspace_marker(cwd: Path) -> tuple[str, Any] | None:
    try:
        from sase.workspace_provider import find_marker_from_cwd
    except Exception:
        return None
    candidates = [
        Path(raw) for key in _WORKSPACE_HINT_ENV if (raw := os.environ.get(key))
    ]
    candidates.append(cwd)
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser().resolve(strict=False)
        if path in seen:
            continue
        seen.add(path)
        try:
            found = find_marker_from_cwd(str(path))
        except Exception:
            continue
        if found is not None:
            return found
    return None


def _read_state(path: Path) -> dict[str, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _STATE_SCHEMA_VERSION
    ):
        return {}
    swept = payload.get("swept")
    if not isinstance(swept, dict):
        return {}
    result: dict[str, list[str]] = {}
    for project_key, refs in swept.items():
        if isinstance(project_key, str) and isinstance(refs, list):
            result[project_key] = [ref for ref in refs if isinstance(ref, str)]
    return result


def _write_state(path: Path, swept: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": _STATE_SCHEMA_VERSION, "swept": swept}
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


@dataclass
class _Totals:
    projects: int = 0
    failed_projects: int = 0
    sweep_scanned: int = 0
    sweep_persisted: int = 0
    sweep_remaining: int = 0
    outbox_drained: int = 0
    outbox_dropped: int = 0
    reconciled: int = 0
    repaired_renames: int = 0
    deferred_projects: int = 0
    warnings: list[str] = field(default_factory=list)


def _log_project_done(
    runtime: BuiltinChopRuntime,
    project_key: str,
    elapsed: dict[str, float],
    started: float,
) -> None:
    jobs = ", ".join(f"{name}={value:.2f}s" for name, value in elapsed.items())
    total = time.monotonic() - started
    runtime.log.info(f"[{_CHOP}] {project_key}: done in {total:.2f}s ({jobs})")


def _run_project(
    project_key: str,
    workspace_dir: str,
    *,
    swept: dict[str, list[str]],
    totals: _Totals,
    deadline: float,
    chop_deadline: float,
    state_path: Path,
    runtime: BuiltinChopRuntime,
) -> None:
    started = time.monotonic()
    runtime.log.info(f"[{_CHOP}] {project_key}: starting")
    elapsed: dict[str, float] = {}
    try:
        store = resolve_artifact_link_store(cwd=Path(workspace_dir))
    except Exception as exc:  # noqa: BLE001 - one broken project cannot stall the rest.
        totals.failed_projects += 1
        totals.warnings.append(f"{project_key}: could not resolve link store: {exc}")
        return

    if time.monotonic() < deadline:
        sweep_started = time.monotonic()
        already_swept = frozenset(swept.get(project_key, ()))
        report, updated_swept = run_artifact_link_backfill_batch(
            store,
            already_swept=already_swept,
            batch_size=_SWEEP_BATCH_SIZE,
            deadline=deadline,
        )
        elapsed["sweep"] = time.monotonic() - sweep_started
        swept[project_key] = sorted(updated_swept)
        totals.sweep_scanned += report.scanned
        totals.sweep_persisted += report.persisted
        totals.sweep_remaining += report.remaining
        totals.warnings.extend(f"{project_key}: {error}" for error in report.errors)
        try:
            _write_state(state_path, swept)
        except Exception as exc:  # noqa: BLE001 - retry on the next tick.
            totals.warnings.append(f"failed to persist sweep checkpoint: {exc}")
        if report.remaining and time.monotonic() >= deadline:
            totals.warnings.append(
                f"{project_key}: deferred outbox/reconcile after sweep budget"
            )
            totals.projects += 1
            _log_project_done(runtime, project_key, elapsed, started)
            return

    if time.monotonic() >= chop_deadline:
        totals.deferred_projects += 1
        totals.warnings.append(
            f"{project_key}: deferred outbox drain and reconcile/repair past chop budget"
        )
        _log_project_done(runtime, project_key, elapsed, started)
        return

    drain_started = time.monotonic()
    try:
        outbox_report = drain_artifact_link_outbox(store=store)
        totals.outbox_drained += outbox_report.drained
        totals.outbox_dropped += outbox_report.dropped
    except Exception as exc:  # noqa: BLE001 - continue with the other jobs.
        totals.warnings.append(f"{project_key}: outbox drain failed: {exc}")
    elapsed["drain"] = time.monotonic() - drain_started

    if time.monotonic() >= chop_deadline:
        totals.deferred_projects += 1
        totals.warnings.append(
            f"{project_key}: deferred reconcile/repair past chop budget"
        )
        totals.projects += 1
        _log_project_done(runtime, project_key, elapsed, started)
        return

    reconcile_started = time.monotonic()
    try:
        reconcile_report = reconcile_and_repair_artifact_links(store)
        totals.reconciled += 1
        totals.repaired_renames += reconcile_report.repaired_renames
    except Exception as exc:  # noqa: BLE001 - continue with the other projects.
        totals.warnings.append(f"{project_key}: reconcile/repair failed: {exc}")
    elapsed["reconcile_repair"] = time.monotonic() - reconcile_started

    totals.projects += 1
    _log_project_done(runtime, project_key, elapsed, started)


@builtin_chop("artifact_link_backfill")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    records = _enabled_project_records()
    state_path = Path(runtime.context.state_dir) / _STATE_FILENAME
    swept = _read_state(state_path)
    live_keys = {record.project_name for record in records}
    for stale_key in set(swept) - live_keys:
        del swept[stale_key]

    totals = _Totals()
    deadline = time.monotonic() + _SWEEP_WORK_BUDGET_SECONDS
    chop_deadline = time.monotonic() + _CHOP_WORK_BUDGET_SECONDS
    for index, record in enumerate(records):
        assert record.workspace_dir is not None
        if time.monotonic() >= chop_deadline:
            deferred_names = [r.project_name for r in records[index:]]
            totals.deferred_projects += len(deferred_names)
            totals.warnings.append(
                "chop budget exceeded; projects not started: "
                + ", ".join(deferred_names)
            )
            break
        _run_project(
            record.project_name,
            record.workspace_dir,
            swept=swept,
            totals=totals,
            deadline=deadline,
            chop_deadline=chop_deadline,
            state_path=state_path,
            runtime=runtime,
        )

    try:
        _write_state(state_path, swept)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        totals.warnings.append(f"failed to persist sweep checkpoint: {exc}")

    for warning in totals.warnings:
        runtime.log.warning(f"[{_CHOP}] {warning}")
    if totals.sweep_remaining:
        runtime.log.info(
            f"[{_CHOP}] {totals.sweep_remaining} documents remain unswept; "
            "continuing on later ticks"
        )

    return runtime.emit_summary(
        {
            "projects": totals.projects,
            "failed_projects": totals.failed_projects,
            "sweep_scanned": totals.sweep_scanned,
            "sweep_persisted": totals.sweep_persisted,
            "sweep_remaining": totals.sweep_remaining,
            "outbox_drained": totals.outbox_drained,
            "outbox_dropped": totals.outbox_dropped,
            "reconciled": totals.reconciled,
            "repaired_renames": totals.repaired_renames,
            "deferred_projects": totals.deferred_projects,
        },
        reason="no_enabled_projects" if totals.projects == 0 else None,
    )


def main() -> None:
    run_builtin_chop("artifact_link_backfill")


if __name__ == "__main__":
    main()

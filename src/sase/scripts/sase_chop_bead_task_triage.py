#!/usr/bin/env python3
"""Raise and reconcile triage gates for ready task beads."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sase.bead.model import Issue, IssueType, Status
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.bead.task_gate import TASK_TRIAGE_KIND, create_task_triage_gate
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import bead_read_facade as rust_beads
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.notification_gates.durability import file_lock
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.poller import poll_gate

_STATE_SCHEMA_VERSION = 1
# Bump when pending task-triage gates need a presentation refresh.
_PRESENTATION_CONTRACT = 2
_STATE_FILENAME = "bead_task_triage.json"
_LOCK_FILENAME = "bead_task_triage.lock"

_GateState = Literal["pending", "terminal", "missing"]


@dataclass
class _ProjectState:
    gates: dict[str, str] = field(default_factory=dict)
    generations: dict[str, int] = field(default_factory=dict)
    contracts: dict[str, int] = field(default_factory=dict)


def _read_state(path: Path) -> dict[str, _ProjectState]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_projects = payload.get("projects")
    if not isinstance(raw_projects, dict):
        return {}

    projects: dict[str, _ProjectState] = {}
    for project_name, raw_project in raw_projects.items():
        if not isinstance(project_name, str) or not isinstance(raw_project, dict):
            continue
        raw_gates = raw_project.get("gates")
        raw_generations = raw_project.get("generations")
        raw_contracts = raw_project.get("contracts")
        gates = (
            {
                bead_id: request_id
                for bead_id, request_id in raw_gates.items()
                if isinstance(bead_id, str) and isinstance(request_id, str)
            }
            if isinstance(raw_gates, dict)
            else {}
        )
        generations = (
            {
                bead_id: generation
                for bead_id, generation in raw_generations.items()
                if isinstance(bead_id, str)
                and isinstance(generation, int)
                and not isinstance(generation, bool)
                and generation >= 1
            }
            if isinstance(raw_generations, dict)
            else {}
        )
        contracts: dict[str, int] = {}
        for bead_id in gates:
            contract = (
                raw_contracts.get(bead_id, 1) if isinstance(raw_contracts, dict) else 1
            )
            contracts[bead_id] = (
                contract
                if isinstance(contract, int)
                and not isinstance(contract, bool)
                and contract >= 1
                else 1
            )
        if gates or generations or contracts:
            projects[project_name] = _ProjectState(
                gates=gates,
                generations=generations,
                contracts=contracts,
            )
    return projects


def _write_state(path: Path, projects: dict[str, _ProjectState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _STATE_SCHEMA_VERSION,
        "projects": {
            project_name: {
                "gates": dict(sorted(project.gates.items())),
                "generations": dict(sorted(project.generations.items())),
                "contracts": dict(sorted(project.contracts.items())),
            }
            for project_name, project in sorted(projects.items())
            if project.gates or project.generations or project.contracts
        },
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _enabled_project_stores(log: ChopLogger) -> list[tuple[str, Path]]:
    records = list_project_records(
        sase_projects_dir(),
        "enabled",
        include_home=False,
        projects_only=True,
    )
    stores: list[tuple[str, Path]] = []
    for record in records:
        if (
            not record.is_project
            or record.state != "enabled"
            or record.system_managed
            or record.project_name == "home"
        ):
            continue
        try:
            beads_dir = canonical_beads_dir_for_project(record.project_name)
        except Exception as exc:  # noqa: BLE001 - continue with healthy projects.
            log.warning(
                f"[bead_task_triage] Failed to locate bead store for "
                f"{record.project_name}: {exc}"
            )
            continue
        if beads_dir is None:
            continue
        stores.append((record.project_name, beads_dir))
    return stores


def _ready_tasks(beads_dir: Path) -> list[Issue]:
    return rust_beads.list_issues(
        beads_dir,
        statuses=[Status.READY],
        issue_types=[IssueType.TASK],
    )


def _request_id(project_name: str, bead_id: str, generation: int) -> str:
    identity = f"{project_name}\0{bead_id}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:12]
    bead_component = bead_id[:80]
    return f"bead-task-triage-{bead_component}-{digest}-g{generation}"


def _gate_state(request_id: str) -> _GateState:
    paths = bundle_paths(TASK_TRIAGE_KIND, request_id)
    if not paths.request.is_file():
        return "missing"
    return "pending" if poll_gate(paths.root) is None else "terminal"


def _cancel_pending_gate(
    request_id: str,
    *,
    reason: str = "task_bead_no_longer_ready",
) -> bool:
    paths = bundle_paths(TASK_TRIAGE_KIND, request_id)
    try:
        cancel_gate(
            paths.root,
            reason=reason,
            source="bead_task_triage",
        )
    except GateError as exc:
        if exc.code == "already_answered":
            return False
        raise
    return True


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "gated": gated,
            "canceled": canceled,
            "skipped": skipped,
        },
        reason=reason,
    )


def _reconcile(runtime: BuiltinChopRuntime, state_path: Path) -> ChopResultBuilder:
    if runtime.context.dry_run:
        return _summary(runtime, reason="dry_run")

    projects = _read_state(state_path)
    try:
        project_stores = _enabled_project_stores(runtime.log)
    except Exception as exc:  # noqa: BLE001 - a bad inventory must fail closed.
        runtime.log.warning(
            f"[bead_task_triage] Failed to load enabled projects: {exc}"
        )
        return _summary(runtime, reason="project_inventory_unavailable")

    gated = 0
    canceled = 0
    skipped = 0
    state_changed = False
    for project_name, beads_dir in project_stores:
        try:
            ready_tasks = {issue.id: issue for issue in _ready_tasks(beads_dir)}
        except Exception as exc:  # noqa: BLE001 - one store must not stop the chop.
            runtime.log.warning(
                f"[bead_task_triage] Failed to read ready tasks for "
                f"{project_name}: {exc}"
            )
            continue

        project_state = projects.setdefault(project_name, _ProjectState())
        for bead_id, request_id in list(project_state.gates.items()):
            try:
                gate_state = _gate_state(request_id)
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                runtime.log.warning(
                    f"[bead_task_triage] Failed to inspect gate {request_id}: {exc}"
                )
                ready_tasks.pop(bead_id, None)
                continue

            issue = ready_tasks.pop(bead_id, None)
            if issue is not None and gate_state == "pending":
                contract = project_state.contracts.get(bead_id, 1)
                if contract >= _PRESENTATION_CONTRACT:
                    skipped += 1
                    continue
                try:
                    was_canceled = _cancel_pending_gate(
                        request_id,
                        reason="task_triage_presentation_upgraded",
                    )
                except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                    runtime.log.warning(
                        f"[bead_task_triage] Failed to refresh stale presentation "
                        f"for gate {request_id}: {exc}"
                    )
                    continue
                canceled += int(was_canceled)

            if issue is None and gate_state == "pending":
                try:
                    was_canceled = _cancel_pending_gate(request_id)
                except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                    runtime.log.warning(
                        f"[bead_task_triage] Failed to cancel stale gate "
                        f"{request_id}: {exc}"
                    )
                    continue
                canceled += int(was_canceled)

            del project_state.gates[bead_id]
            project_state.contracts.pop(bead_id, None)
            state_changed = True
            if issue is not None:
                ready_tasks[bead_id] = issue

        for bead_id, issue in sorted(ready_tasks.items()):
            generation = project_state.generations.get(bead_id, 0) + 1
            request_id = _request_id(project_name, bead_id, generation)
            try:
                create_task_triage_gate(
                    request_id=request_id,
                    bead_id=bead_id,
                    project=project_name,
                    title=issue.title,
                    description=issue.description,
                    notes=issue.notes,
                    created_by=issue.created_by,
                    producer={
                        "chop": "bead_task_triage",
                        "project": project_name,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - retry deterministically.
                runtime.log.warning(
                    f"[bead_task_triage] Failed to create gate for "
                    f"{project_name}:{bead_id}: {exc}"
                )
                continue
            project_state.gates[bead_id] = request_id
            project_state.generations[bead_id] = generation
            project_state.contracts[bead_id] = _PRESENTATION_CONTRACT
            gated += 1
            state_changed = True

    if state_changed:
        try:
            _write_state(state_path, projects)
        except Exception as exc:  # noqa: BLE001 - gate ids make recovery idempotent.
            runtime.log.warning(
                f"[bead_task_triage] Failed to persist reconciliation state: {exc}"
            )

    reason = None if gated or canceled else "no_triage_changes"
    return _summary(
        runtime,
        gated=gated,
        canceled=canceled,
        skipped=skipped,
        reason=reason,
    )


@builtin_chop("bead_task_triage")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_dir = Path(runtime.context.state_dir)
    state_path = state_dir / _STATE_FILENAME
    with file_lock(state_dir / _LOCK_FILENAME):
        return _reconcile(runtime, state_path)


def main() -> None:
    run_builtin_chop("bead_task_triage")


if __name__ == "__main__":
    main()

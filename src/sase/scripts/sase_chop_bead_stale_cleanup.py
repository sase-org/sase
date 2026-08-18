#!/usr/bin/env python3
"""Raise and reconcile the one pending BeadStaleCleanup gate.

An hourly housekeeping chop. Ready task beads below their effective +1 bar --
their own task type's ``triage.min_plus_ones``, or the global
``bead.task_triage.min_plus_ones`` for an untyped bead or an unregistered
type, via :func:`sase.bead.task_triage_policy.effective_min_plus_ones` --
accumulate until ``bead.task_triage.stale_cleanup_min_beads`` of them have
sat there for ``bead.task_triage.stale_after_days``; this pass then offers
the oldest ``BEAD_STALE_CLEANUP_MAX_BEADS`` of them in one gate. Lane state
holds the pending request, a generation counter, and a fingerprint over the
offered roster plus the three thresholds (never ``stale_as_of``).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.bead.config import (
    get_task_triage_min_plus_ones,
    get_task_triage_stale_after_days,
    get_task_triage_stale_cleanup_min_beads,
)
from sase.bead.model import Issue, IssueType, Status
from sase.bead.stale_cleanup_gate import (
    BEAD_STALE_CLEANUP_KIND,
    BEAD_STALE_CLEANUP_MAX_BEADS,
    create_bead_stale_cleanup_gate,
)
from sase.bead.task_triage_policy import effective_min_plus_ones, stale_task_bead
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import bead_read_facade as rust_beads
from sase.core import time as core_time
from sase.notification_gates.durability import (
    canonical_json_bytes,
    file_lock,
    sha256_bytes,
)
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.scripts._bead_gate_projects import (
    ProjectInventory as _ProjectInventory,
    coerce_project_inventory as _coerce_project_inventory,
    enabled_project_stores as _enabled_project_stores_impl,
    project_display_name as _project_display_name,
)
from sase.scripts._bead_task_triage_gates import gate_state as _gate_state_impl
from sase.task_types.registry import TaskTypeRegistry, get_task_type_registry

_STATE_FILENAME = "bead_stale_cleanup.json"
_LOCK_FILENAME = "bead_stale_cleanup.lock"
_STATE_SCHEMA_VERSION = 1
_CHOP = "bead_stale_cleanup"


@dataclass
class _LaneState:
    request_id: str | None = None
    generation: int = 0
    fingerprint: str | None = None


@dataclass(frozen=True)
class _StaleEntry:
    project: str
    issue: Issue

    def payload(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "bead_id": self.issue.id,
            "title": self.issue.title,
            "created_at": self.issue.created_at,
            "plus_one_count": self.issue.plus_one_count,
            "size": self.issue.size.value if self.issue.size else None,
        }

    def sort_key(self) -> tuple[datetime, str, str]:
        created = _parse_created_at(self.issue.created_at)
        fallback = datetime.min.replace(tzinfo=core_time.get_timezone())
        return (created or fallback, self.project, self.issue.id)


def _enabled_project_stores(log: ChopLogger) -> _ProjectInventory:
    return _enabled_project_stores_impl(log, chop=_CHOP)


def _aware_now() -> datetime:
    """Return the configured-tz clock with tzinfo kept.

    ``stale_task_bead`` compares against timezone-aware ``created_at`` values,
    so the naive ``core_time.local_now()`` convention cannot be used here.
    """
    return datetime.now(core_time.get_timezone())


def _parse_created_at(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _ready_task_beads(beads_dir: Path) -> list[Issue]:
    return rust_beads.list_issues(
        beads_dir,
        statuses=[Status.READY],
        issue_types=[IssueType.TASK],
    )


def _read_state(path: Path) -> _LaneState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _LaneState()
    if not isinstance(payload, dict):
        return _LaneState()
    request_id = payload.get("request_id")
    generation = payload.get("generation")
    fingerprint = payload.get("fingerprint")
    return _LaneState(
        request_id=request_id if isinstance(request_id, str) and request_id else None,
        generation=(
            generation
            if isinstance(generation, int)
            and not isinstance(generation, bool)
            and generation >= 1
            else 0
        ),
        fingerprint=(
            fingerprint if isinstance(fingerprint, str) and fingerprint else None
        ),
    )


def _write_state(path: Path, state: _LaneState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"schema_version": _STATE_SCHEMA_VERSION}
    if state.request_id and state.fingerprint:
        payload["request_id"] = state.request_id
        payload["generation"] = state.generation
        payload["fingerprint"] = state.fingerprint
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


def _clear_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _roster_fingerprint(
    beads: list[dict[str, Any]],
    *,
    min_plus_ones: int,
    stale_after_days: int,
    stale_cleanup_min_beads: int,
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "beads": beads,
                "min_plus_ones": min_plus_ones,
                "stale_after_days": stale_after_days,
                "stale_cleanup_min_beads": stale_cleanup_min_beads,
            }
        )
    )


def _request_id(fingerprint: str, generation: int) -> str:
    return f"bead-stale-cleanup-{fingerprint[:12]}-g{generation}"


def _gate_state(request_id: str) -> str:
    return _gate_state_impl(BEAD_STALE_CLEANUP_KIND, request_id)


def _cancel_pending_gate(request_id: str, *, reason: str) -> bool:
    paths = bundle_paths(BEAD_STALE_CLEANUP_KIND, request_id)
    try:
        cancel_gate(paths.root, reason=reason, source=_CHOP)
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
    stale: int = 0,
    offered: int = 0,
    omitted: int = 0,
    projects: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "gated": gated,
            "canceled": canceled,
            "skipped": skipped,
            "stale": stale,
            "offered": offered,
            "omitted": omitted,
            "projects": projects,
        },
        reason=reason,
    )


def _persist(state_path: Path, state: _LaneState, log: ChopLogger) -> None:
    try:
        if state.request_id and state.fingerprint:
            _write_state(state_path, state)
        else:
            _clear_state(state_path)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to persist reconciliation state: {exc}")


def _collect_stale(
    runtime: BuiltinChopRuntime,
    inventory: _ProjectInventory,
    *,
    min_plus_ones: int,
    stale_after_days: int,
    now: datetime,
    task_type_registry: TaskTypeRegistry,
) -> tuple[list[_StaleEntry], set[str], int]:
    skipped_projects = set(inventory.skipped_projects)
    entries: list[_StaleEntry] = []
    projects = 0
    for project_name, beads_dir in inventory.stores:
        try:
            issues = _ready_task_beads(beads_dir)
        except Exception as exc:  # noqa: BLE001 - one store must not stop the chop.
            skipped_projects.add(project_name)
            runtime.log.warning(
                f"[{_CHOP}] Failed to read ready task beads for "
                f"{_project_display_name(project_name)}: {exc}"
            )
            continue
        projects += 1
        for issue in issues:
            if stale_task_bead(
                issue,
                min_plus_ones=effective_min_plus_ones(
                    issue,
                    registry=task_type_registry,
                    global_default=min_plus_ones,
                ),
                stale_after_days=stale_after_days,
                now=now,
            ):
                entries.append(_StaleEntry(project=project_name, issue=issue))
    entries.sort(key=lambda entry: entry.sort_key())
    return entries, skipped_projects, projects


def _inspect_gate(request_id: str, log: ChopLogger) -> str | None:
    try:
        return _gate_state(request_id)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to inspect gate {request_id}: {exc}")
        return None


def _cancel_if_pending(
    request_id: str,
    *,
    reason: str,
    log: ChopLogger,
) -> int | None:
    gate = _inspect_gate(request_id, log)
    if gate is None:
        return None
    if gate != "pending":
        return 0
    try:
        return int(_cancel_pending_gate(request_id, reason=reason))
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to cancel gate {request_id}: {exc}")
        return None


def _create_gate(
    *,
    request_id: str,
    beads: list[dict[str, Any]],
    omitted_count: int,
    min_plus_ones: int,
    stale_after_days: int,
    stale_cleanup_min_beads: int,
    stale_as_of: str,
    log: ChopLogger,
) -> bool:
    try:
        create_bead_stale_cleanup_gate(
            request_id=request_id,
            beads=beads,
            omitted_count=omitted_count,
            min_plus_ones=min_plus_ones,
            stale_after_days=stale_after_days,
            stale_cleanup_min_beads=stale_cleanup_min_beads,
            stale_as_of=stale_as_of,
            producer={"chop": _CHOP},
        )
    except Exception as exc:  # noqa: BLE001 - retry deterministically.
        log.warning(f"[{_CHOP}] Failed to create stale cleanup gate: {exc}")
        return False
    return True


def _reconcile(runtime: BuiltinChopRuntime, state_path: Path) -> ChopResultBuilder:
    if runtime.context.dry_run:
        return _summary(runtime, reason="dry_run")

    min_plus_ones = get_task_triage_min_plus_ones()
    stale_after_days = get_task_triage_stale_after_days()
    stale_cleanup_min_beads = get_task_triage_stale_cleanup_min_beads()
    try:
        inventory = _coerce_project_inventory(_enabled_project_stores(runtime.log))
    except Exception as exc:  # noqa: BLE001 - a bad inventory must fail closed.
        runtime.log.warning(f"[{_CHOP}] Failed to load enabled projects: {exc}")
        return _summary(runtime, reason="project_inventory_unavailable")

    now = _aware_now()
    stale_as_of = now.isoformat()
    entries, skipped_projects, projects = _collect_stale(
        runtime,
        inventory,
        min_plus_ones=min_plus_ones,
        stale_after_days=stale_after_days,
        now=now,
        task_type_registry=get_task_type_registry(),
    )
    incomplete = bool(skipped_projects)
    stale = len(entries)
    offered_entries = entries[:BEAD_STALE_CLEANUP_MAX_BEADS]
    offered_payloads = [entry.payload() for entry in offered_entries]
    offered = len(offered_payloads)
    omitted = max(0, stale - offered)
    if omitted:
        runtime.log.info(
            f"[{_CHOP}] Offering {offered} of {stale} stale task beads; "
            f"{omitted} omitted"
        )

    state = _read_state(state_path)
    pending_id = state.request_id

    if stale < stale_cleanup_min_beads:
        if incomplete:
            return _summary(
                runtime,
                skipped=int(pending_id is not None),
                stale=stale,
                projects=projects,
                reason="incomplete_inventory",
            )
        canceled = 0
        if pending_id is not None:
            result = _cancel_if_pending(
                pending_id,
                reason="stale_backlog_below_threshold",
                log=runtime.log,
            )
            if result is None:
                return _summary(
                    runtime,
                    stale=stale,
                    projects=projects,
                    reason="below_stale_threshold",
                )
            canceled = result
            _persist(state_path, _LaneState(), runtime.log)
        return _summary(
            runtime,
            canceled=canceled,
            stale=stale,
            projects=projects,
            reason=None if canceled else "below_stale_threshold",
        )

    fingerprint = _roster_fingerprint(
        offered_payloads,
        min_plus_ones=min_plus_ones,
        stale_after_days=stale_after_days,
        stale_cleanup_min_beads=stale_cleanup_min_beads,
    )
    if pending_id is not None and state.fingerprint == fingerprint:
        gate = _inspect_gate(pending_id, runtime.log)
        if gate is None:
            return _summary(
                runtime,
                stale=stale,
                offered=offered,
                omitted=omitted,
                projects=projects,
            )
        if gate == "pending":
            return _summary(
                runtime,
                skipped=1,
                stale=stale,
                offered=offered,
                omitted=omitted,
                projects=projects,
                reason="unchanged_roster",
            )

    if incomplete and pending_id is not None:
        gate = _inspect_gate(pending_id, runtime.log)
        if gate is None or gate == "pending":
            return _summary(
                runtime,
                skipped=int(gate == "pending"),
                stale=stale,
                offered=offered,
                omitted=omitted,
                projects=projects,
                reason="incomplete_inventory",
            )

    canceled = 0
    if pending_id is not None:
        result = _cancel_if_pending(
            pending_id,
            reason="stale_roster_changed",
            log=runtime.log,
        )
        if result is None:
            return _summary(
                runtime,
                stale=stale,
                offered=offered,
                omitted=omitted,
                projects=projects,
            )
        canceled = result

    generation = state.generation + 1
    request_id = _request_id(fingerprint, generation)
    if not _create_gate(
        request_id=request_id,
        beads=offered_payloads,
        omitted_count=omitted,
        min_plus_ones=min_plus_ones,
        stale_after_days=stale_after_days,
        stale_cleanup_min_beads=stale_cleanup_min_beads,
        stale_as_of=stale_as_of,
        log=runtime.log,
    ):
        return _summary(
            runtime,
            canceled=canceled,
            stale=stale,
            offered=offered,
            omitted=omitted,
            projects=projects,
        )
    _persist(
        state_path,
        _LaneState(
            request_id=request_id,
            generation=generation,
            fingerprint=fingerprint,
        ),
        runtime.log,
    )
    return _summary(
        runtime,
        gated=1,
        canceled=canceled,
        stale=stale,
        offered=offered,
        omitted=omitted,
        projects=projects,
    )


@builtin_chop("bead_stale_cleanup")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_dir = Path(runtime.context.state_dir)
    state_path = state_dir / _STATE_FILENAME
    with file_lock(state_dir / _LOCK_FILENAME):
        return _reconcile(runtime, state_path)


def main() -> None:
    run_builtin_chop("bead_stale_cleanup")


if __name__ == "__main__":
    main()

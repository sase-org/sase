#!/usr/bin/env python3
"""Raise and reconcile one EpicResume gate per epic stalled by a failed phase.

Each pass scans enabled projects for epic clans (``clan_tribe == "epic"``),
evaluates :func:`sase.bead.epic_stall_policy.stalled_epic` for the newest clan
generation of each, and offers exactly one gate per settled stall. A
fingerprint over the failed-member roster keys lane state so an answered or
dismissed stall never re-gates until a genuinely new failure occurs; the gate
is canceled once the epic resumes or closes, and lane state is pruned for
epics that no longer exist.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent.names import is_process_alive
from sase.bead.config import get_epic_resume_settle_seconds
from sase.bead.epic_resume_gate import (
    EPIC_RESUME_KIND,
    cancel_epic_resume,
    create_epic_resume_gate,
)
from sase.bead.epic_resume_launch import active_epic_resume
from sase.bead.epic_stall_policy import (
    EpicClanMember,
    EpicClanSnapshot,
    EpicStall,
    epic_stall_fingerprint,
    latest_generation_snapshot,
    stalled_epic,
)
from sase.bead.model import Status
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import bead_read_facade as rust_beads
from sase.core.agent_clan_context import (
    clan_context_by_key,
    clan_context_for,
    effective_clan_attributes,
)
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.core.paths import sase_projects_dir
from sase.core.time import get_timezone
from sase.notification_gates.durability import file_lock
from sase.scripts._bead_gate_projects import (
    ProjectInventory as _ProjectInventory,
    coerce_project_inventory as _coerce_project_inventory,
    enabled_project_stores as _enabled_project_stores_impl,
)
from sase.scripts._bead_task_triage_gates import gate_state as _gate_state_impl

_STATE_FILENAME = "epic_resume.json"
_LOCK_FILENAME = "epic_resume.lock"
_STATE_SCHEMA_VERSION = 1
_CHOP = "epic_resume"
_EPIC_TRIBE = "epic"

_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=("ace-run",),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_workflow_state=False,
)


@dataclass
class _LaneState:
    """One epic's reconciliation record.

    ``settled`` marks a stall that was already answered or dismissed:
    ``request_id`` is cleared, but ``fingerprint`` is kept so the same
    failed-member roster never re-gates. A new failure produces a different
    fingerprint and clears ``settled``.
    """

    request_id: str | None = None
    generation: int = 0
    fingerprint: str | None = None
    settled: bool = False


@dataclass(frozen=True)
class _EpicInfo:
    open: bool
    title: str
    remaining_phase_count: int


def _enabled_project_stores(log: ChopLogger) -> _ProjectInventory:
    return _enabled_project_stores_impl(log, chop=_CHOP)


def _member_is_live(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* is RUNNING, STARTING, or QUEUED.

    A done marker is always terminal. A waiting marker with
    ``slot_requested_at`` means the member is queued for a runner slot, not
    blocked on a wait dependency, so it still counts as live. Any other
    waiting marker is a genuine ``%w`` block, matching the non-live
    ``waiting_members`` semantics in :mod:`sase.bead.epic_stall_policy`.
    """
    if record.has_done_marker:
        return False
    waiting = record.waiting
    if waiting is not None:
        return bool(waiting.slot_requested_at)
    meta = record.agent_meta
    pid = meta.pid if meta is not None else None
    stopped_at = meta.stopped_at if meta is not None else None
    return is_process_alive(
        {"pid": pid, "stopped_at": stopped_at}, Path(record.artifact_dir)
    )


def _parse_finished_at_epoch(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return datetime.fromtimestamp(float(value), get_timezone())
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _parse_finished_at_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_timezone())
    return parsed.astimezone(get_timezone())


def _member_finished_at(
    done: DoneMarkerWire | None,
    meta: AgentMetaWire | None = None,
) -> datetime | None:
    """Return the stall clock for one clan member.

    Production ``done.json`` writers historically omitted ``finished_at``.
    ``agent_meta.json`` ``stopped_at`` is the durable fallback the runner
    already records, so real failed phases can settle without waiting for
    every historical marker to be rewritten.
    """
    if done is not None:
        parsed = _parse_finished_at_epoch(done.finished_at)
        if parsed is not None:
            return parsed
    if meta is not None:
        return _parse_finished_at_instant(meta.stopped_at)
    return None


def _build_member(record: AgentArtifactRecordWire) -> EpicClanMember:
    meta = record.agent_meta
    assert meta is not None and meta.name
    done = record.done
    return EpicClanMember(
        agent_name=meta.name,
        bead_id=meta.bead_id or "",
        artifact_dir=record.artifact_dir,
        timestamp=record.timestamp,
        outcome=done.outcome if done is not None else None,
        has_done_marker=record.has_done_marker,
        is_live=_member_is_live(record),
        finished_at=_member_finished_at(done, meta),
    )


def _scan_epic_snapshots(projects_root: Path) -> list[EpicClanSnapshot]:
    """Return one :class:`EpicClanSnapshot` per represented epic clan generation."""
    scan = scan_agent_artifacts(projects_root, _SCAN_OPTIONS)
    clan_contexts = clan_context_by_key(scan.clan_context)
    grouped: dict[tuple[str, str, str], list[AgentArtifactRecordWire]] = {}
    for record in scan.records:
        meta = record.agent_meta
        if (
            meta is None
            or not meta.name
            or not meta.agent_clan
            or not meta.agent_clan_generation
        ):
            continue
        context = clan_context_for(
            clan_contexts,
            agent_clan=meta.agent_clan,
            agent_clan_generation=meta.agent_clan_generation,
        )
        tribe, _ = effective_clan_attributes(
            declared_tribe=meta.clan_tribe,
            declared_summary=meta.clan_summary,
            context=context,
        )
        if tribe != _EPIC_TRIBE:
            continue
        key = (record.project_name, meta.agent_clan, meta.agent_clan_generation)
        grouped.setdefault(key, []).append(record)

    return [
        EpicClanSnapshot(
            project=project_name,
            epic_id=epic_id,
            clan_generation=generation,
            members=tuple(_build_member(record) for record in records),
        )
        for (project_name, epic_id, generation), records in grouped.items()
    ]


def _latest_snapshots_by_epic(
    snapshots: list[EpicClanSnapshot],
) -> dict[tuple[str, str], EpicClanSnapshot]:
    grouped: dict[tuple[str, str], list[EpicClanSnapshot]] = {}
    for snapshot in snapshots:
        grouped.setdefault((snapshot.project, snapshot.epic_id), []).append(snapshot)
    result: dict[tuple[str, str], EpicClanSnapshot] = {}
    for key, group in grouped.items():
        latest = latest_generation_snapshot(group)
        if latest is not None:
            result[key] = latest
    return result


def _resolve_epic_info(beads_dir: Path, epic_id: str) -> _EpicInfo:
    """Return open/title/remaining-phase state for *epic_id*.

    Raises ``KeyError`` when the epic bead no longer exists, and any other
    exception on a genuine store-read failure.
    """
    issue = rust_beads.show(beads_dir, epic_id)
    children = rust_beads.get_epic_children(beads_dir, epic_id)
    remaining = sum(1 for child in children if child.status != Status.CLOSED)
    return _EpicInfo(
        open=issue.status != Status.CLOSED,
        title=issue.title,
        remaining_phase_count=remaining,
    )


def _aware_now() -> datetime:
    return datetime.now(get_timezone())


def _request_id(fingerprint: str, generation: int) -> str:
    return f"epic-resume-{fingerprint[:12]}-g{generation}"


def _gate_state(request_id: str) -> str:
    return _gate_state_impl(EPIC_RESUME_KIND, request_id)


def _inspect_gate(request_id: str, log: ChopLogger) -> str | None:
    try:
        return _gate_state(request_id)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[{_CHOP}] Failed to inspect gate {request_id}: {exc}")
        return None


def _cancel_pending(
    project: str, epic_id: str, *, reason: str, log: ChopLogger
) -> bool:
    try:
        return cancel_epic_resume(project, epic_id, reason=reason, source=_CHOP)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(
            f"[{_CHOP}] Failed to cancel resume gate for {project}:{epic_id}: {exc}"
        )
        return False


def _member_payloads(members: tuple[EpicClanMember, ...]) -> list[dict[str, Any]]:
    return [
        {
            "agent_name": member.agent_name,
            "bead_id": member.bead_id,
            "finished_at": (
                member.finished_at.isoformat()
                if member.finished_at is not None
                else None
            ),
        }
        for member in members
    ]


def _create_gate(
    *,
    request_id: str,
    project: str,
    epic_id: str,
    epic_title: str,
    clan_generation: str,
    stall: EpicStall,
    remaining_phase_count: int,
    log: ChopLogger,
) -> bool:
    try:
        create_epic_resume_gate(
            request_id=request_id,
            project=project,
            epic_id=epic_id,
            epic_title=epic_title,
            clan_generation=clan_generation,
            failed_members=_member_payloads(stall.failed_members),
            waiting_members=_member_payloads(stall.waiting_members),
            remaining_phase_count=remaining_phase_count,
            stalled_since=stall.stalled_since.isoformat(),
            producer={"chop": _CHOP, "project": project},
        )
    except Exception as exc:  # noqa: BLE001 - retry deterministically.
        log.warning(
            f"[{_CHOP}] Failed to create resume gate for {project}:{epic_id}: {exc}"
        )
        return False
    return True


def _read_state(path: Path) -> dict[tuple[str, str], _LaneState]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_epics = payload.get("epics")
    if not isinstance(raw_epics, dict):
        return {}

    result: dict[tuple[str, str], _LaneState] = {}
    for project_name, raw_project in raw_epics.items():
        if not isinstance(project_name, str) or not isinstance(raw_project, dict):
            continue
        for epic_id, raw_entry in raw_project.items():
            if not isinstance(epic_id, str) or not isinstance(raw_entry, dict):
                continue
            fingerprint = raw_entry.get("fingerprint")
            if not isinstance(fingerprint, str) or not fingerprint:
                continue
            request_id = raw_entry.get("request_id")
            generation = raw_entry.get("generation")
            settled = raw_entry.get("settled")
            result[(project_name, epic_id)] = _LaneState(
                request_id=(
                    request_id if isinstance(request_id, str) and request_id else None
                ),
                generation=(
                    generation
                    if isinstance(generation, int)
                    and not isinstance(generation, bool)
                    and generation >= 0
                    else 0
                ),
                fingerprint=fingerprint,
                settled=bool(settled) if isinstance(settled, bool) else False,
            )
    return result


def _write_state(path: Path, states: dict[tuple[str, str], _LaneState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    epics: dict[str, dict[str, Any]] = {}
    for (project_name, epic_id), state in sorted(states.items()):
        if state.fingerprint is None:
            continue
        epics.setdefault(project_name, {})[epic_id] = {
            "request_id": state.request_id,
            "generation": state.generation,
            "fingerprint": state.fingerprint,
            "settled": state.settled,
        }
    payload = {"schema_version": _STATE_SCHEMA_VERSION, "epics": epics}
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


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    deferred: int = 0,
    stalled: int = 0,
    epics: int = 0,
    projects: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "gated": gated,
            "canceled": canceled,
            "skipped": skipped,
            "deferred": deferred,
            "stalled": stalled,
            "epics": epics,
            "projects": projects,
        },
        reason=reason,
    )


def _reconcile(runtime: BuiltinChopRuntime, state_path: Path) -> ChopResultBuilder:
    if runtime.context.dry_run:
        return _summary(runtime, reason="dry_run")

    try:
        inventory = _coerce_project_inventory(_enabled_project_stores(runtime.log))
    except Exception as exc:  # noqa: BLE001 - a bad inventory must fail closed.
        runtime.log.warning(f"[{_CHOP}] Failed to load enabled projects: {exc}")
        return _summary(runtime, reason="project_inventory_unavailable")

    beads_dirs = dict(inventory.stores)
    readable_projects = set(beads_dirs)

    try:
        snapshots = _scan_epic_snapshots(sase_projects_dir())
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        runtime.log.warning(f"[{_CHOP}] Failed to scan epic clan artifacts: {exc}")
        return _summary(runtime, reason="scan_unavailable")

    latest_by_epic = _latest_snapshots_by_epic(
        [snapshot for snapshot in snapshots if snapshot.project in readable_projects]
    )

    now = _aware_now()
    settle_seconds = get_epic_resume_settle_seconds()
    state = _read_state(state_path)
    seen_keys: set[tuple[str, str]] = set()
    gated = canceled = skipped = deferred = stalled_count = 0
    state_changed = False

    for (project, epic_id), snapshot in sorted(latest_by_epic.items()):
        seen_keys.add((project, epic_id))
        beads_dir = beads_dirs[project]
        try:
            info: _EpicInfo | None = _resolve_epic_info(beads_dir, epic_id)
        except KeyError:
            info = None
        except Exception as exc:  # noqa: BLE001 - one epic must not stop the chop.
            runtime.log.warning(
                f"[{_CHOP}] Failed to resolve epic bead {project}:{epic_id}: {exc}"
            )
            continue

        lane = state.get((project, epic_id))

        if info is None:
            if lane is not None:
                if not lane.settled and lane.request_id is not None:
                    canceled += int(
                        _cancel_pending(
                            project, epic_id, reason="epic_vanished", log=runtime.log
                        )
                    )
                del state[(project, epic_id)]
                state_changed = True
            continue

        stall = stalled_epic(
            snapshot, epic_open=info.open, now=now, settle_seconds=settle_seconds
        )

        if stall is None:
            if lane is not None:
                if not lane.settled and lane.request_id is not None:
                    cancel_reason = "epic_closed" if not info.open else "epic_resumed"
                    canceled += int(
                        _cancel_pending(
                            project, epic_id, reason=cancel_reason, log=runtime.log
                        )
                    )
                del state[(project, epic_id)]
                state_changed = True
            continue

        stalled_count += 1

        try:
            in_flight = active_epic_resume(epic_id) is not None
        except Exception as exc:  # noqa: BLE001 - keep today's gating behavior.
            runtime.log.warning(
                f"[{_CHOP}] Failed to read active resume launches for {epic_id}: {exc}"
            )
            in_flight = False
        if in_flight:
            deferred += 1
            continue

        fingerprint = epic_stall_fingerprint(stall)

        if lane is not None and lane.fingerprint == fingerprint:
            if lane.settled:
                skipped += 1
                continue
            if lane.request_id is not None:
                gate_state = _inspect_gate(lane.request_id, runtime.log)
                if gate_state is None or gate_state == "pending":
                    skipped += 1
                    continue
                if gate_state == "terminal":
                    state[(project, epic_id)] = _LaneState(
                        request_id=None,
                        generation=lane.generation,
                        fingerprint=fingerprint,
                        settled=True,
                    )
                    state_changed = True
                    skipped += 1
                    continue
                # gate_state == "missing": the bundle vanished; re-raise below.

        if lane is not None and not lane.settled and lane.request_id is not None:
            canceled += int(
                _cancel_pending(
                    project, epic_id, reason="epic_stall_changed", log=runtime.log
                )
            )

        generation = (lane.generation if lane is not None else 0) + 1
        request_id = _request_id(fingerprint, generation)
        if not _create_gate(
            request_id=request_id,
            project=project,
            epic_id=epic_id,
            epic_title=info.title,
            clan_generation=snapshot.clan_generation,
            stall=stall,
            remaining_phase_count=info.remaining_phase_count,
            log=runtime.log,
        ):
            continue
        state[(project, epic_id)] = _LaneState(
            request_id=request_id,
            generation=generation,
            fingerprint=fingerprint,
            settled=False,
        )
        state_changed = True
        gated += 1

    if inventory.sweep_allowed:
        for key in list(state):
            if key in seen_keys:
                continue
            project, epic_id = key
            if project not in readable_projects:
                continue
            lane = state[key]
            if not lane.settled and lane.request_id is not None:
                canceled += int(
                    _cancel_pending(
                        project, epic_id, reason="epic_vanished", log=runtime.log
                    )
                )
            del state[key]
            state_changed = True

    if state_changed:
        try:
            _write_state(state_path, state)
        except Exception as exc:  # noqa: BLE001 - retry on the next tick.
            runtime.log.warning(
                f"[{_CHOP}] Failed to persist reconciliation state: {exc}"
            )

    reason = None if (gated or canceled or deferred) else "no_stall_changes"
    return _summary(
        runtime,
        gated=gated,
        canceled=canceled,
        skipped=skipped,
        deferred=deferred,
        stalled=stalled_count,
        epics=len(latest_by_epic),
        projects=len(readable_projects),
        reason=reason,
    )


@builtin_chop("epic_resume")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_dir = Path(runtime.context.state_dir)
    state_path = state_dir / _STATE_FILENAME
    with file_lock(state_dir / _LOCK_FILENAME):
        return _reconcile(runtime, state_path)


def main() -> None:
    run_builtin_chop("epic_resume")


if __name__ == "__main__":
    main()

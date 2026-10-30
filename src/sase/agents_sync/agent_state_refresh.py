"""Periodic bounded convergence for already-published agent-run states.

One scheduler tick selects a single enabled project with a configured agents
sidecar, then runs one default bounded repair window for the current owner.
Scheduling policy (fair rotation plus bounded exponential backoff) lives in
``sase_core``; this module supplies time, project enumeration, durable
checkpoints, and calls into the bounded repair service. A tick killed by the
job timeout counts as a failed attempt (the project backs off, keeps its
cursor, and rotation continues), and a window that cannot advance retries
with backoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.agents_sync.publication_state_repair import (
    STATE_REPAIR_DEFAULT_LIMIT,
    STATE_REPAIR_WORK_BUDGET_SECONDS,
    StateRepairReport,
    repair_project_run_states,
)

AGENT_STATE_REFRESH_SCHEMA_VERSION = 1
AGENT_STATE_REFRESH_STATE_FILENAME = "agent_state_refresh.json"
AGENT_STATE_REFRESH_LOCK_FILENAME = "agent_state_refresh.lock"
AGENT_STATE_REFRESH_DEFAULT_LIMIT = STATE_REPAIR_DEFAULT_LIMIT
AGENT_STATE_REFRESH_WORK_BUDGET_SECONDS = STATE_REPAIR_WORK_BUDGET_SECONDS
AGENT_STATE_REFRESH_COMMAND = "sase agent sync --repair-states"


@dataclass(frozen=True, slots=True)
class AgentStateRefreshSummary:
    """One scheduler tick outcome for the agent_state_refresh job."""

    projects: int = 0
    examined: int = 0
    changed: int = 0
    already_current: int = 0
    live: int = 0
    unresolved: int = 0
    withheld: int = 0
    failed: int = 0
    errors: int = 0
    selected_project: str | None = None
    pass_complete: bool = False
    next_cursor: str | None = None
    diagnostics: tuple[str, ...] = ()
    reason: str | None = None


@dataclass
class _Checkpoint:
    cursor: str | None = None
    failure_count: int = 0
    retry_after_ms: int = 0


@dataclass
class _PersistedState:
    last_selected: dict[str, str] | None = None
    checkpoints: dict[str, _Checkpoint] = field(default_factory=dict)


def _owner_token(owner: Any) -> str:
    return f"{owner.username}@{owner.machine_name}"


def _state_key(project_key: str, owner_token: str) -> str:
    return f"{project_key}:{owner_token}"


def _read_state(path: Path) -> _PersistedState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _PersistedState()
    if not isinstance(payload, dict):
        return _PersistedState()
    if payload.get("schema_version") != AGENT_STATE_REFRESH_SCHEMA_VERSION:
        return _PersistedState()
    raw_last = payload.get("last_selected")
    last_selected: dict[str, str] | None = None
    if isinstance(raw_last, dict):
        project = raw_last.get("project")
        owner = raw_last.get("owner")
        if isinstance(project, str) and project and isinstance(owner, str) and owner:
            last_selected = {"project": project, "owner": owner}
    checkpoints: dict[str, _Checkpoint] = {}
    raw_projects = payload.get("projects")
    if isinstance(raw_projects, dict):
        for key, raw_entry in raw_projects.items():
            if not isinstance(key, str) or not isinstance(raw_entry, dict):
                continue
            cursor = raw_entry.get("cursor")
            failures = raw_entry.get("failure_count")
            retry_after = raw_entry.get("retry_after_ms")
            if cursor is not None and not isinstance(cursor, str):
                continue
            if (
                not isinstance(failures, int)
                or isinstance(failures, bool)
                or failures < 0
            ):
                continue
            if (
                not isinstance(retry_after, int)
                or isinstance(retry_after, bool)
                or retry_after < 0
            ):
                continue
            checkpoints[key] = _Checkpoint(
                cursor=cursor,
                failure_count=failures,
                retry_after_ms=retry_after,
            )
    return _PersistedState(last_selected=last_selected, checkpoints=checkpoints)


def _write_state(path: Path, state: _PersistedState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": AGENT_STATE_REFRESH_SCHEMA_VERSION,
        "last_selected": state.last_selected,
        "projects": {
            key: {
                "cursor": entry.cursor,
                "failure_count": entry.failure_count,
                "retry_after_ms": entry.retry_after_ms,
            }
            for key, entry in sorted(state.checkpoints.items())
        },
    }
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _apply_schedule_transition(
    state: _PersistedState,
    transition: Any,
    fallback_identity: Any,
) -> None:
    if transition.updated_checkpoint is not None:
        state.checkpoints[
            _state_key(
                transition.updated_checkpoint.identity.project,
                transition.updated_checkpoint.identity.owner,
            )
        ] = _Checkpoint(
            cursor=transition.updated_checkpoint.cursor,
            failure_count=transition.updated_checkpoint.failure_count,
            retry_after_ms=transition.updated_checkpoint.retry_after_ms,
        )
        state.last_selected = {
            "project": transition.updated_checkpoint.identity.project,
            "owner": transition.updated_checkpoint.identity.owner,
        }
    else:
        state.last_selected = {
            "project": fallback_identity.project,
            "owner": fallback_identity.owner,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _require_owner() -> Any:
    from sase.agents_sync import _commit_publication_support as support

    return support.require_agent_owner_identity()


def _resolve_targets() -> tuple[list[Any], list[Any]]:
    from sase.agents_sync import _commit_publication_support as support

    selection = support.resolve_sync_targets(())
    return list(selection.targets), list(selection.outcomes)


def _repair_one(
    target: Any,
    owner: Any,
    *,
    state_after: str | None,
    state_limit: int = AGENT_STATE_REFRESH_DEFAULT_LIMIT,
    work_budget_seconds: float = AGENT_STATE_REFRESH_WORK_BUDGET_SECONDS,
) -> StateRepairReport:
    return repair_project_run_states(
        target,
        owner,
        apply=True,
        state_limit=state_limit,
        state_after=state_after,
        work_budget_seconds=work_budget_seconds,
    )


def run_agent_state_refresh(
    *,
    state_dir: Path | str,
    now_ms: int | None = None,
    state_limit: int = AGENT_STATE_REFRESH_DEFAULT_LIMIT,
    work_budget_seconds: float = AGENT_STATE_REFRESH_WORK_BUDGET_SECONDS,
    list_targets: Callable[[], tuple[list[Any], list[Any]]] | None = None,
    require_owner: Callable[[], Any] | None = None,
    repair_one: Callable[..., StateRepairReport] | None = None,
    now_ms_fn: Callable[[], int] | None = None,
) -> AgentStateRefreshSummary:
    """Run one bounded scheduled refresh tick for the current owner."""

    from sase.notification_gates.durability import file_lock

    directory = Path(state_dir)
    state_path = directory / AGENT_STATE_REFRESH_STATE_FILENAME
    lock_path = directory / AGENT_STATE_REFRESH_LOCK_FILENAME
    with file_lock(lock_path):
        return _run_locked(
            state_path,
            now_ms=now_ms,
            state_limit=state_limit,
            work_budget_seconds=work_budget_seconds,
            list_targets=list_targets,
            require_owner=require_owner,
            repair_one=repair_one,
            now_ms_fn=now_ms_fn,
        )


def _run_locked(
    state_path: Path,
    *,
    now_ms: int | None,
    state_limit: int,
    work_budget_seconds: float,
    list_targets: Callable[[], tuple[list[Any], list[Any]]] | None,
    require_owner: Callable[[], Any] | None,
    repair_one: Callable[..., StateRepairReport] | None,
    now_ms_fn: Callable[[], int] | None,
) -> AgentStateRefreshSummary:
    from sase.core.agent_run_state_facade import advance_agent_run_state_schedule
    from sase.core.agent_run_state_wire import (
        AGENT_RUN_STATE_OUTCOME_FAILURE,
        AGENT_RUN_STATE_OUTCOME_SUCCESS,
        AGENT_RUN_STATE_WIRE_SCHEMA_VERSION,
        AgentRunStateProjectIdentityWire,
        AgentRunStateProjectWire,
        AgentRunStateScheduleOutcomeWire,
        AgentRunStateScheduleRequestWire,
    )

    clock = now_ms_fn or _now_ms
    moment = now_ms if now_ms is not None else clock()
    owner_fn = require_owner or _require_owner
    try:
        owner = owner_fn()
    except (RuntimeError, ValueError) as exc:
        return AgentStateRefreshSummary(
            errors=1,
            reason="no_owner_identity",
            diagnostics=(f"owner identity is not configured: {exc}",),
        )
    token = _owner_token(owner)

    targets_fn = list_targets or _resolve_targets
    try:
        targets, outcomes = targets_fn()
    except Exception as exc:  # noqa: BLE001 - discovery failure backs off cleanly
        return AgentStateRefreshSummary(
            errors=1,
            reason="target_discovery_failed",
            diagnostics=(f"could not list enabled projects: {exc}",),
        )

    diagnostics: list[str] = []
    errors = 0
    for outcome in outcomes:
        message = getattr(outcome, "error", None)
        if message:
            errors += 1
            key = getattr(outcome, "project_key", "?")
            diagnostics.append(f"{key}: {message}")

    persisted = _read_state(state_path)
    live_keys = {_state_key(target.project_key, token) for target in targets}
    for stale_key in [key for key in persisted.checkpoints if key not in live_keys]:
        del persisted.checkpoints[stale_key]

    if not targets:
        try:
            _write_state(state_path, persisted)
        except Exception as exc:  # noqa: BLE001 - persistence retries next tick
            diagnostics.append(f"failed to persist refresh state: {exc}")
        return AgentStateRefreshSummary(
            projects=0,
            errors=errors,
            diagnostics=tuple(diagnostics),
            reason="no_enabled_projects" if not diagnostics else None,
        )

    wires = tuple(
        AgentRunStateProjectWire(
            identity=AgentRunStateProjectIdentityWire(
                project=target.project_key,
                owner=token,
            ),
            enabled=True,
            configured=True,
            cursor=persisted.checkpoints.get(
                _state_key(target.project_key, token), _Checkpoint()
            ).cursor,
            failure_count=persisted.checkpoints.get(
                _state_key(target.project_key, token), _Checkpoint()
            ).failure_count,
            retry_after_ms=persisted.checkpoints.get(
                _state_key(target.project_key, token), _Checkpoint()
            ).retry_after_ms,
        )
        for target in sorted(targets, key=lambda item: item.project_key)
    )
    last_selected = None
    if persisted.last_selected is not None:
        last_selected = AgentRunStateProjectIdentityWire(
            project=persisted.last_selected["project"],
            owner=persisted.last_selected["owner"],
        )

    try:
        selection = advance_agent_run_state_schedule(
            AgentRunStateScheduleRequestWire(
                schema_version=AGENT_RUN_STATE_WIRE_SCHEMA_VERSION,
                now_ms=moment,
                last_selected=last_selected,
                projects=wires,
                outcome=None,
            )
        )
    except (ValueError, RuntimeError) as exc:
        return AgentStateRefreshSummary(
            projects=len(targets),
            errors=errors + 1,
            diagnostics=(*diagnostics, f"scheduling policy failed: {exc}"),
            reason="scheduling_failed",
        )

    if selection.next_project is None:
        try:
            _write_state(state_path, persisted)
        except Exception as exc:  # noqa: BLE001 - persistence retries next tick
            diagnostics.append(f"failed to persist refresh state: {exc}")
        return AgentStateRefreshSummary(
            projects=len(targets),
            errors=errors,
            diagnostics=tuple(diagnostics),
            reason="all_backed_off" if not errors else None,
        )

    selected_key = selection.next_project.project
    target = next((item for item in targets if item.project_key == selected_key), None)
    if target is None:
        return AgentStateRefreshSummary(
            projects=len(targets),
            errors=errors + 1,
            diagnostics=(
                *diagnostics,
                f"selected project {selected_key!r} is not resolvable",
            ),
            reason="scheduling_failed",
        )

    checkpoint = persisted.checkpoints.get(
        _state_key(target.project_key, token), _Checkpoint()
    )
    outcome_identity = AgentRunStateProjectIdentityWire(
        project=target.project_key,
        owner=token,
    )
    try:
        pre_transition = advance_agent_run_state_schedule(
            AgentRunStateScheduleRequestWire(
                schema_version=AGENT_RUN_STATE_WIRE_SCHEMA_VERSION,
                now_ms=moment,
                last_selected=outcome_identity,
                projects=wires,
                outcome=AgentRunStateScheduleOutcomeWire(
                    identity=outcome_identity,
                    result=AGENT_RUN_STATE_OUTCOME_FAILURE,
                    next_cursor=None,
                    pass_complete=False,
                ),
            )
        )
    except (ValueError, RuntimeError) as exc:
        return AgentStateRefreshSummary(
            projects=len(targets),
            errors=errors + 1,
            diagnostics=(*diagnostics, f"scheduling policy failed: {exc}"),
            reason="scheduling_failed",
        )
    pre_persisted = _PersistedState(
        last_selected=(
            dict(persisted.last_selected) if persisted.last_selected else None
        ),
        checkpoints=dict(persisted.checkpoints),
    )
    _apply_schedule_transition(pre_persisted, pre_transition, outcome_identity)
    try:
        _write_state(state_path, pre_persisted)
    except Exception as exc:  # noqa: BLE001 - persistence retries next tick
        diagnostics.append(f"failed to persist refresh pre-charge: {exc}")
    repair = repair_one or _repair_one
    try:
        report = repair(
            target,
            owner,
            state_after=checkpoint.cursor,
            state_limit=state_limit,
            work_budget_seconds=work_budget_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - per-project isolation contract
        report = StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            error=f"agents state refresh failed: {exc}",
        )

    window_not_advanced = (
        report.error is None
        and report.skip_reason is None
        and report.next_cursor is None
        and not report.pass_complete
    )
    if report.error is not None or report.skip_reason is not None:
        outcome_result = AGENT_RUN_STATE_OUTCOME_FAILURE
        outcome_cursor = None
        outcome_complete = False
        detail = report.error or report.skip_reason or "unknown failure"
        diagnostics.append(f"{target.project_key}: {detail}")
    elif window_not_advanced:
        outcome_result = AGENT_RUN_STATE_OUTCOME_FAILURE
        outcome_cursor = None
        outcome_complete = False
        diagnostics.append(
            f"{target.project_key}: repair window did not advance; "
            "retrying with backoff"
        )
    else:
        outcome_result = AGENT_RUN_STATE_OUTCOME_SUCCESS
        outcome_cursor = report.next_cursor
        outcome_complete = report.pass_complete

    try:
        transition = advance_agent_run_state_schedule(
            AgentRunStateScheduleRequestWire(
                schema_version=AGENT_RUN_STATE_WIRE_SCHEMA_VERSION,
                now_ms=moment,
                last_selected=outcome_identity,
                projects=wires,
                outcome=AgentRunStateScheduleOutcomeWire(
                    identity=outcome_identity,
                    result=outcome_result,
                    next_cursor=outcome_cursor,
                    pass_complete=outcome_complete,
                ),
            )
        )
    except (ValueError, RuntimeError) as exc:
        return AgentStateRefreshSummary(
            projects=len(targets),
            errors=errors + 1,
            diagnostics=(*diagnostics, f"scheduling policy failed: {exc}"),
            reason="scheduling_failed",
        )

    _apply_schedule_transition(persisted, transition, outcome_identity)
    try:
        _write_state(state_path, persisted)
    except Exception as exc:  # noqa: BLE001 - persistence retries next tick
        diagnostics.append(f"failed to persist refresh state: {exc}")
        return AgentStateRefreshSummary(
            projects=len(targets),
            examined=report.examined,
            changed=report.changed,
            already_current=report.already_current,
            live=report.live,
            unresolved=report.unresolved,
            withheld=report.withheld,
            failed=report.failed,
            errors=errors + 1,
            selected_project=target.project_key,
            pass_complete=report.pass_complete,
            next_cursor=report.next_cursor,
            diagnostics=(*diagnostics, *report.diagnostics),
            reason="state_persist_failed",
        )

    failed_total = report.failed + (1 if report.error else 0)
    reason: str | None = None
    if report.error or report.skip_reason:
        reason = "project_failed"
    elif window_not_advanced:
        reason = "window_not_advanced"
    return AgentStateRefreshSummary(
        projects=len(targets),
        examined=report.examined,
        changed=report.changed,
        already_current=report.already_current,
        live=report.live,
        unresolved=report.unresolved,
        withheld=report.withheld,
        failed=failed_total,
        errors=errors,
        selected_project=target.project_key,
        pass_complete=report.pass_complete,
        next_cursor=report.next_cursor,
        diagnostics=(*diagnostics, *report.diagnostics),
        reason=reason,
    )


__all__ = [
    "AGENT_STATE_REFRESH_COMMAND",
    "AGENT_STATE_REFRESH_DEFAULT_LIMIT",
    "AGENT_STATE_REFRESH_LOCK_FILENAME",
    "AGENT_STATE_REFRESH_SCHEMA_VERSION",
    "AGENT_STATE_REFRESH_STATE_FILENAME",
    "AGENT_STATE_REFRESH_WORK_BUDGET_SECONDS",
    "AgentStateRefreshSummary",
    "run_agent_state_refresh",
]

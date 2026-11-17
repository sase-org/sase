"""Resolve a hijack request to its occupying turn."""

from __future__ import annotations

from copy import copy
from pathlib import Path
from typing import Any

from sase.agent.hijack._facts_common import (
    HijackSubject,
    MemberFacts,
    capabilities,
    eligibility_schema_version,
    has_numbered_claim,
    nested_text,
    text,
    value,
)
from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_done_marker
from sase.agent.hijack._stop_target import classify_turn, resolve_direct_target

_LIVE_STATUSES = frozenset({"STARTING", "RUNNING", "RETRYING"})
_WAITING_STATUSES = frozenset({"WAITING", "QUEUED"})
_TERMINAL_STATUSES = frozenset({"DONE", "FAILED", "HIJACKED", "STOPPED", "LOST"})
_TERMINAL_MONITOR_STATES = frozenset(
    {"completed", "failed", "timeout", "stopped", "lost"}
)
_TERMINAL_FOLLOWUP_OUTCOMES = frozenset(
    {
        "launched",
        "launched-degraded",
        "hijacked",
        "host-completed",
        "suppressed",
        "not-launchable",
    }
)
_DELIVERED_DISPOSITIONS = frozenset({"acknowledged", "settled", "dispatching"})
_PENDING_DISPOSITIONS = frozenset({"pending", "reserved"})


def resolve_hijack_subject(
    name_or_row: str | Any,
    *,
    deps: StopDeps | None = None,
) -> HijackSubject:
    """Resolve a member, session name, or session-container row to its occupant."""
    from sase.core.agent_artifact_group_lookup import (
        AgentArtifactGroupLookupUnavailable,
    )
    from sase.agent.names._lookup_named import AgentNamedLookupUnavailable

    deps = deps or StopDeps()
    row = None if isinstance(name_or_row, str) else name_or_row
    requested_name = _input_name(name_or_row)

    from sase.agent.names import NamedAgent

    find_agent = deps.find_agent or _default_find_agent
    raw_artifacts_dir = value(row, "artifacts_dir")
    artifacts_dir = (
        str(raw_artifacts_dir) if isinstance(raw_artifacts_dir, (str, Path)) else None
    )
    try:
        found_agent = (
            NamedAgent(
                name=requested_name,
                artifacts_dir=artifacts_dir,
                is_done=False,
                outcome=None,
            )
            if artifacts_dir
            else find_agent(requested_name)
        )
        session = None
        if artifacts_dir:
            session = _session_from_member_dir(deps, artifacts_dir)
        if session is None and found_agent is not None:
            session = _session_from_member_dir(deps, found_agent.artifacts_dir)
        if session is None:
            session = _session_from_name(deps, requested_name)
    except (AgentArtifactGroupLookupUnavailable, AgentNamedLookupUnavailable) as exc:
        return _unavailable_group_subject(requested_name, row, exc)

    if session is not None:
        roster: tuple[Any, ...] = tuple(session.members)
        if not roster and session.root is not None:
            roster = (session.root,)
    elif found_agent is not None:
        roster = (found_agent,)
    else:
        roster = ()

    running_rows = _running_rows(deps, row, roster)
    deps = copy(deps)
    deps.list_running = lambda: running_rows
    claims_by_project: dict[str, list[Any]] = {}
    member_facts: list[MemberFacts] = []
    for member in roster:
        member_name = str(getattr(member, "name", requested_name) or requested_name)
        member_artifacts = str(getattr(member, "artifacts_dir", "") or "")
        if not member_artifacts:
            continue
        member_meta = _read_meta(member_artifacts)
        member_agent = NamedAgent(
            name=member_name,
            artifacts_dir=member_artifacts,
            is_done=bool(getattr(member, "is_done", False)),
            outcome=getattr(member, "outcome", None),
        )
        _project_name, project_file, timestamp, is_home = _project_fields(member_agent)
        claims = claims_by_project.get(project_file)
        if claims is None:
            claims = _claims_for_project(project_file)
            claims_by_project[project_file] = claims
        claim = next(
            (item for item in claims if item.artifacts_timestamp == timestamp), None
        )
        live_row = _row_for_member(running_rows, member_name, member_artifacts)
        pid = _pid(getattr(claim, "pid", None)) or _pid(member_meta.get("pid"))
        if pid is None:
            pid = _pid(value(live_row, "pid"))
        process_alive = _process_alive(member_meta, Path(member_artifacts), pid, deps)
        status = _status(live_row, process_alive)
        done_outcome, _ = read_done_marker(member_artifacts)
        done_outcome = done_outcome or text(getattr(member, "outcome", None))
        is_monitor, is_gate, gate_state = classify_turn(member_meta)
        monitor_state = _monitor_state(member_meta, live_row)
        turn_phase = text(member_meta.get("lifecycle_phase"))
        finalizer_phase = nested_text(member_meta, "finalizer_status", "phase")
        occupying_kind = _occupying_kind(
            member_meta,
            live_row,
            status,
            is_monitor=is_monitor,
            is_gate=is_gate,
        )
        pre_provider = turn_phase in {"booting", "waiting", "preparing"}
        followup_pending = _monitor_followup_pending(
            member_artifacts,
            member_meta,
            occupying_kind=occupying_kind,
            monitor_state=monitor_state,
            done_outcome=done_outcome,
        )
        settled = (
            done_outcome is not None
            or (status in _TERMINAL_STATUSES and not pre_provider)
        ) and not followup_pending
        waiting = status in _WAITING_STATUSES
        in_flight = (
            status in _LIVE_STATUSES
            or pre_provider
            or turn_phase
            in {
                "provider_running",
                "provider_done",
                "finalizing",
                "handoff",
            }
        )
        member_facts.append(
            MemberFacts(
                member=member,
                name=member_name,
                artifacts_dir=member_artifacts,
                timestamp=timestamp,
                meta=member_meta,
                row=live_row,
                claim=claim,
                status=status,
                pid=pid,
                process_alive=process_alive,
                done_outcome=done_outcome,
                is_home=is_home,
                occupying_kind=occupying_kind,
                turn_phase=turn_phase,
                finalizer_phase=finalizer_phase,
                gate_state=gate_state,
                monitor_state=monitor_state,
                settled=settled,
                in_flight=in_flight,
                waiting=waiting,
                monitor_followup_pending=followup_pending,
            )
        )

    ordered = tuple(sorted(member_facts, key=lambda item: item.timestamp))
    selection_request = {
        "schema_version": eligibility_schema_version(),
        "members": [
            {
                "name": member.name,
                "status": member.status,
                "holds_claim": has_numbered_claim(member.claim),
                "in_flight": member.in_flight,
                "waiting": member.waiting,
                "settled": member.settled,
                "order": index,
            }
            for index, member in enumerate(ordered)
        ],
    }
    from sase.agent.hijack.core import agent_hijack_select_occupant

    selection = agent_hijack_select_occupant(selection_request)
    selected_index = selection.get("selected_index")
    selected = (
        ordered[selected_index]
        if isinstance(selected_index, int)
        and not isinstance(selected_index, bool)
        and 0 <= selected_index < len(ordered)
        else None
    )
    context = selected or (ordered[-1] if ordered else None)
    occupant_reason = str(selection.get("reason") or "session has no live member")

    is_session_container = bool(
        value(row, "is_agent_session_container_row", False)
        or value(row, "is_session_container", False)
        or (session is not None and requested_name == session.base_name)
    )
    is_named_proc = bool(value(row, "is_named_proc", False)) or (
        context is not None
        and _is_named_proc(
            context.meta,
            is_monitor=context.occupying_kind == "monitor",
            is_gate=context.occupying_kind == "gate",
        )
    )
    is_clan_container = bool(
        value(row, "is_clan_container", False) or value(row, "is_clan", False)
    )
    if not is_clan_container:
        try:
            is_clan_container = _clan_from_name(deps, requested_name) is not None
        except AgentArtifactGroupLookupUnavailable as exc:
            return _unavailable_group_subject(requested_name, row, exc)
    is_remote = bool(
        value(row, "is_remote", False)
        or value(row, "fleet_origin_alias", None)
        or value(row, "is_remote_agent_session_container", False)
    )
    is_bulk = bool(
        value(row, "is_bulk", False)
        or value(row, "is_bulk_marked", False)
        or value(row, "bulk_marked", False)
    )

    target: HijackTarget | None = None
    if context is not None:
        selected_agent = NamedAgent(
            name=context.name,
            artifacts_dir=context.artifacts_dir,
            is_done=context.done_outcome is not None,
            outcome=context.done_outcome,
        )
        session_name = (
            str(session.base_name)
            if session is not None
            else text(context.meta.get("agent_session"))
        )
        target = resolve_direct_target(
            context.name,
            deps=deps,
            found_override=selected_agent,
            row_override=context.row,
            session_name=session_name,
        )
        if target is not None:
            target.occupant_name = selected.name if selected is not None else None
            target.occupant_reason = occupant_reason

    return HijackSubject(
        requested_name=requested_name,
        target=target,
        selected=selected,
        context=context,
        members=ordered,
        session=session,
        occupant_reason=occupant_reason,
        is_session_container=is_session_container,
        is_named_proc=is_named_proc,
        is_clan_container=is_clan_container,
        is_remote=is_remote,
        is_bulk=is_bulk,
        row=row,
        found=bool(found_agent is not None or session is not None or row is not None),
    )


def _unavailable_group_subject(
    requested_name: str,
    row: Any | None,
    error: BaseException,
) -> HijackSubject:
    """Make index incompleteness a safe, explicit refusal."""
    return HijackSubject(
        requested_name=requested_name,
        target=None,
        selected=None,
        context=None,
        members=(),
        session=None,
        occupant_reason="agent group lookup is incomplete",
        is_session_container=False,
        is_named_proc=False,
        is_clan_container=False,
        is_remote=False,
        is_bulk=False,
        row=row,
        found=False,
        lookup_error=str(error),
    )


def _default_find_agent(name: str) -> Any | None:
    from sase.agent.names import find_named_agent

    return find_named_agent(name, include_dead=True)


def _session_from_member_dir(deps: StopDeps, artifacts_dir: str) -> Any | None:
    from sase.core.agent_artifact_group_lookup import (
        AgentArtifactGroupLookupUnavailable,
    )

    lookup = deps.find_session_by_member_artifact_dir
    if lookup is None:
        from sase.agent.names import find_agent_session_by_member_artifact_dir

        lookup = find_agent_session_by_member_artifact_dir
    try:
        found = lookup(artifacts_dir)
    except AgentArtifactGroupLookupUnavailable:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if isinstance(found, tuple) and found:
        return found[0]
    return None


def _session_from_name(deps: StopDeps, name: str) -> Any | None:
    from sase.core.agent_artifact_group_lookup import (
        AgentArtifactGroupLookupUnavailable,
    )

    lookup = deps.find_session
    if lookup is None:
        from sase.agent.names import find_agent_session

        lookup = find_agent_session
    try:
        return lookup(name)
    except AgentArtifactGroupLookupUnavailable:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _clan_from_name(deps: StopDeps, name: str) -> Any | None:
    from sase.core.agent_artifact_group_lookup import (
        AgentArtifactGroupLookupUnavailable,
    )

    lookup = deps.find_clan
    if lookup is None:
        from sase.agent.names import find_agent_clan

        lookup = find_agent_clan
    try:
        return lookup(name)
    except AgentArtifactGroupLookupUnavailable:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _input_name(name_or_row: str | Any) -> str:
    if isinstance(name_or_row, str):
        return name_or_row
    for field in ("presented_agent_name", "agent_name", "name"):
        name = text(value(name_or_row, field))
        if name:
            return name
    return ""


def _running_rows(
    deps: StopDeps, input_row: Any | None, roster: tuple[Any, ...]
) -> list[Any]:
    rows: list[Any] = []
    if input_row is not None and value(input_row, "artifacts_dir"):
        rows.append(input_row)
    list_running = deps.list_running
    if list_running is None:
        try:
            from sase.agent.running_listing import running_from_snapshot
            from sase.core.agent_scan_facade import scan_agent_artifact_dirs
            from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
            from sase.core.paths import sase_projects_dir

            paths = [str(member.artifacts_dir) for member in roster]
            snapshot = scan_agent_artifact_dirs(
                sase_projects_dir(),
                paths,
                AgentArtifactScanOptionsWire(
                    include_prompt_step_markers=False,
                    include_raw_prompt_snippets=False,
                ),
            )
            targeted = running_from_snapshot(snapshot)

            def list_running() -> list[Any]:
                return list(targeted)
        except Exception:
            return rows
    try:
        for row in list_running() or ():
            if row not in rows:
                rows.append(row)
    except Exception:
        pass
    return rows


def _row_for_member(rows: list[Any], name: str, artifacts_dir: str) -> Any | None:
    wanted = _canonical_path(artifacts_dir)
    for row in rows:
        row_path = value(row, "artifacts_dir")
        if row_path and _canonical_path(str(row_path)) == wanted:
            return row
    return next((row for row in rows if value(row, "name") == name), None)


def _project_fields(member: Any) -> tuple[str, str, str, bool]:
    from sase.agent.running import named_agent_project_fields

    try:
        _artifacts, project_name, project_file, timestamp, is_home = (
            named_agent_project_fields(member)
        )
        return str(project_name), str(project_file), str(timestamp), bool(is_home)
    except (OSError, RuntimeError, ValueError):
        artifacts = Path(str(getattr(member, "artifacts_dir", "")))
        return "", "", artifacts.name, False


def _claims_for_project(project_file: str) -> list[Any]:
    if not project_file:
        return []
    try:
        from sase.running_field import get_claimed_workspaces

        return list(get_claimed_workspaces(project_file))
    except (OSError, RuntimeError, ValueError):
        return []


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    from sase.agent.hijack._stop_models import read_json_dict

    return read_json_dict(Path(artifacts_dir) / "agent_meta.json") or {}


def _process_alive(
    meta: dict[str, Any],
    artifacts_dir: Path,
    pid: int | None,
    deps: StopDeps,
) -> bool:
    if pid is None:
        return False
    check = deps.process_alive
    if check is None:
        from sase.agent.names import is_process_alive

        check = is_process_alive
    proof = dict(meta)
    # The workspace claim is authoritative when its owner differs from the
    # metadata PID. Ask the process identity helper to verify that exact PID;
    # otherwise a stale metadata PID could make a different claim look live.
    proof["pid"] = pid
    try:
        return bool(check(proof, artifacts_dir))
    except (OSError, RuntimeError, ValueError):
        return False


def _status(row: Any | None, process_alive: bool) -> str:
    status = text(value(row, "status"))
    if status:
        status = status.upper()
        if not process_alive and status in _LIVE_STATUSES:
            return "LOST"
        return status
    return "RUNNING" if process_alive else "DONE"


def _monitor_followup_pending(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    occupying_kind: str,
    monitor_state: str | None,
    done_outcome: str | None,
) -> bool:
    """Return whether a monitor still owns an undelivered follow-up.

    Uses settlement/delivery records and a frozen continue policy. A
    ``monitor_next_action`` string alone is not evidence of a pending handoff.
    """
    if occupying_kind != "monitor":
        return False
    outcome = text(meta.get("monitor_followup_outcome"))
    if outcome in _TERMINAL_FOLLOWUP_OUTCOMES:
        return False
    dispositions: set[str] = set()
    try:
        from sase.monitor.delivery import load_delivery_records

        records = load_delivery_records(artifacts_dir)
    except Exception:
        records = []
    for record in records:
        disposition = record.get("disposition") if isinstance(record, dict) else None
        if isinstance(disposition, str) and disposition:
            dispositions.add(disposition)
    if dispositions & _DELIVERED_DISPOSITIONS:
        return False
    if dispositions & _PENDING_DISPOSITIONS:
        return True
    command_settled = done_outcome is not None or (
        monitor_state in _TERMINAL_MONITOR_STATES
    )
    if not command_settled:
        return False
    frozen = meta.get("continuation_frozen_policy")
    if not isinstance(frozen, dict):
        try:
            from sase.continuation_capture.policy import load_frozen_outcome_policy

            frozen = load_frozen_outcome_policy(artifacts_dir)
        except Exception:
            frozen = None
    if not isinstance(frozen, dict):
        return False
    try:
        from sase.monitor.outcome_policy import settlement_policy_decision

        decision = settlement_policy_decision(
            artifacts_dir, meta, monitor_state or "completed"
        )
    except Exception:
        return False
    action = decision.get("action")
    next_action = decision.get("next_action")
    return (
        action == "continue"
        and isinstance(next_action, str)
        and bool(next_action.strip())
    )


def _monitor_state(meta: dict[str, Any], row: Any | None) -> str | None:
    state = nested_text(meta, "agent_session_turn", "state")
    return state or text(meta.get("monitor_state")) or text(value(row, "monitor_state"))


def _occupying_kind(
    meta: dict[str, Any],
    row: Any | None,
    status: str,
    *,
    is_monitor: bool,
    is_gate: bool,
) -> str:
    if is_monitor:
        return "monitor"
    if is_gate:
        return "gate"
    if status in _WAITING_STATUSES:
        return "wait" if status == "WAITING" else "queue"
    if _is_workflow_step(meta, row):
        return "workflow_step"
    from sase.plan_chain import turn_kind_value

    kind = turn_kind_value(meta)
    if isinstance(kind, str) and kind.lower() in {"agent", "llm"}:
        return "llm"
    has_model_target = any(
        isinstance(meta.get(key), str) and meta.get(key)
        for key in ("llm_provider", "exec_llm_provider", "agent_llm_provider", "model")
    )
    if has_model_target:
        return "llm"
    if status in {"STARTING", "LOST", "DONE", "STOPPED", "FAILED"} and text(
        meta.get("lifecycle_phase")
    ) in {
        "booting",
        "preparing",
    }:
        return "llm"
    if "hijack" in capabilities(meta) and status != "STARTING":
        return "llm"
    return "none"


def _is_workflow_step(meta: dict[str, Any], row: Any | None) -> bool:
    if bool(value(row, "is_workflow_step_child", False)):
        return True
    step_type = text(meta.get("step_type") or meta.get("workflow_step_type"))
    return (
        step_type in {"python", "bash", "parallel"}
        or meta.get("is_workflow_step") is True
    )


def _is_named_proc(meta: dict[str, Any], *, is_monitor: bool, is_gate: bool) -> bool:
    if is_monitor or is_gate:
        return False
    role = text(meta.get("proc_role"))
    return role == "proc" or bool(text(meta.get("named_proc")))


def _pid(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 1
        else None
    )


def _canonical_path(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return path


__all__ = [
    "resolve_hijack_subject",
]

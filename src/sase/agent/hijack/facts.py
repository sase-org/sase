"""Resolve a hijack request to its occupying turn and build backend facts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_done_marker
from sase.agent.hijack._stop_target import classify_turn, resolve_direct_target

LOG = logging.getLogger(__name__)

_LIVE_STATUSES = frozenset({"STARTING", "RUNNING", "RETRYING"})
_WAITING_STATUSES = frozenset({"WAITING", "QUEUED"})
_TERMINAL_STATUSES = frozenset({"DONE", "FAILED", "HIJACKED", "STOPPED", "LOST"})


@dataclass
class _MemberFacts:
    """Durable and live facts for one possible session occupant."""

    member: Any
    name: str
    artifacts_dir: str
    timestamp: str
    meta: dict[str, Any]
    row: Any | None
    claim: Any | None
    status: str
    pid: int | None
    process_alive: bool
    done_outcome: str | None
    is_home: bool
    occupying_kind: str
    turn_phase: str | None
    finalizer_phase: str | None
    gate_state: str | None
    monitor_state: str | None
    settled: bool
    in_flight: bool
    waiting: bool


@dataclass
class _HijackSubject:
    """One requested identity resolved to its current occupying member."""

    requested_name: str
    target: HijackTarget | None
    selected: _MemberFacts | None
    context: _MemberFacts | None
    members: tuple[_MemberFacts, ...]
    session: Any | None
    occupant_reason: str
    is_session_container: bool
    is_named_proc: bool
    is_clan_container: bool
    is_remote: bool
    is_bulk: bool
    row: Any | None
    found: bool

    @property
    def occupant_name(self) -> str | None:
        return None if self.selected is None else self.selected.name


def resolve_hijack_subject(
    name_or_row: str | Any,
    *,
    deps: StopDeps | None = None,
) -> _HijackSubject:
    """Resolve a member, session name, or session-container row to its occupant."""
    deps = deps or StopDeps()
    row = None if isinstance(name_or_row, str) else name_or_row
    requested_name = _input_name(name_or_row)

    from sase.agent.names import (
        NamedAgent,
        find_agent_clan,
        find_agent_session,
        find_agent_session_by_member_artifact_dir,
    )

    find_agent = deps.find_agent or _default_find_agent
    raw_artifacts_dir = _value(row, "artifacts_dir")
    artifacts_dir = (
        str(raw_artifacts_dir) if isinstance(raw_artifacts_dir, (str, Path)) else None
    )
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
        try:
            member_session = find_agent_session_by_member_artifact_dir(artifacts_dir)
        except (OSError, RuntimeError, ValueError):
            member_session = None
        if member_session is not None:
            session = member_session[0]
    if session is None and found_agent is not None:
        try:
            member_session = find_agent_session_by_member_artifact_dir(
                found_agent.artifacts_dir
            )
        except (OSError, RuntimeError, ValueError):
            member_session = None
        if member_session is not None:
            session = member_session[0]
    if session is None:
        try:
            session = find_agent_session(requested_name)
        except (OSError, RuntimeError, ValueError):
            session = None

    if session is not None:
        roster: tuple[Any, ...] = tuple(session.members)
        if not roster and session.root is not None:
            roster = (session.root,)
    elif found_agent is not None:
        roster = (found_agent,)
    else:
        roster = ()

    running_rows = _running_rows(deps, row)
    claims_by_project: dict[str, list[Any]] = {}
    member_facts: list[_MemberFacts] = []
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
            pid = _pid(_value(live_row, "pid"))
        process_alive = _process_alive(member_meta, Path(member_artifacts), pid, deps)
        status = _status(live_row, process_alive)
        done_outcome, _ = read_done_marker(member_artifacts)
        done_outcome = done_outcome or _text(getattr(member, "outcome", None))
        is_monitor, is_gate, gate_state = classify_turn(member_meta)
        monitor_state = _monitor_state(member_meta, live_row)
        turn_phase = _text(member_meta.get("lifecycle_phase"))
        finalizer_phase = _nested_text(member_meta, "finalizer_status", "phase")
        occupying_kind = _occupying_kind(
            member_meta,
            live_row,
            status,
            is_monitor=is_monitor,
            is_gate=is_gate,
        )
        pre_provider = turn_phase in {"booting", "waiting", "preparing"}
        settled = done_outcome is not None or (
            status in _TERMINAL_STATUSES and not pre_provider
        )
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
            _MemberFacts(
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
            )
        )

    ordered = tuple(sorted(member_facts, key=lambda item: item.timestamp))
    selection_request = {
        "schema_version": _eligibility_schema_version(),
        "members": [
            {
                "name": member.name,
                "status": member.status,
                "holds_claim": _has_numbered_claim(member.claim),
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
        _value(row, "is_agent_session_container_row", False)
        or _value(row, "is_session_container", False)
        or (session is not None and requested_name == session.base_name)
    )
    is_named_proc = bool(_value(row, "is_named_proc", False)) or (
        context is not None
        and _is_named_proc(
            context.meta,
            is_monitor=context.occupying_kind == "monitor",
            is_gate=context.occupying_kind == "gate",
        )
    )
    is_clan_container = bool(
        _value(row, "is_clan_container", False) or _value(row, "is_clan", False)
    )
    if not is_clan_container:
        try:
            is_clan_container = find_agent_clan(requested_name) is not None
        except (OSError, RuntimeError, ValueError):
            is_clan_container = False
    is_remote = bool(
        _value(row, "is_remote", False)
        or _value(row, "fleet_origin_alias", None)
        or _value(row, "is_remote_agent_session_container", False)
    )
    is_bulk = bool(
        _value(row, "is_bulk", False)
        or _value(row, "is_bulk_marked", False)
        or _value(row, "bulk_marked", False)
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
            else _text(context.meta.get("agent_session"))
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

    return _HijackSubject(
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


def _build_hijack_facts(subject: _HijackSubject) -> dict[str, Any]:
    """Compute the v2 decision wire from the subject's observed records."""
    member = subject.selected or subject.context
    target = subject.target
    claim = None if member is None else member.claim
    workspace_num = _positive_int(getattr(claim, "workspace_num", None))
    done_outcome = None if member is None else member.done_outcome
    active_state = _active_hijack_state(target)
    is_home = (
        target.is_home if target is not None else member.is_home if member else False
    )
    return {
        "schema_version": _eligibility_schema_version(),
        "is_local": not subject.is_remote,
        "is_remote": subject.is_remote,
        "is_bulk": subject.is_bulk,
        "is_named_proc": subject.is_named_proc,
        "is_home_mode": is_home,
        "is_clan_container": subject.is_clan_container,
        "is_session_container": subject.is_session_container,
        "live_member_count": sum(not item.settled for item in subject.members),
        "occupying_kind": (
            member.occupying_kind if member is not None and subject.selected else "none"
        ),
        "status": member.status if member is not None and subject.selected else None,
        "turn_phase": member.turn_phase
        if member is not None and subject.selected
        else None,
        "finalizer_phase": (
            member.finalizer_phase if member is not None and subject.selected else None
        ),
        "gate_state": member.gate_state
        if member is not None and subject.selected
        else None,
        "monitor_state": (
            member.monitor_state if member is not None and subject.selected else None
        ),
        "workspace_num": workspace_num,
        "has_numbered_claim": workspace_num is not None,
        "pid": member.pid if member is not None and subject.selected else None,
        "process_alive": (
            member.process_alive if member is not None and subject.selected else False
        ),
        "has_hijack_capability": bool(
            member is not None and "hijack" in _capabilities(member.meta)
        ),
        "successor_attachable": bool(
            subject.selected is not None
            and (
                subject.session is not None
                or (target and target.agent_session)
                or _promotion_preconditions_hold(member)
            )
        ),
        "done_outcome": done_outcome,
        "active_hijack_state": active_state,
    }


def decide(subject: _HijackSubject) -> dict[str, Any]:
    """Call the Rust v2 decision and attach it to the selected target."""
    from sase.agent.hijack.core import agent_hijack_decide

    facts = _build_hijack_facts(subject)
    decision = agent_hijack_decide(facts)
    if (
        not subject.found
        and not subject.is_remote
        and not subject.is_bulk
        and not subject.is_named_proc
        and not subject.is_clan_container
    ):
        decision = {
            **decision,
            "mode": "refused",
            "eligible": False,
            "code": "not_found",
            "message": f"no agent or session found with name '{subject.requested_name}'",
            "next_action": "check the name with `sase agent list`",
            "redirect_op": None,
            "adapter": None,
        }
    if subject.target is not None:
        subject.target.decision = decision
    LOG.info(
        "agent_hijack_decision mode=%s code=%s member=%s requested=%s",
        decision.get("mode") or "unknown",
        decision.get("code") or "-",
        subject.occupant_name or "-",
        subject.requested_name,
    )
    return decision


def resolve_and_decide(
    name_or_row: str | Any,
    *,
    deps: StopDeps | None = None,
) -> tuple[_HijackSubject, dict[str, Any]]:
    """Resolve one request and evaluate the same facts used by stop and explain."""
    subject = resolve_hijack_subject(name_or_row, deps=deps)
    return subject, decide(subject)


def _default_find_agent(name: str) -> Any | None:
    from sase.agent.names import find_named_agent

    return find_named_agent(name, include_dead=True)


def _input_name(name_or_row: str | Any) -> str:
    if isinstance(name_or_row, str):
        return name_or_row
    for field in ("presented_agent_name", "agent_name", "name"):
        value = _text(_value(name_or_row, field))
        if value:
            return value
    return ""


def _running_rows(deps: StopDeps, input_row: Any | None) -> list[Any]:
    rows: list[Any] = []
    if input_row is not None and _value(input_row, "artifacts_dir"):
        rows.append(input_row)
    list_running = deps.list_running
    if list_running is None:
        try:
            from sase.agent.running_listing import list_running_agents

            list_running = list_running_agents
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
        row_path = _value(row, "artifacts_dir")
        if row_path and _canonical_path(str(row_path)) == wanted:
            return row
    return next((row for row in rows if _value(row, "name") == name), None)


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
    status = _text(_value(row, "status"))
    if status:
        status = status.upper()
        if not process_alive and status in _LIVE_STATUSES:
            return "LOST"
        return status
    return "RUNNING" if process_alive else "DONE"


def _monitor_state(meta: dict[str, Any], row: Any | None) -> str | None:
    value = _nested_text(meta, "agent_session_turn", "state")
    return (
        value or _text(meta.get("monitor_state")) or _text(_value(row, "monitor_state"))
    )


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
    if status in {"STARTING", "LOST", "DONE", "STOPPED", "FAILED"} and _text(
        meta.get("lifecycle_phase")
    ) in {
        "booting",
        "preparing",
    }:
        return "llm"
    if "hijack" in _capabilities(meta) and status != "STARTING":
        return "llm"
    return "none"


def _is_workflow_step(meta: dict[str, Any], row: Any | None) -> bool:
    if bool(_value(row, "is_workflow_step_child", False)):
        return True
    step_type = _text(meta.get("step_type") or meta.get("workflow_step_type"))
    return (
        step_type in {"python", "bash", "parallel"}
        or meta.get("is_workflow_step") is True
    )


def _is_named_proc(meta: dict[str, Any], *, is_monitor: bool, is_gate: bool) -> bool:
    if is_monitor or is_gate:
        return False
    role = _text(meta.get("proc_role"))
    return role == "proc" or bool(_text(meta.get("named_proc")))


def _capabilities(meta: dict[str, Any]) -> list[str]:
    value = meta.get("runner_capabilities")
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def _active_hijack_state(target: HijackTarget | None) -> str | None:
    if target is None:
        return None
    try:
        from sase.agent.hijack import ledger

        record = ledger.load_record_by_artifacts_dir(target.artifacts_dir)
    except (OSError, RuntimeError, ValueError):
        return None
    return _text(None if record is None else record.get("state"))


def _eligibility_schema_version() -> int:
    from sase.agent.hijack.core import agent_hijack_eligibility_wire_schema_version

    return agent_hijack_eligibility_wire_schema_version()


def _has_numbered_claim(claim: Any | None) -> bool:
    return _positive_int(getattr(claim, "workspace_num", None)) is not None


def _promotion_preconditions_hold(member: Any | None) -> bool:
    """Return whether a sessionless predecessor could be promoted.

    Keep-work recovery promotes a bare agent into a session with the
    existing ``promote_agent_to_agent_session`` helper before attaching
    the successor. A stop is only accepted when that promotion could run,
    so Continue never follows a stop that cannot be recovered: the
    predecessor needs a readable meta with a bare name and an artifacts
    directory that could host the session container.
    """
    if member is None:
        return False
    meta = getattr(member, "meta", None)
    if not isinstance(meta, dict):
        return False
    name = meta.get("name")
    if not isinstance(name, str) or not name:
        return False
    artifacts_dir = getattr(member, "artifacts_dir", None)
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return False
    # Already sessioned members attach without promotion; bare names with
    # no session marker are promotable. A conflicting session marker that
    # is not the member's own session fails closed elsewhere.
    return True


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _pid(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 1
        else None
    )


def _nested_text(value: dict[str, Any], *keys: str) -> str | None:
    nested: Any = value
    for key in keys:
        nested = nested.get(key) if isinstance(nested, dict) else None
    return _text(nested)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _canonical_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return value


__all__ = [
    "decide",
    "resolve_and_decide",
    "resolve_hijack_subject",
]

"""Cancel / force chooser for a still-pending hijack latch."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from rich.text import Text

from ...models.agent import Agent
from ...models.agent_hijack_presentation import pending_hijack_boundary
from ...modals.agent_action_chooser_modal import (
    AgentActionChoice,
    AgentActionChooserModal,
)

_RESULT_PREFIX = "pending:"
_CANCEL_RESULT = f"{_RESULT_PREFIX}cancel"
_FORCE_RESULT = f"{_RESULT_PREFIX}now"
_FORCE_WARNING = "effect uncertain — finalizer interrupted; inspect the snapshot"
_KEEP_STYLE = "bold #FF5FAF"
_FORCE_STYLE = "bold #FF5F5F"


def _pending_latch_force_eligible(
    record: Mapping[str, Any] | None,
    *,
    now: float | None = None,
) -> bool:
    """Return whether the in-memory latch record is old enough to force."""
    if not isinstance(record, Mapping) or record.get("state") != "latched":
        return False
    try:
        from sase.agent.hijack import core

        eligibility = core.hijack_latch_force_eligibility(
            dict(record), float(time.time() if now is None else now)
        )
    except Exception:
        return False
    return eligibility.get("eligible") is True


def _pending_hijack_choices(
    record: Mapping[str, Any],
    *,
    now: float | None = None,
) -> tuple[AgentActionChoice, ...]:
    """Return Cancel, plus Hijack now when the 120-second force bound has elapsed."""
    choices: list[AgentActionChoice] = [
        AgentActionChoice(
            result=_CANCEL_RESULT,
            section="hijack_keep",
            label="Cancel hijack",
            detail="release this latch; the occupant keeps running",
            glyph="✕",
            glyph_style=_KEEP_STYLE,
            badge=None,
            badge_style=None,
            age=None,
            hotkey="c",
            inline_detail=True,
        )
    ]
    if _pending_latch_force_eligible(record, now=now):
        choices.append(
            AgentActionChoice(
                result=_FORCE_RESULT,
                section="hijack_fresh",
                label="Hijack now",
                detail=_FORCE_WARNING,
                glyph="⚡",
                glyph_style=_FORCE_STYLE,
                badge=None,
                badge_style=None,
                age=None,
                hotkey="n",
                inline_detail=True,
            )
        )
    return tuple(choices)


def open_pending_hijack_panel(app: Any, agent: Agent) -> bool:
    """Open cancel/force choices from the row's worker-cached latch record."""
    record = getattr(agent, "hijack_record", None)
    if not isinstance(record, Mapping) or record.get("state") != "latched":
        app.notify(
            "Pending hijack details are unavailable; refresh the Agents tab",
            severity="warning",
        )
        return False
    record = dict(record)
    choices = _pending_hijack_choices(record)
    name = agent.presented_agent_name or agent.agent_name or agent.cl_name
    boundary = pending_hijack_boundary(record)
    header = Text()
    header.append(f"after {boundary}", style="bold")
    workspace_num = record.get("workspace_num")
    if isinstance(workspace_num, int):
        header.append(f" · workspace #{workspace_num}", style="dim")
    subtitles = {"hijack_keep": "the occupant keeps running"}
    if any(choice.result == _FORCE_RESULT for choice in choices):
        subtitles["hijack_fresh"] = _FORCE_WARNING
    modal = AgentActionChooserModal(
        choices,
        title=f"⏏ Pending hijack · {name}",
        title_badge="PENDING",
        header=header,
        section_subtitles=subtitles,
        primary_result=_CANCEL_RESULT,
        initial_index=0,
        footer_text="j/k move · ⏎ select · Esc leave pending",
    )
    identity = tuple(agent.identity)

    def _on_choice(result: str | None) -> None:
        if result is None:
            return
        current = _row_for_identity(app, identity) or agent
        if result == _CANCEL_RESULT:
            _submit_pending_action(app, current, record, action="cancel")
            return
        if result == _FORCE_RESULT:
            _submit_pending_action(app, current, record, action="now")

    app.push_screen(modal, _on_choice)
    return True


def _submit_pending_action(
    app: Any,
    agent: Agent,
    record: Mapping[str, Any],
    *,
    action: str,
) -> None:
    from ..agent_durable import submit_agent_hijack

    name = agent.agent_name
    if not isinstance(name, str) or not name:
        app.notify("Selected row has no local agent name", severity="error")
        return
    hijack_id = record.get("hijack_id")
    target_key = record.get("target_key")
    session_name = _session_name(agent)
    display = (
        f"Cancel hijack {agent.display_name}"
        if action == "cancel"
        else f"Hijack now {agent.display_name}"
    )
    identity = tuple(agent.identity)

    def on_complete(completion: Any) -> None:
        current = _row_for_identity(app, identity) or agent
        apply_hijack_proc_completion(app, current, current, completion)

    submitted = submit_agent_hijack(
        app,
        name=name,
        identity=str(agent.identity),
        cl_name=agent.cl_name,
        project_file=agent.project_file,
        display_name=display,
        session_name=session_name,
        action=action,
        hijack_id=hijack_id if isinstance(hijack_id, str) else None,
        target_key=target_key if isinstance(target_key, str) else None,
        on_complete=on_complete,
    )
    if not submitted:
        app.notify("Could not queue the hijack operation", severity="error")


def apply_hijack_proc_completion(
    app: Any,
    occupant: Agent,
    selected: Agent,
    completion: Any,
) -> None:
    """Apply a durable persist-hijack result without treating latches as stop errors."""
    raw_payload = getattr(completion, "payload", None)
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    status = payload.get("status") if isinstance(payload, dict) else None
    occupant.hijack_stop_failed = status == "stop_failed"
    if status in {"latched", "pending"}:
        occupant.hijack_overlay = "pending"
        occupant.hijack_stop_failed = False
        record = payload.get("record")
        if isinstance(record, dict):
            occupant.hijack_record = dict(record)
        hijack_id = payload.get("hijack_id")
        if isinstance(hijack_id, str) and hijack_id:
            occupant.hijack_id = hijack_id
    elif status in {"requested", "stopping"}:
        occupant.hijack_overlay = "hijacking"
        occupant.hijack_stop_failed = False
    elif status in {"cancelled", "finished_first", "moot", "held", "applied"}:
        occupant.hijack_overlay = None
        occupant.hijack_stop_failed = False
    elif status in {"refused", "error", "ownership_uncertain"}:
        occupant.hijack_stop_failed = False
    else:
        occupant.hijack_overlay = None
    if selected.identity != occupant.identity:
        selected.hijack_overlay = occupant.hijack_overlay
        selected.hijack_stop_failed = occupant.hijack_stop_failed
        selected.hijack_record = occupant.hijack_record
        selected.hijack_id = occupant.hijack_id
    refresh = getattr(app, "_refresh_hijack_row", None)
    if callable(refresh):
        refresh(occupant)
        if selected.identity != occupant.identity:
            refresh(selected)
    message = getattr(completion, "message", None)
    if status in {"finished_first", "moot"}:
        message = "finished before the hijack; nothing was held"
    elif status in {"latched", "pending"} and not message:
        message = "Hijack latched; waiting for a safe boundary"
    severity = payload.get("severity") if isinstance(payload, dict) else None
    if status in {"latched", "pending", "cancelled", "finished_first", "moot"}:
        severity = "information"
    if severity not in {"warning", "error", "information"}:
        severity = "information" if getattr(completion, "success", False) else "warning"
    if message:
        app.notify(message, severity=severity)
    refresh_source = (
        payload.get("schedule_agents_refresh_source")
        if isinstance(payload, dict)
        else None
    )
    if isinstance(refresh_source, str):
        schedule = getattr(app, "_schedule_agents_async_refresh", None)
        if callable(schedule):
            schedule(source=refresh_source)


def _row_for_identity(app: Any, identity: tuple[object, ...]) -> Agent | None:
    resolver = getattr(app, "_hijack_row_for_identity", None)
    if callable(resolver):
        found = resolver(identity)
        if found is not None:
            return found
    resolver = getattr(app, "_agent_by_identity", None)
    if callable(resolver):
        return resolver(identity)
    return None


def _session_name(agent: Agent) -> str | None:
    try:
        session_candidate = getattr(agent, "agent_session", None)
        if isinstance(session_candidate, str) and session_candidate:
            return session_candidate
        if getattr(agent, "is_agent_session_root_entry", False):
            reference = agent.agent_session_reference_name()
            if isinstance(reference, str) and reference:
                return reference
    except Exception:
        return None
    return None


__all__ = [
    "apply_hijack_proc_completion",
    "open_pending_hijack_panel",
]

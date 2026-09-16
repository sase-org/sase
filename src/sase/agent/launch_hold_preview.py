"""Predicate: does a submitted prompt's ``%hold`` need interactive confirmation.

A hold is "broad" -- and needs a human to confirm arming it -- when it either
combines ``future`` with ``scope=host`` (every project's future launches), or
its frozen ``pending`` capture would exceed
``agent_hold_confirm_capture_threshold``. Narrow, single-name holds never
need confirmation.

This module is presentation glue: it turns already-parsed hold fields into a
confirmation decision and a human-readable body. The TUI and ``sase run``
both call it from a raw submitted prompt so their confirm gates agree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

HOLD_DIRECTIVE_MARKER = "%hold"


def prompt_mentions_hold(prompt: str) -> bool:
    """Cheap substring check that keeps the no-hold fast path allocation-free."""
    return HOLD_DIRECTIVE_MARKER in prompt


def hold_confirmation_body(prompt: str, *, project: str | None = None) -> str | None:
    """Return a confirmation body when *prompt* would arm a broad hold.

    Returns ``None`` when the prompt carries no hold, every hold is narrow,
    or the hold directive fails to parse (real validation happens at launch
    time; this preflight is best-effort).
    """
    if not prompt_mentions_hold(prompt):
        return None
    from sase.config.core import get_agent_hold_confirm_capture_threshold

    threshold = get_agent_hold_confirm_capture_threshold()
    descriptions: list[str] = []
    for label, hold, hold_project in _iter_prompt_holds(prompt, project=project):
        if _hold_is_broad(hold, project=hold_project, threshold=threshold):
            descriptions.append(_broad_hold_description(label, hold, hold_project))
    if not descriptions:
        return None
    return "\n\n".join(descriptions)


def _iter_prompt_holds(
    prompt: str, *, project: str | None
) -> list[tuple[str, Mapping[str, Any], str | None]]:
    """Enumerate ``(label, hold_fields, project)`` for every unit in *prompt*."""
    from sase.xprompt.code_value import typed_launch_units_enabled

    if typed_launch_units_enabled() and ("%if" in prompt or "%proc" in prompt):
        return _typed_prompt_holds(prompt)
    return _non_typed_prompt_holds(prompt, project=project)


def _typed_prompt_holds(
    prompt: str,
) -> list[tuple[str, Mapping[str, Any], str | None]]:
    from sase.agent.launch_request_planning import (
        expand_prompt_for_typed_launch,
        prepare_typed_launch_plan,
        resolve_typed_launch_selected_project,
    )
    from sase.agent.launch_request_types import LaunchRequestError

    try:
        expanded = expand_prompt_for_typed_launch(prompt)
        selected_project = resolve_typed_launch_selected_project(expanded)
        typed_plan = prepare_typed_launch_plan(
            expanded, selected_project=selected_project
        )
    except (LaunchRequestError, TypeError, ValueError):
        return []
    project = typed_plan.get("selected_project")
    project = project if isinstance(project, str) else None
    entries: list[tuple[str, Mapping[str, Any], str | None]] = []
    for unit in typed_plan.get("units") or []:
        if not isinstance(unit, Mapping):
            continue
        payload = unit.get("payload")
        if not isinstance(payload, Mapping):
            continue
        hold = payload.get("hold")
        if not isinstance(hold, Mapping) or not hold:
            continue
        entries.append((_typed_unit_hold_label(unit, payload), hold, project))
    return entries


def _typed_unit_hold_label(unit: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    logical_id = str(unit.get("logical_id") or "")
    if payload.get("kind") == "proc":
        name = payload.get("shell_name") or payload.get("label") or logical_id
        return f"proc `{name}`"
    name = payload.get("identity") or logical_id
    return f"agent `{name}`"


def _non_typed_prompt_holds(
    prompt: str, *, project: str | None
) -> list[tuple[str, Mapping[str, Any], str | None]]:
    from sase.agent.launch_guard import plan_launch_units
    from sase.xprompt.directives import extract_prompt_directives

    entries: list[tuple[str, Mapping[str, Any], str | None]] = []
    try:
        units = plan_launch_units(prompt)
    except Exception:  # noqa: BLE001 - preflight is best-effort.
        units = ()
    for unit in units:
        for candidate in unit.candidates:
            try:
                _, directives = extract_prompt_directives(candidate.prompt)
            except Exception:  # noqa: BLE001 - preflight is best-effort.
                continue
            if not directives.hold:
                continue
            label = f"agent {unit.index} of {unit.total}"
            entries.append((label, dict(directives.hold), project))
    return entries


def _hold_is_broad(
    hold: Mapping[str, Any], *, project: str | None, threshold: int
) -> bool:
    scope = str(hold.get("scope") or "project")
    if hold.get("future") and scope == "host":
        return True
    if not hold.get("pending"):
        return False
    if scope == "project" and project is None:
        return False
    from sase.core.agent_hold_facade import preview_pending_capture

    capture = preview_pending_capture(scope, project=project)
    if capture is None:
        return False
    return (capture.waiting_count + capture.queued_count) > threshold


def _broad_hold_description(
    label: str, hold: Mapping[str, Any], project: str | None
) -> str:
    from sase.core.agent_hold_facade import (
        format_pending_capture,
        preview_pending_capture,
    )
    from sase.xprompt.hold_directive import format_hold_directive

    directive = format_hold_directive(dict(hold)) or HOLD_DIRECTIVE_MARKER
    scope = str(hold.get("scope") or "project")
    lines = [f"{label}: `{directive}`"]
    if hold.get("pending"):
        capture_text = format_pending_capture(
            preview_pending_capture(scope, project=project)
        )
        if capture_text:
            lines.append(capture_text)
    if hold.get("future") and scope == "host":
        lines.append(
            "warning: `future` combined with `scope=host` holds every "
            "project's future launches."
        )
    return "\n".join(lines)


__all__ = [
    "HOLD_DIRECTIVE_MARKER",
    "hold_confirmation_body",
    "prompt_mentions_hold",
]

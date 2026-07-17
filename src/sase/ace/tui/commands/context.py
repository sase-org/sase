"""Live :class:`CommandContext` extraction from a running :class:`AceApp`.

This is the Phase 3 adapter that turns the app's stateful selection
into the small immutable bag of state that
:func:`is_command_available` reads. It keeps the predicate module
free of any reference to the live app object.

The extractor is intentionally defensive:

- Missing/uninitialized state (e.g. ``_axe_items`` empty during
  startup) yields conservative defaults rather than raising.
- Helper widgets that do not exist yet in the current tab (e.g. the
  agent detail panel before agents have been loaded) are looked up
  inside ``try``/``except`` so the palette can still open during
  early lifecycle windows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.models.agent_status import (
    is_stopped_agent_status,
    is_unread_completed_status,
)
from sase.ace.tui.commands.types import CommandContext, CommandTab
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem, ChopItem

if TYPE_CHECKING:
    from sase.ace.tui.app import AceApp


def _safe_index(items: list[Any], idx: int) -> Any | None:
    if 0 <= idx < len(items):
        return items[idx]
    return None


def _selected_changespec(app: AceApp):  # type: ignore[no-untyped-def]
    return _safe_index(app.changespecs, app.current_idx)


def _selected_agent(app: AceApp):  # type: ignore[no-untyped-def]
    agents = getattr(app, "_agents", [])
    return _safe_index(agents, app.current_idx)


def _selected_axe_item(app: AceApp):  # type: ignore[no-untyped-def]
    items = getattr(app, "_axe_items", [])
    return _safe_index(items, app.current_idx)


def _can_jump_to_changespec(app: AceApp, agent) -> bool:  # type: ignore[no-untyped-def]
    if agent is None:
        return False
    resolver = getattr(app, "_resolve_agent_cl_name", None)
    if resolver is None:
        return False
    try:
        return resolver(agent) is not None
    except Exception:
        return False


def _file_panel_visible(app: AceApp) -> bool:  # type: ignore[no-untyped-def]
    if app.current_tab != "agents":
        return False
    try:
        from sase.ace.tui.widgets import AgentDetail

        panel = app.query_one("#agent-detail-panel", AgentDetail)
        return bool(panel.is_file_visible())
    except Exception:
        return False


def _has_agent_artifacts(app: AceApp, agent) -> bool:  # type: ignore[no-untyped-def]
    if app.current_tab != "agents":
        return False
    try:
        lister = getattr(app, "_list_selected_artifact_files", None)
        return (
            bool(lister(agent)) if lister is not None and agent is not None else False
        )
    except Exception:
        return False


def _completed_agent_count(app: AceApp) -> int:  # type: ignore[no-untyped-def]
    agents = getattr(app, "_agents", [])
    return sum(1 for a in agents if is_unread_completed_status(a.status))


def _stopped_agent_count(app: AceApp) -> int:  # type: ignore[no-untyped-def]
    agents = getattr(app, "_agents", [])
    return sum(1 for a in agents if is_stopped_agent_status(a.status))


def _unread_completed_agent_count(app: AceApp) -> int:  # type: ignore[no-untyped-def]
    agents = getattr(app, "_agents", [])
    unread_ids: set[object] = getattr(app, "_unread_completed_agent_ids", set())
    return sum(
        1
        for a in agents
        if is_unread_completed_status(a.status)
        and getattr(a, "identity", None) in unread_ids
    )


def _agents_mark_count(app: AceApp) -> int:  # type: ignore[no-untyped-def]
    return len(getattr(app, "_marked_agents", set()))


def _runner_count(app: AceApp) -> int:  # type: ignore[no-untyped-def]
    slots = getattr(app, "_bgcmd_slots", [])
    return len(slots)


def _selected_axe_slot_states(app: AceApp, item) -> tuple[bool, bool]:  # type: ignore[no-untyped-def]
    """Return ``(is_done, is_running)`` for a selected bgcmd slot.

    ``(False, False)`` for non-bgcmd rows or when the slot has no
    info.
    """
    if not isinstance(item, BgCmdItem):
        return (False, False)
    slot = item.slot
    slots: list[tuple[int, object]] = getattr(app, "_bgcmd_slots", [])
    info = None
    for s, slot_info in slots:
        if s == slot:
            info = slot_info
            break
    if info is None:
        return (False, False)
    try:
        from sase.ace.tui.bgcmd import is_slot_running

        running = bool(is_slot_running(slot))
    except Exception:
        running = False
    # "Done" = there is a slot record but the process is no longer
    # running (i.e. it finished).
    return (not running, running)


def _selected_axe_chop_run_total(app: AceApp, item) -> int:  # type: ignore[no-untyped-def]
    if not isinstance(item, ChopItem):
        return 0
    snapshots = getattr(app, "_axe_chop_snapshots", {})
    snap = snapshots.get((item.lumberjack_name, item.chop_name))
    if snap is None:
        return 0
    return len(getattr(snap, "runs", []) or [])


def extract_command_context(app: AceApp) -> CommandContext:  # type: ignore[no-untyped-def]
    """Build a :class:`CommandContext` snapshot from the live ``AceApp``.

    Phase 3 of the command palette plan. This is the single adapter
    between the running app and the pure availability predicates so
    the predicates do not have to import ``AceApp``.
    """
    tab: CommandTab = app.current_tab  # type: ignore[assignment]

    cs = _selected_changespec(app) if tab == "changespecs" else None
    agent = _selected_agent(app) if tab == "agents" else None
    axe_item = _selected_axe_item(app) if tab == "axe" else None

    if tab == "agents":
        mark_count = _agents_mark_count(app)
    else:
        mark_count = len(getattr(app, "marked_indices", set()) or set())

    completed = _completed_agent_count(app) if tab == "agents" else 0
    stopped = _stopped_agent_count(app) if tab == "agents" else 0
    unread_completed = _unread_completed_agent_count(app) if tab == "agents" else 0
    can_jump = _can_jump_to_changespec(app, agent) if tab == "agents" else False
    attempt_pinned = (
        app.current_attempt_number is not None if tab == "agents" else False
    )
    group_focused = (
        getattr(app, "_current_group_key", None) is not None
        if tab == "agents"
        else False
    )
    file_panel = _file_panel_visible(app)
    has_artifact_files = _has_agent_artifacts(app, agent)

    if tab == "axe":
        done, running = _selected_axe_slot_states(app, axe_item)
        chop_run_total = _selected_axe_chop_run_total(app, axe_item)
    else:
        done, running = (False, False)
        chop_run_total = 0

    return CommandContext(
        tab=tab,
        artifacts_subtab=getattr(app, "current_artifacts_subtab", "prs"),
        changespec=cs,
        agent=agent,
        axe_item=axe_item,
        mark_count=mark_count,
        completed_agent_count=completed,
        stopped_agent_count=stopped,
        unread_completed_agent_count=unread_completed,
        runner_count=_runner_count(app),
        can_jump_to_changespec=can_jump,
        attempt_pinned=attempt_pinned,
        group_focused=group_focused,
        file_panel_visible=file_panel,
        has_artifact_files=has_artifact_files,
        axe_running=bool(getattr(app, "axe_running", False)),
        selected_axe_slot_done=done and isinstance(axe_item, BgCmdItem),
        selected_axe_slot_running=running and isinstance(axe_item, BgCmdItem),
        selected_axe_chop_run_total=chop_run_total,
    )


__all__ = ["extract_command_context"]

"""Agents Archive action boundary: live guards, marks, footer, read targets.

Action-boundary seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``_get_selected_agent`` keeps its Inbox-only semantics; this module is the
single place that decides when the Archive owns the Agents tab and what a
live-only action must do instead. Live-only callers keep using
``_get_selected_agent`` and never see an archived row; read callers resolve
the hydrated Archive agent through :func:`archive_read_target`.

Caller audit (phase ``sase-1jm.3.1.6``; ``_get_selected_agent`` call sites in
``src/sase/ace/tui`` grouped by intent — live callers below are guarded,
read/navigation callers opt into the typed selection):

- read via typed selection (Archive-aware): deck selection/cycling/scroll
  readers, prompt/chat read access (``prompt_panel/_live_reply_follow`` stays
  live-only: it never follows an archived RUNNING row), copy readers in
  ``actions/clipboard/_agents.py`` and ``_palette._build_agent_context``,
  and the fork/copy parent seam (hydrated read target only, no chooser).
- live mutation (guarded with an explanatory toast): ``x`` kill,
  ``X`` cleanup panel, ``s`` save-marked group, ``w`` reword/wait,
  ``W`` wait-for, ``A`` accept/HITL/auto-approve, ``R`` retry, ``n`` rename,
  ``N`` tribe modal, ``U`` unread toggle, agent-tab ``[``/``]`` moves and
  the tab picker, bulk kill/wait paths over Inbox marks.
- view navigation (already Archive-routed, untouched): ``j k g G h l J K``
  and Enter via ``route_archive_key``.
- Inbox accounting (never consults Archive rows): unread/attention counts,
  ``load:``/runner slots, prospective clans, auto-dismiss, bare ``%wait``,
  live bulk actions, agent-tab totals, and Inbox marks. Archive marks live
  on ``ArchiveViewState.marks`` by stable identity and never enter those
  collections.
"""

from __future__ import annotations

from typing import Any

# Live-only Agents-tab action names: key dispatch guards each entry point
# and ``check_agents_availability`` hides the same names from the palette
# while the Archive owns the panel.
ARCHIVE_LIVE_ONLY_ACTIONS = frozenset(
    {
        "kill_agent",
        "open_agent_cleanup_panel",
        "save_marked_agents",
        "bulk_change_status",
        "reword",
        "add_tag",
        "wait_for_agent",
        "accept_proposal",
        "toggle_auto_approve",
        "agents_retry",
        "rename_cl",
        "edit_agent_tribe",
        "next_agents_tab",
        "prev_agents_tab",
        "pick_agents_tab",
        "toggle_agent_unread",
    }
)

# Fork/resume/copy and restore stay available as parent-phase seams: the
# parent fork/copy phase consumes ``archive_read_target`` for its chooser,
# and the parent restore phase owns Enter-restore. Blocking them here
# would shadow those later handlers.
ARCHIVE_PARENT_SEAM_ACTIONS = frozenset(
    {
        "fork_agent",
        "resume_agent",
        "act_on_agent",
    }
)

# Short key labels used in guard toasts. Anything unlisted falls back to the
# action name so a renamed key still explains itself.
_ARCHIVE_GUARD_KEY_LABELS = {
    "kill_agent": "x",
    "open_agent_cleanup_panel": "X",
    "save_marked_agents": "s",
    "bulk_change_status": "S",
    "reword": "w",
    "add_tag": "W",
    "wait_for_agent": "W",
    "accept_proposal": "A",
    "toggle_auto_approve": "A",
    "agents_retry": "R",
    "rename_cl": "n",
    "edit_agent_tribe": "N",
    "next_agents_tab": "]",
    "prev_agents_tab": "[",
    "pick_agents_tab": "tabs",
    "toggle_agent_unread": "U",
}

_TAB_GUARD_ACTIONS = frozenset(
    {"next_agents_tab", "prev_agents_tab", "pick_agents_tab"}
)
_TRIBE_GUARD_ACTIONS = frozenset({"edit_agent_tribe"})


def archive_ui_active(owner: Any) -> bool:
    """Return whether the Archive view currently owns the Agents tab."""
    try:
        from ._archive_view import archive_detail_owns_panel
    except Exception:
        return False
    try:
        return bool(archive_detail_owns_panel(owner))
    except Exception:
        return False


def _archive_guard_message(action: str, *, target_name: str | None = None) -> str:
    """Return the explanatory toast for a live-only action in the Archive."""
    key = _ARCHIVE_GUARD_KEY_LABELS.get(action, action)
    if action in _TAB_GUARD_ACTIONS:
        return "Agent tabs live in the Inbox · ,a"
    if action in _TRIBE_GUARD_ACTIONS:
        return "Tribes live in the Inbox · ,a"
    if target_name:
        return f"{key} acts on inbox agents — {target_name} is archived · ,a for inbox"
    return f"{key} acts on inbox agents — archived rows are read-only · ,a for inbox"


def _archive_selection_name(owner: Any) -> str | None:
    """Return the display name of the Archive selection, if it names a row."""
    try:
        from ._archive_view import get_agents_tab_selection
    except Exception:
        return None
    try:
        selection = get_agents_tab_selection(owner)
    except Exception:
        return None
    row = getattr(selection, "light_row", None)
    if row is not None:
        try:
            name = row.get("agent_name")
        except Exception:
            name = None
        if name:
            return str(name)
    agent = getattr(selection, "agent", None)
    for attr in ("presented_agent_name", "display_name", "cl_name"):
        try:
            value = getattr(agent, attr, None)
        except Exception:
            value = None
        if value:
            return str(value)
    return None


def guard_archive_live_action(owner: Any, action: str) -> bool:
    """Toast and return True when ``action`` is live-only and blocked.

    Returns False when the Inbox path may run. Never mutates parked Inbox
    state: callers return immediately on True before touching selection,
    marks, or unread collections.
    """
    if not archive_ui_active(owner):
        return False
    try:
        notify = getattr(owner, "notify", None)
        if callable(notify):
            notify(
                _archive_guard_message(
                    action, target_name=_archive_selection_name(owner)
                )
            )
    except Exception:
        pass
    return True


def archive_read_target(owner: Any) -> Any | None:
    """Return the hydrated Archive agent for read callers, else None.

    This is the seam the parent fork/copy phase consumes: a hydrated read
    target with no chooser and no new targets. Inbox callers keep using
    ``_get_selected_agent``; only read callers that explicitly need Archive
    rows call here. Returns None outside the Archive or when the selection
    is a banner, tail, pulse, or not-yet-hydrated row.
    """
    if not archive_ui_active(owner):
        return None
    try:
        from ._archive_view import get_agents_tab_selection
    except Exception:
        return None
    try:
        selection = get_agents_tab_selection(owner)
    except Exception:
        return None
    return getattr(selection, "agent", None)


def resolve_agents_read_agent(owner: Any) -> Any | None:
    """Return the Archive read target when active, else the Inbox selection.

    Copy readers and other read callers use this so Archive rows stay
    readable while live actions stay Inbox-only. Never raises: failures
    resolve to the Inbox selection (possibly None).
    """
    target = archive_read_target(owner)
    if target is not None:
        return target
    try:
        selector = getattr(owner, "_get_selected_agent", None)
        return selector() if callable(selector) else None
    except Exception:
        return None


def archive_markable_key(owner: Any) -> str | None:
    """Return the selected Archive key when it names a markable run.

    Banners, page tails, and the focused Inbox pulse are navigable but
    never agents, so they resolve to None here.
    """
    if not archive_ui_active(owner):
        return None
    try:
        from ...models.agent_archive_view import (
            ARCHIVE_SECTION_PULSE,
            is_archive_row_key,
        )
        from ._archive_view import agents_archive_view_state
    except Exception:
        return None
    try:
        state = agents_archive_view_state(owner)
        key = state.archive.selected_key
        if (
            key is None
            or state.archive.focused_section == ARCHIVE_SECTION_PULSE
            or not is_archive_row_key(key)
        ):
            return None
        return str(key)
    except Exception:
        return None


def toggle_archive_mark(owner: Any) -> bool:
    """Toggle the Archive mark on the selected run. True when toggled."""
    key = archive_markable_key(owner)
    if key is None:
        try:
            notify = getattr(owner, "notify", None)
            if callable(notify):
                notify("Only archived runs can be marked", severity="warning")
        except Exception:
            pass
        return False
    try:
        from ._archive_view import agents_archive_view_state
    except Exception:
        return False
    try:
        state = agents_archive_view_state(owner)
        marks = set(state.archive.marks)
        if key in marks:
            marks.discard(key)
        else:
            marks.add(key)
        state.archive.marks = frozenset(marks)
        return True
    except Exception:
        return False


def clear_archive_marks(owner: Any) -> int:
    """Clear Archive marks, returning how many were cleared."""
    if not archive_ui_active(owner):
        return 0
    try:
        from ._archive_view import agents_archive_view_state
    except Exception:
        return 0
    try:
        state = agents_archive_view_state(owner)
        count = len(state.archive.marks)
        state.archive.marks = frozenset()
        return count
    except Exception:
        return 0


def archive_marked_count(owner: Any) -> int:
    """Return the number of Archive marks (0 outside the Archive)."""
    if not archive_ui_active(owner):
        return 0
    try:
        from ._archive_view import agents_archive_view_state
    except Exception:
        return 0
    try:
        return len(agents_archive_view_state(owner).archive.marks)
    except Exception:
        return 0


def archive_marked_run_keys(owner: Any) -> frozenset[str]:
    """Return marked Archive keys, expanding containers to member runs.

    Container membership comes from loaded light members only — no bundle
    hydration — as the member source for the parent bulk-restore builder.
    Inbox marks stay parked and untouched.
    """
    if not archive_ui_active(owner):
        return frozenset()
    try:
        from ...models.agent_archive_list import archive_row_key
        from ...models.agent_archive_view import (
            container_key_of,
            is_archive_container_key,
        )
        from ._archive_column import archive_container_members
        from ._archive_view import agents_archive_view_state
    except Exception:
        return frozenset()
    try:
        marked = set(agents_archive_view_state(owner).archive.marks)
    except Exception:
        return frozenset()
    expanded: set[str] = set()
    for key in marked:
        if is_archive_container_key(key):
            container_key = container_key_of(key)
            if container_key is None:
                expanded.add(key)
                continue
            try:
                members = archive_container_members(owner, container_key)
            except Exception:
                members = ()
            member_keys = {key}
            for member in members:
                try:
                    member_key = archive_row_key(member)
                except Exception:
                    member_key = None
                if member_key:
                    member_keys.add(member_key)
            expanded |= member_keys
        else:
            expanded.add(key)
    return frozenset(expanded)


__all__ = [
    "ARCHIVE_LIVE_ONLY_ACTIONS",
    "ARCHIVE_PARENT_SEAM_ACTIONS",
    "archive_markable_key",
    "archive_marked_count",
    "archive_marked_run_keys",
    "archive_read_target",
    "archive_ui_active",
    "clear_archive_marks",
    "guard_archive_live_action",
    "resolve_agents_read_agent",
    "toggle_archive_mark",
]

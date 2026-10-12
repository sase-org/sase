"""Agents-tab Archive view-aware selection and key routing.

Selection seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``owner`` is the app, duck-typed so fakes can drive every helper without a
composed widget tree. ``_get_selected_agent`` keeps its Inbox-only semantics;
read callers opt into :func:`get_agents_tab_selection` instead. The public
import path stays :mod:`sase.ace.tui.actions.agents._archive_view`, which
re-exports this module's public names.
"""

from __future__ import annotations

import logging
from typing import Any

from ...models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    ARCHIVE_ROW_NONE,
    ARCHIVE_SECTION_PULSE,
    AgentsTabSelection,
    ReadOnlyArchiveContext,
    agents_archive_view_enabled,
    is_archive_container_key,
    is_archive_row_key,
)
from ._archive_view_state import agents_archive_view_state, archive_detail_owns_panel

log = logging.getLogger(__name__)


def get_agents_tab_selection(owner: Any) -> AgentsTabSelection:
    """Return the typed view-aware selection for read callers.

    Live-only callers keep using ``_get_selected_agent`` and never see an
    archived row. A banner, page tail, or the focused Inbox pulse is not an
    agent: it resolves to ``row_kind`` ``"none"``. A run carries its stable
    key and core light row; a container carries ``container:<key>`` and the
    light row of its summary. A hydrated Archive agent is attached when the
    reader has finished loading that same key.
    """
    state = agents_archive_view_state(owner)
    if state.active_view == AGENTS_VIEW_ARCHIVE:
        if not agents_archive_view_enabled():
            return AgentsTabSelection(view=AGENTS_VIEW_INBOX, row_kind=ARCHIVE_ROW_NONE)
        key = state.archive.selected_key
        if (
            key is None
            or state.archive.focused_section == ARCHIVE_SECTION_PULSE
            or not is_archive_row_key(key)
        ):
            return AgentsTabSelection(
                view=AGENTS_VIEW_ARCHIVE,
                row_kind=ARCHIVE_ROW_NONE,
                read_only=True,
            )
        from ._archive_column import archive_light_row
        from ._archive_reader import hydrated_archive_agent_for

        return AgentsTabSelection(
            view=AGENTS_VIEW_ARCHIVE,
            row_kind=(
                ARCHIVE_ROW_CONTAINER
                if is_archive_container_key(key)
                else ARCHIVE_ROW_AGENT
            ),
            agent=hydrated_archive_agent_for(owner, key),
            read_only=True,
            archive_key=key,
            provenance="archive",
            light_row=archive_light_row(owner, key),
        )
    selector = getattr(owner, "_get_selected_agent", None)
    agent = selector() if callable(selector) else None
    if agent is None:
        return AgentsTabSelection(view=AGENTS_VIEW_INBOX, row_kind=ARCHIVE_ROW_NONE)
    return AgentsTabSelection(
        view=AGENTS_VIEW_INBOX, row_kind=ARCHIVE_ROW_AGENT, agent=agent
    )


def archive_read_only_context(owner: Any) -> ReadOnlyArchiveContext | None:
    """Return the read-only detail context for the Archive selection."""
    state = agents_archive_view_state(owner)
    if not archive_detail_owns_panel(owner):
        return None
    key = state.archive.selected_key
    if (
        key is None
        or state.archive.focused_section == ARCHIVE_SECTION_PULSE
        or not is_archive_row_key(key)
    ):
        return None
    from ._archive_column import archive_light_row
    from ._archive_reader import hydrated_archive_agent_for

    runtime = getattr(owner, "_archive_reader_runtime", None)
    matching = getattr(runtime, "archive_key", None) == key
    return ReadOnlyArchiveContext(
        archive_key=key,
        detail_generation=state.generation,
        provenance="archive",
        light_row=archive_light_row(owner, key),
        hydrated_agent=hydrated_archive_agent_for(owner, key),
        unreadable=bool(getattr(runtime, "unreadable", False)) if matching else False,
        retained=tuple(getattr(runtime, "retained", ())) if matching else (),
        missing=tuple(getattr(runtime, "missing", ())) if matching else (),
    )


def route_archive_key(owner: Any, intent: str) -> bool:
    """Route an Agents-tab list key to the Archive. True when it consumed the key.

    Called at the top of the ``j k g G h l J K`` and Enter actions so an active
    Archive never falls through to Inbox navigation or to actions on the
    parked Inbox selection. The Inbox path pays one attribute read: the Archive
    column code only loads once the Archive is actually open.
    """
    if getattr(owner, "current_tab", "agents") != "agents":
        return False
    if agents_archive_view_state(
        owner
    ).active_view != AGENTS_VIEW_ARCHIVE or not archive_detail_owns_panel(owner):
        return False
    from ._archive_column_nav import dispatch_archive_intent

    dispatch_archive_intent(owner, intent)
    _mark_archive_key_painted(owner)
    return True


def _mark_archive_key_painted(owner: Any) -> None:
    """Finalize the in-flight key-to-paint sample on the next frame.

    Mirrors the Inbox navigation path: the calling action already recorded
    the keypress through ``_jk_perf_begin``, so without this hook the sample
    would be discarded by the next keystroke and Archive j/k would stay
    invisible to the ``SASE_TUI_PERF=1`` harness. No-op unless perf
    recording is on; fakes without ``call_after_refresh`` never reach it.
    """
    try:
        perf = getattr(owner, "_jk_perf", None)
        after_refresh = getattr(owner, "call_after_refresh", None)
        if perf is None or not callable(after_refresh):
            return
        mark_updated = getattr(perf, "mark_model_updated", None)
        if callable(mark_updated):
            mark_updated()
        after_refresh(perf.mark_painted)
    except Exception:
        log.debug("archive paint sample hook failed", exc_info=True)


__all__ = [
    "archive_read_only_context",
    "get_agents_tab_selection",
    "route_archive_key",
]

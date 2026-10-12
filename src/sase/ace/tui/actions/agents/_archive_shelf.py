"""Committed Inbox-filter counts and the one-line Archive shelf."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ...models.agent_archive_controller import (
    ArchiveShelfSnapshot,
    AgentsArchiveControllerState,
)
from ...models.agent_archive_list import archive_timezone
from ...models.agent_archive_view import agents_archive_view_enabled
from ...util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)
_TASKS_ATTR = "_archive_shelf_tasks"


def _controller(owner: Any) -> AgentsArchiveControllerState | None:
    state = getattr(owner, "_agents_archive_controller", None)
    return state if isinstance(state, AgentsArchiveControllerState) else None


def archive_shelf_snapshot(owner: Any) -> ArchiveShelfSnapshot:
    state = _controller(owner)
    return state.shelf if state is not None else ArchiveShelfSnapshot()


def _matching_rows(
    corpus: Any,
    query: str,
    profile: Any,
    limit: int = 5,
) -> tuple[Mapping[str, Any], ...]:
    summary = corpus.summary(query, group_by="day", profile=profile)
    found: list[Mapping[str, Any]] = []
    for group in summary.get("groups", ()):
        if not isinstance(group, Mapping):
            continue
        remaining = limit - len(found)
        if remaining <= 0:
            break
        key = group.get("key")
        if not isinstance(key, str):
            continue
        payload = corpus.rows(
            query,
            group_by="day",
            group_key=key,
            offset=0,
            limit=remaining,
            profile=profile,
        )
        found.extend(
            dict(row) for row in payload.get("rows", ()) if isinstance(row, Mapping)
        )
    return tuple(found)


def _compute_shelf_snapshot(
    corpus: Any,
    profile: Any,
    query: str,
) -> ArchiveShelfSnapshot:
    """Run counts and the bounded bridge query against a held corpus."""
    from ....query.scope_token import extract_scope

    try:
        query, _scope = extract_scope(query)
        total = int(corpus.count("", profile=profile) or 0)
    except Exception:
        log.debug("archive shelf total count failed", exc_info=True)
        return ArchiveShelfSnapshot(status="unavailable", query=query)

    if query.strip():
        try:
            matching = int(corpus.count(query, profile=profile) or 0)
            rows = _matching_rows(corpus, query, profile) if matching else ()
        except Exception:
            # A committed Inbox-only field (for example unread:) cannot be
            # answered by the Archive profile. Keep the total for the shelf,
            # and let the empty-state card explain the scope mismatch.
            log.debug("archive shelf filter is not answerable", exc_info=True)
            return ArchiveShelfSnapshot(
                status="unanswerable",
                query=query,
                total=total,
            )
        return ArchiveShelfSnapshot(
            status="ready",
            query=query,
            total=total,
            matching=matching,
            rows=rows,
        )

    try:
        summary = corpus.summary("", group_by="day", profile=profile)
        groups = summary.get("groups", ())
        timezone = archive_timezone(str(getattr(corpus, "timezone", "") or ""))
        today_key = datetime.now(timezone).date().isoformat()
        today = next(
            (
                int(group.get("count", 0) or 0)
                for group in groups
                if isinstance(group, Mapping) and group.get("key") == today_key
            ),
            0,
        )
    except Exception:
        log.debug("archive shelf today count failed", exc_info=True)
        today = 0
    return ArchiveShelfSnapshot(
        status="ready",
        query="",
        total=total,
        today=today,
        matching=total,
    )


def request_archive_shelf_refresh(owner: Any) -> None:
    """Refresh committed-filter counts from the warm corpus off-thread."""
    if not agents_archive_view_enabled():
        _sync_widget(owner)
        return
    state = _controller(owner)
    if state is None:
        return
    query = str(getattr(owner, "_agent_search_query", "") or "")
    corpus = state.corpus
    profile = state.profile
    if corpus is None:
        state.shelf = ArchiveShelfSnapshot(
            status=("unavailable" if state.status == "unreadable" else "cold"),
            query=query,
        )
        _sync_widget(owner)
        return

    key = (query, state.tokens, id(corpus))
    if key == state.shelf_requested_key:
        return
    state.shelf_requested_key = key
    state.shelf_generation += 1
    generation = state.shelf_generation
    state.shelf = ArchiveShelfSnapshot(status="loading", query=query)
    _sync_widget(owner)

    async def _run() -> None:
        try:
            result = await asyncio.to_thread(
                _compute_shelf_snapshot,
                corpus,
                profile,
                query,
            )
        except Exception:
            log.debug("archive shelf refresh failed", exc_info=True)
            result = ArchiveShelfSnapshot(status="unavailable", query=query)
        current = _controller(owner)
        if (
            current is None
            or current.shelf_generation != generation
            or current.corpus is not corpus
            or str(getattr(owner, "_agent_search_query", "") or "") != query
        ):
            return
        current.shelf = result
        _sync_widget(owner)

    task = spawn_pump_free_task(
        owner,
        _run(),
        name="sase-archive-shelf",
        registry_attr=_TASKS_ATTR,
    )
    if task is not None:
        tasks = getattr(owner, _TASKS_ATTR, None)
        if tasks is None:
            tasks = set()
            setattr(owner, _TASKS_ATTR, tasks)
        tasks.add(task)


def _sync_widget(owner: Any) -> None:
    try:
        widget = owner.query_one("#agent-archive-shelf")
        widget.set_snapshot(
            archive_shelf_snapshot(owner),
            inbox_empty=not bool(getattr(owner, "_agents", ()) or ()),
            enabled=agents_archive_view_enabled(),
        )
    except Exception:
        # The controller can prewarm before the laid-out TUI widgets mount.
        pass


def sync_archive_shelf(owner: Any) -> None:
    """Repaint the shelf after a count, refresh, or Inbox-result change."""
    _sync_widget(owner)


def archive_bridge_detail(owner: Any, query: str) -> str:
    """Describe the Archive side of an empty committed Inbox query."""
    shelf = archive_shelf_snapshot(owner)
    if shelf.query != query:
        return "◷ Checking the Archive for this filter…"
    if shelf.status in {"cold", "loading"}:
        return "◷ Checking the Archive for this filter…"
    if shelf.status == "unavailable":
        return "The Archive index is unavailable · ,a opens the Archive"
    if shelf.status == "unanswerable":
        return "The Archive can't answer this filter · ^ previous filter"
    if shelf.matching == 0:
        return "No Archive runs match this filter · ^ previous filter"
    if shelf.status != "ready":
        return "◷ Checking the Archive for this filter…"
    lines = [f"◷ Archive · {shelf.matching or 0} match this filter"]
    for row in shelf.rows:
        name = _row_name(row)
        if not name:
            continue
        outcome = str(row.get("outcome") or row.get("status") or "").replace("_", " ")
        lines.append(f"  {name}" + (f" · {outcome}" if outcome else ""))
    lines.append("⏎ search the Archive for this filter · ^ previous filter")
    return "\n".join(lines)


def _row_name(row: Mapping[str, Any]) -> str:
    for key in ("agent_name", "name", "cl_name"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def activate_archive_shelf(owner: Any) -> bool:
    """Open the parked Archive, carrying an answerable Inbox filter."""
    if not agents_archive_view_enabled():
        return False
    owner._agent_archive_shelf_focused = False
    try:
        owner.query_one("#agent-archive-shelf").remove_class("-focused")
    except Exception:
        pass
    shelf = archive_shelf_snapshot(owner)
    query = str(getattr(owner, "_agent_search_query", "") or "")
    if query.strip() and shelf.query == query and shelf.status == "ready":
        from ._archive_view import open_agents_archive_view_with_query

        open_agents_archive_view_with_query(
            owner,
            query=f"in:archive {query}",
        )
        return True
    from ._archive_view import open_agents_archive_view

    open_agents_archive_view(owner)
    return True


def archive_dismissal_toast_suffix(owner: Any) -> str:
    """Return the conditional Archive pointer appended to dismissal toasts."""
    return " → ◷ Archive · ,a browse" if agents_archive_view_enabled() else ""


def route_archive_shelf_focus(owner: Any, *, forward: bool) -> bool:
    """Route J/K to and from the Inbox shelf pseudo-panel."""
    if (
        getattr(owner, "current_tab", None) != "agents"
        or not agents_archive_view_enabled()
    ):
        return False
    try:
        from ._display_helpers import agents_archive_is_active

        if agents_archive_is_active(owner):
            return False
        shelf_widget = owner.query_one("#agent-archive-shelf")
    except Exception:
        return False
    if getattr(getattr(shelf_widget, "styles", None), "display", "none") == "none":
        return False

    focused = bool(getattr(owner, "_agent_archive_shelf_focused", False))
    if focused:
        if forward:
            return True
        owner._agent_archive_shelf_focused = False
        shelf_widget.remove_class("-focused")
        try:
            owner.query_one("#agent-list-panel").focus()
        except Exception:
            pass
        return True

    if not forward:
        return False
    panel_group = getattr(owner, "_panel_group", None)
    panel_keys = list(getattr(panel_group, "panel_keys", ()) or ())
    focused_idx = int(getattr(panel_group, "focused_idx", 0) or 0)
    if not panel_keys or focused_idx != len(panel_keys) - 1:
        return False
    owner._agent_archive_shelf_focused = True
    shelf_widget.add_class("-focused")
    shelf_widget.focus()
    return True


__all__ = [
    "activate_archive_shelf",
    "archive_bridge_detail",
    "archive_dismissal_toast_suffix",
    "archive_shelf_snapshot",
    "request_archive_shelf_refresh",
    "route_archive_shelf_focus",
    "sync_archive_shelf",
]

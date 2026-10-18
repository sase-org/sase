"""Agents-tab Archive column navigation: cursor, folds, paging, and key routing.

Archive-column seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
Every Agents-tab list key (``j k g G h l J K`` and Enter) calls
:func:`route_archive_key` first; while the Archive owns the tab it consumes the
key, so nothing falls through to Inbox navigation or to actions on the parked
Inbox selection. All state lives on ``ArchiveViewState``; the Inbox indices,
``_agents``, and the parked Inbox selection are never read or written here.
"""

from __future__ import annotations

import logging
from typing import Any

from ...models.agent_archive_list import (
    ITEM_BANNER,
    ITEM_CONTAINER,
    ITEM_MEMBER,
    ITEM_ROW,
    ITEM_TAIL,
    edge_key,
    neighbor_key,
    parent_banner_key,
    with_banner_open,
)
from ...models.agent_archive_view import (
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
    INTENT_ACTIVATE,
    INTENT_COLLAPSE,
    INTENT_DOWN,
    INTENT_EXPAND,
    INTENT_FIRST,
    INTENT_LAST,
    INTENT_SWITCH_SECTION,
    INTENT_UP,
    banner_item_key,
    container_key_of,
    tail_item_key,
)
from ._archive_column import (
    banner_is_default_open,
    column_archive,
    column_runtime,
    column_widget,
    refresh_column,
    schedule_detail,
)
from ._archive_view import archive_detail_owns_panel, close_agents_archive_view

log = logging.getLogger(__name__)


def _set_cursor(owner: Any, key: str | None, *, from_widget: bool = False) -> None:
    archive = column_archive(owner)
    if key is None:
        return
    column_runtime(owner).default_cursor = False
    changed = key != archive.selected_key or (
        archive.focused_section != ARCHIVE_SECTION_LIST
    )
    archive.selected_key = key
    archive.focused_section = ARCHIVE_SECTION_LIST
    widget = column_widget(owner)
    if widget is not None:
        if not from_widget:
            widget.set_cursor(key)
        widget.set_section(ARCHIVE_SECTION_LIST)
    if changed:
        schedule_detail(owner)
        from ._archive_column import refresh_archive_footer

        refresh_archive_footer(owner)


def _selected_item(owner: Any) -> Any:
    return column_runtime(owner).model.item(column_archive(owner).selected_key)


def _toggle_banner(owner: Any, banner_key: str, *, open: bool) -> None:
    archive = column_archive(owner)
    archive.expanded_banners, archive.folded_banners = with_banner_open(
        archive.expanded_banners,
        archive.folded_banners,
        banner_key,
        open=open,
        default_open=banner_is_default_open(owner, banner_key),
    )
    if not open:
        # Folding hides the cursor's row: park on the banner itself.
        item = _selected_item(owner)
        if item is not None and item.banner_key == banner_key:
            archive.selected_key = banner_item_key(banner_key)
    refresh_column(owner)
    schedule_detail(owner)


def _set_container_expanded(owner: Any, container_key: str, *, expanded: bool) -> None:
    archive = column_archive(owner)
    current = tuple(archive.expanded_containers)
    if expanded and container_key not in current:
        archive.expanded_containers = (*current, container_key)
    elif not expanded and container_key in current:
        archive.expanded_containers = tuple(k for k in current if k != container_key)
    else:
        return
    refresh_column(owner)


def _load_next_page(owner: Any, banner_key: str) -> None:
    archive = column_archive(owner)
    runtime = column_runtime(owner)
    model = runtime.model
    tail_position = model.position(tail_item_key(banner_key))
    if tail_position is not None and tail_position > 0:
        runtime.page_anchor = model.items[tail_position - 1].key
    pages = dict(archive.loaded_pages)
    pages[banner_key] = max(1, int(pages.get(banner_key, 1) or 1)) + 1
    archive.loaded_pages = pages
    refresh_column(owner)


def _return_to_inbox(owner: Any) -> None:
    """Return to the parked Inbox; reopening the Archive lands on its list."""
    column_archive(owner).focused_section = ARCHIVE_SECTION_LIST
    close_agents_archive_view(owner)


def _move(owner: Any, step: int) -> None:
    archive = column_archive(owner)
    if archive.focused_section == ARCHIVE_SECTION_PULSE:
        return
    _set_cursor(
        owner, neighbor_key(column_runtime(owner).model, archive.selected_key, step)
    )


def _edge(owner: Any, *, last: bool) -> None:
    archive = column_archive(owner)
    if archive.focused_section == ARCHIVE_SECTION_PULSE:
        return
    _set_cursor(owner, edge_key(column_runtime(owner).model, last=last))


def _enter_banner(owner: Any, item: Any) -> None:
    """Step onto the first child row under an open banner or container."""
    model = column_runtime(owner).model
    following = model.item(neighbor_key(model, item.key, 1))
    if (
        following is not None
        and following.key != item.key
        and following.banner_key == item.banner_key
        and following.kind != ITEM_BANNER
    ):
        _set_cursor(owner, following.key)


def _expand(owner: Any) -> None:
    archive = column_archive(owner)
    if archive.focused_section == ARCHIVE_SECTION_PULSE:
        _return_to_inbox(owner)
        return
    item = _selected_item(owner)
    if item is None:
        return
    if item.kind == ITEM_BANNER:
        if item.open:
            _enter_banner(owner, item)
        else:
            _toggle_banner(owner, str(item.banner_key), open=True)
    elif item.kind == ITEM_TAIL:
        _load_next_page(owner, str(item.banner_key))
    elif item.kind == ITEM_CONTAINER:
        container = container_key_of(item.key)
        if container is None:
            return
        if item.expanded:
            _enter_banner(owner, item)
        else:
            _set_container_expanded(owner, container, expanded=True)


def _collapse(owner: Any) -> None:
    archive = column_archive(owner)
    if archive.focused_section == ARCHIVE_SECTION_PULSE:
        return
    model = column_runtime(owner).model
    item = model.item(archive.selected_key)
    if item is None:
        return
    if item.kind == ITEM_BANNER:
        if item.open:
            _toggle_banner(owner, str(item.banner_key), open=False)
    elif item.kind == ITEM_CONTAINER and item.expanded:
        container = container_key_of(item.key)
        if container is not None:
            _set_container_expanded(owner, container, expanded=False)
    elif item.kind == ITEM_MEMBER and item.member_of is not None:
        container_item = next(
            (
                candidate
                for candidate in model.items
                if candidate.kind == ITEM_CONTAINER
                and container_key_of(candidate.key) == item.member_of
            ),
            None,
        )
        if container_item is not None:
            _set_cursor(owner, container_item.key)
            _set_container_expanded(owner, item.member_of, expanded=False)
    else:
        parent = parent_banner_key(model, archive.selected_key)
        if parent is not None:
            _set_cursor(owner, parent)


def _activate(owner: Any) -> None:
    archive = column_archive(owner)
    if archive.focused_section == ARCHIVE_SECTION_PULSE:
        _return_to_inbox(owner)
        return
    item = _selected_item(owner)
    if item is None:
        return
    if item.kind == ITEM_BANNER:
        _toggle_banner(owner, str(item.banner_key), open=not item.open)
    elif item.kind == ITEM_TAIL:
        _load_next_page(owner, str(item.banner_key))
    elif item.kind in (ITEM_CONTAINER, ITEM_ROW, ITEM_MEMBER):
        from ._archive_restore import open_archive_chooser

        open_archive_chooser(owner, item.key)


def _switch_section(owner: Any) -> None:
    """Switch pulse/list focus; the parked Inbox cursor is never touched."""
    archive = column_archive(owner)
    archive.focused_section = (
        ARCHIVE_SECTION_LIST
        if archive.focused_section == ARCHIVE_SECTION_PULSE
        else ARCHIVE_SECTION_PULSE
    )
    widget = column_widget(owner)
    if widget is not None:
        widget.set_section(archive.focused_section)
    schedule_detail(owner)


_INTENT_HANDLERS = {
    INTENT_DOWN: lambda owner: _move(owner, 1),
    INTENT_UP: lambda owner: _move(owner, -1),
    INTENT_FIRST: lambda owner: _edge(owner, last=False),
    INTENT_LAST: lambda owner: _edge(owner, last=True),
    INTENT_EXPAND: _expand,
    INTENT_COLLAPSE: _collapse,
    INTENT_ACTIVATE: _activate,
    INTENT_SWITCH_SECTION: _switch_section,
}


def dispatch_archive_intent(owner: Any, intent: str) -> None:
    """Run one list-key intent against the Archive. Never raises into the key."""
    handler = _INTENT_HANDLERS.get(intent)
    if handler is None:
        return
    try:
        handler(owner)
    except Exception:
        log.debug("archive key %s failed", intent, exc_info=True)


def archive_cursor_from_widget(owner: Any, key: str) -> None:
    """The user moved the list highlight (arrow keys or mouse)."""
    if not archive_detail_owns_panel(owner):
        return
    # Rebuilds and OptionList highlight echoes must not yank pulse focus;
    # J then Enter would otherwise activate a list row and stay on Archive.
    if column_archive(owner).focused_section == ARCHIVE_SECTION_PULSE:
        return
    _set_cursor(owner, key, from_widget=True)


def archive_activate_key(owner: Any, key: str) -> None:
    """Enter or a click on a list item: highlight it, then activate it."""
    if not archive_detail_owns_panel(owner):
        return
    _set_cursor(owner, key, from_widget=True)
    dispatch_archive_intent(owner, INTENT_ACTIVATE)


def archive_activate_pulse(owner: Any) -> None:
    """A click on the Inbox pulse returns to the parked Inbox."""
    if archive_detail_owns_panel(owner):
        _return_to_inbox(owner)


__all__ = [
    "archive_activate_key",
    "archive_activate_pulse",
    "archive_cursor_from_widget",
    "dispatch_archive_intent",
]

"""Agents-tab Archive column core: list state, window planning, paint, and chrome.

Archive-column seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``owner`` is the app, duck-typed so fakes can drive every helper without a
composed widget tree; DOM access is confined to :func:`sync_archive_chrome`
and the widget calls in :func:`_paint`. The corpus controller owns all disk
and query work: this module only plans windows from the held summary,
assembles the list model, and repaints. Cursor movement, folds, paging, and
key routing live in :mod:`._archive_column_nav`.

All Archive list state lives on ``ArchiveViewState`` (the cursor, folds,
loaded pages, section focus) and never touches Inbox indices, ``_agents``, or
the parked Inbox selection.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any

from ...models.agent_archive_controller import (
    ARCHIVE_CORPUS_COLD,
    ARCHIVE_CORPUS_LOADING,
    ARCHIVE_CORPUS_WARM,
    ArchiveCorpusSnapshot,
    ArchivePageWindow,
)
from ...models.agent_archive_list import (
    ITEM_BANNER,
    ITEM_MEMBER,
    ITEM_TAIL,
    ArchiveBanner,
    ArchiveListModel,
    archive_row_key,
    archive_timezone,
    assemble_archive_list,
    banner_key_for_row,
    build_archive_banners,
    default_open_banner_keys,
    effective_open_banner_keys,
    fallback_cursor,
    plan_archive_windows,
    with_banner_open,
    windows_satisfy,
)
from ...models.agent_archive_view import (
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
    ArchiveViewState,
)
from ._archive_controller import (
    archive_corpus_snapshot,
    archive_inbox_pulse,
    request_archive_windows,
)
from ._archive_view import archive_detail_owns_panel

log = logging.getLogger(__name__)

_COLUMN_ID = "archive-column"
_WIDGET_ATTR = "_archive_column_widget"
_RUNTIME_ATTR = "_archive_column_runtime"


@dataclass
class _ColumnRuntime:
    """Transient per-app column state (never persisted)."""

    model: ArchiveListModel = field(default_factory=ArchiveListModel)
    requested: tuple[Any, ...] | None = None
    page_anchor: str | None = None
    reveal_container: str | None = None
    #: The cursor key the detail was last scheduled for. The controller can
    #: move ``archive.selected_key`` without scheduling (exact-name reveal,
    #: drift fallback, committed-query change); the next install compares
    #: against this so a controller-moved selection still repaints.
    last_detail_key: str | None = None
    #: The cursor was auto-placed on a banner because no run had loaded yet;
    #: the first run to arrive takes it unless the user already moved.
    default_cursor: bool = False


@dataclass(frozen=True)
class _Computed:
    snapshot: ArchiveCorpusSnapshot
    banners: tuple[ArchiveBanner, ...]
    default_open: frozenset[str]
    open_keys: frozenset[str]
    usable: bool
    today: date
    tz: tzinfo
    desired: tuple[ArchivePageWindow, ...]


def column_runtime(owner: Any) -> _ColumnRuntime:
    runtime = getattr(owner, _RUNTIME_ATTR, None)
    if not isinstance(runtime, _ColumnRuntime):
        runtime = _ColumnRuntime()
        setattr(owner, _RUNTIME_ATTR, runtime)
    return runtime


def column_archive(owner: Any) -> ArchiveViewState:
    return owner._agents_archive_view.archive  # type: ignore[no-any-return]


def column_widget(owner: Any) -> Any:
    return getattr(owner, _WIDGET_ATTR, None)


def archive_light_row(owner: Any, key: str | None) -> Mapping[str, Any] | None:
    """Return the core light row behind a selected run or container key."""
    item = column_runtime(owner).model.item(key)
    return None if item is None else item.row


def archive_container_members(
    owner: Any, container_key: str
) -> tuple[Mapping[str, Any], ...]:
    """Return the loaded matching light members of an expanded container.

    A collapsed container has no loaded members; callers needing them expand
    it through the list (or request a window) rather than hydrating bundles.
    """
    return tuple(
        item.row
        for item in column_runtime(owner).model.items
        if item.kind == ITEM_MEMBER and item.member_of == container_key
        if item.row is not None
    )


def banner_is_default_open(owner: Any, banner_key: str) -> bool:
    """Return whether ``banner_key`` is open before any user fold change."""
    return banner_key in _compute(owner).default_open


def _now(owner: Any, tz: tzinfo) -> datetime:
    clock = getattr(owner, "_archive_now", None)
    if callable(clock):
        return clock().astimezone(tz)  # type: ignore[no-any-return]
    return datetime.now(tz)


def _compute(owner: Any) -> _Computed:
    snapshot = archive_corpus_snapshot(owner)
    archive = column_archive(owner)
    tz = archive_timezone(snapshot.timezone)
    today = _now(owner, tz).date()
    usable = (
        snapshot.summary is not None
        and snapshot.applied_query == archive.committed_query
        and snapshot.applied_grouping == archive.grouping
    )
    banners: tuple[ArchiveBanner, ...] = ()
    default_open: frozenset[str] = frozenset()
    if usable:
        banners = build_archive_banners(
            snapshot.summary,
            archive.grouping,
            today=today,
            display_snapshot=snapshot.display_snapshot,
        )
        total = int((snapshot.summary or {}).get("total", 0) or 0)
        default_open = default_open_banner_keys(
            banners,
            grouping=archive.grouping,
            total=total,
            today=today,
            complete=snapshot.status == ARCHIVE_CORPUS_WARM,
        )
    open_keys = effective_open_banner_keys(
        default_open, archive.expanded_banners, archive.folded_banners
    )
    desired: tuple[ArchivePageWindow, ...] = ()
    if usable:
        desired = plan_archive_windows(
            banners,
            open_keys,
            archive.loaded_pages,
            probe_totals=bool(archive.expanded_containers),
        )
    return _Computed(
        snapshot, banners, default_open, open_keys, usable, today, tz, desired
    )


def _signature(
    archive: ArchiveViewState, desired: tuple[ArchivePageWindow, ...]
) -> Any:
    return (
        archive.committed_query,
        archive.grouping,
        tuple(archive.expanded_containers),
        desired,
    )


def plan_archive_view_windows(owner: Any) -> tuple[ArchivePageWindow, ...] | None:
    """Plan windows from the held summary so a warm open needs one request.

    Returns ``None`` when no usable summary is held (cold open or a changed
    query), in which case the first result plans the windows. Records the plan
    as requested so the open's own refresh does not issue a duplicate.
    """
    computed = _compute(owner)
    if not computed.usable:
        return None
    column_runtime(owner).requested = _signature(
        column_archive(owner), computed.desired
    )
    return computed.desired


def _request_if_needed(owner: Any, computed: _Computed) -> None:
    archive = column_archive(owner)
    snapshot = computed.snapshot
    expanded = tuple(archive.expanded_containers)
    if snapshot.applied_expanded == expanded and windows_satisfy(
        snapshot.windows, computed.desired
    ):
        return
    signature = _signature(archive, computed.desired)
    runtime = column_runtime(owner)
    if runtime.requested == signature:
        return
    runtime.requested = signature
    request_archive_windows(owner, computed.desired, expanded_containers=expanded)


def _is_loading(snapshot: ArchiveCorpusSnapshot) -> bool:
    return snapshot.refreshing or snapshot.status in {
        ARCHIVE_CORPUS_COLD,
        ARCHIVE_CORPUS_LOADING,
    }


def _assemble(owner: Any, computed: _Computed) -> ArchiveListModel:
    archive = column_archive(owner)
    snapshot = computed.snapshot
    return assemble_archive_list(
        banners=computed.banners,
        open_keys=computed.open_keys,
        windows=snapshot.windows if computed.usable else (),
        pages=archive.loaded_pages,
        desired_expanded=archive.expanded_containers,
        applied_expanded=snapshot.applied_expanded,
        status=snapshot.status,
        error_message=snapshot.error_message,
        indexed_rows=snapshot.indexed_rows,
        summary_known=computed.usable,
        loading=_is_loading(snapshot),
    )


def _default_cursor(model: ArchiveListModel) -> str | None:
    """Prefer the first run so opening the Archive lands on content."""
    first_any: str | None = None
    for item in model.items:
        if not item.selectable:
            continue
        if first_any is None:
            first_any = item.key
        if item.kind != ITEM_BANNER:
            return item.key
    return first_any


def _first_run_key(model: ArchiveListModel) -> str | None:
    for item in model.items:
        if item.selectable and item.kind != ITEM_BANNER:
            return item.key
    return None


def _normalize_cursor(
    archive: ArchiveViewState,
    runtime: _ColumnRuntime,
    model: ArchiveListModel,
) -> str | None:
    """Keep the cursor valid across a rebuild without clobbering a pending one.

    A transient list with nothing selectable (loading) leaves the key alone so
    the controller can still preserve identity when the real rows land, and a
    pending exact-arrival keeps its looked-up key until it is revealed.
    """
    key = archive.selected_key
    if archive.reveal_row is not None or not model.selectable_keys():
        return key
    if key is None:
        key = _default_cursor(model)
        placed = model.item(key)
        runtime.default_cursor = placed is not None and placed.kind == ITEM_BANNER
        return key
    key = fallback_cursor(runtime.model, key, model)
    if runtime.default_cursor:
        first_run = _first_run_key(model)
        if first_run is not None:
            runtime.default_cursor = False
            return first_run
    return key


def _apply_page_anchor(
    runtime: _ColumnRuntime, model: ArchiveListModel, key: str | None
) -> str | None:
    """After paging, move the cursor onto the first newly loaded row."""
    anchor = runtime.page_anchor
    if anchor is None:
        return key
    position = model.position(anchor)
    if position is None or position + 1 >= len(model.items):
        runtime.page_anchor = None
        return key
    following = model.items[position + 1]
    anchor_item = model.items[position]
    if following.kind == ITEM_TAIL and following.banner_key == anchor_item.banner_key:
        return key  # the next page has not landed yet
    runtime.page_anchor = None
    if following.selectable and following.banner_key == anchor_item.banner_key:
        return following.key
    return key


def _advance_reveal(owner: Any, computed: _Computed) -> bool:
    """Walk an exact-arrival row into view; True when state changed.

    Only advances while the loaded windows are current, so each step reacts to
    real data: open its banner, page until it appears, then expand its
    container once, then give up (the row is not part of this query).
    """
    archive = column_archive(owner)
    row = archive.reveal_row
    if row is None:
        return False
    snapshot = computed.snapshot
    if not (
        computed.usable
        and snapshot.applied_expanded == tuple(archive.expanded_containers)
        and windows_satisfy(snapshot.windows, computed.desired)
    ):
        return False
    runtime = column_runtime(owner)
    model = _assemble(owner, computed)
    key = archive_row_key(row)
    if key is None or model.position(key) is not None:
        if key is not None:
            archive.selected_key = key
            if archive.focused_section != ARCHIVE_SECTION_PULSE:
                archive.focused_section = ARCHIVE_SECTION_LIST
        archive.reveal_row = None
        runtime.reveal_container = None
        return False
    banner_key = banner_key_for_row(row, archive.grouping, computed.tz, computed.today)
    banner = next((b for b in computed.banners if b.key == banner_key), None)
    if banner is None:
        archive.reveal_row = None
        return False
    if banner.key not in computed.open_keys:
        archive.expanded_banners, archive.folded_banners = with_banner_open(
            archive.expanded_banners,
            archive.folded_banners,
            banner.key,
            open=True,
            default_open=banner.key in computed.default_open,
        )
        return True
    if any(
        item.kind == ITEM_TAIL and item.banner_key == banner.key for item in model.items
    ):
        pages = dict(archive.loaded_pages)
        pages[banner.key] = max(1, int(pages.get(banner.key, 1) or 1)) + 1
        archive.loaded_pages = pages
        return True
    container = str(row.get("container_key") or "")
    if container and runtime.reveal_container != container:
        runtime.reveal_container = container
        if container not in archive.expanded_containers:
            archive.expanded_containers = (*archive.expanded_containers, container)
            return True
    archive.reveal_row = None
    runtime.reveal_container = None
    return False


def refresh_column(owner: Any, *, request: bool = True) -> None:
    """Re-plan windows, reassemble the list, and repaint the Archive column."""
    if not archive_detail_owns_panel(owner):
        return
    try:
        computed = _compute(owner)
        if _advance_reveal(owner, computed):
            computed = _compute(owner)
        if request and computed.usable:
            _request_if_needed(owner, computed)
        _install_model(owner, computed, _assemble(owner, computed))
    except Exception:
        log.debug("archive column refresh failed", exc_info=True)


def _install_model(owner: Any, computed: _Computed, model: ArchiveListModel) -> None:
    archive = column_archive(owner)
    runtime = column_runtime(owner)
    previous_key = archive.selected_key
    key = _normalize_cursor(archive, runtime, model)
    key = _apply_page_anchor(runtime, model, key)
    archive.selected_key = key
    runtime.model = model
    _paint(owner, computed, model)
    if key != previous_key or key != runtime.last_detail_key:
        schedule_detail(owner)


def _paint(owner: Any, computed: _Computed, model: ArchiveListModel) -> None:
    widget = column_widget(owner)
    if widget is None:
        return
    archive = column_archive(owner)
    widget.apply_items(
        model.items,
        archive.selected_key,
        tz=computed.tz,
        grouping=archive.grouping,
        restored_keys=archive.restored_keys,
        marked_keys=_archive_marked_keys(owner),
    )
    widget.set_section(archive.focused_section)
    widget.set_pulse(archive_inbox_pulse(owner))


def _archive_marked_keys(owner: Any) -> frozenset[str]:
    from ._archive_actions import archive_marked_run_keys

    return archive_marked_run_keys(owner)


def update_archive_pulse(owner: Any) -> None:
    """Repaint only the pulse so live Inbox ticks never touch the list or detail."""
    widget = column_widget(owner)
    if widget is None:
        return
    try:
        widget.set_pulse(archive_inbox_pulse(owner))
    except Exception:
        log.debug("archive pulse update failed", exc_info=True)


def on_archive_snapshot_applied(owner: Any) -> None:
    """Controller hook: a current-generation result landed."""
    refresh_column(owner)
    try:
        from ._archive_view import flush_pending_archive_list_scroll

        flush_pending_archive_list_scroll(owner)
    except Exception:
        log.debug("archive list scroll restore failed", exc_info=True)
    if archive_detail_owns_panel(owner):
        try:
            from ...widgets import AgentInfoPanel

            snapshot = archive_corpus_snapshot(owner)
            archive = column_archive(owner)
            owner.query_one("#agent-info-panel", AgentInfoPanel).set_archive_info(
                active=True,
                query=archive.committed_query,
                grouping=archive.grouping,
                count=snapshot.count,
                indexed_rows=snapshot.indexed_rows,
                status=snapshot.status,
                refreshing=snapshot.refreshing,
            )
        except Exception:
            log.debug("archive info row update failed", exc_info=True)
        refresh_archive_footer(owner)


def refresh_archive_footer(owner: Any) -> None:
    """Sync the conditional footer to Archive ownership.

    Detail renders update the footer on some paths (container summaries)
    but not others (placeholders, unreadable cards, empty states), so the
    footer must follow ownership itself: every applied snapshot and every
    chrome activation refreshes it, instead of piggybacking on whichever
    render path happened to run last.
    """
    try:
        refresh = getattr(owner, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh):
            refresh()
    except Exception:
        log.debug("archive footer sync failed", exc_info=True)


# --- chrome ---------------------------------------------------------------


def _agents_content(owner: Any) -> Any:
    query_one = getattr(owner, "query_one", None)
    if not callable(query_one):
        return None
    from textual.css.query import NoMatches

    try:
        return query_one("#agents-content")
    except NoMatches:
        return None


def _ensure_column(owner: Any, content: Any) -> Any:
    existing = column_widget(owner)
    if existing is not None:
        return existing
    from ...widgets.agents_archive import ArchiveColumn

    column = ArchiveColumn(id=_COLUMN_ID)
    content.mount(column, before="#agent-detail-container")
    setattr(owner, _WIDGET_ATTR, column)
    return column


def sync_archive_chrome(owner: Any, *, request: bool = True) -> None:
    """Show the Archive column (Archive view) or the Inbox column (Inbox view).

    The Archive column mounts lazily on first use. Both columns stay mounted:
    only the ``-archive-active`` class toggles, so the hidden Inbox keeps
    refreshing. ``request=False`` skips window requests (a caller that just
    pre-planned them).
    """
    active = archive_detail_owns_panel(owner)
    try:
        from ...widgets import AgentInfoPanel, AgentLoadIndicator, TabBar

        panel = owner.query_one("#agent-info-panel", AgentInfoPanel)
        if active:
            from ._archive_controller import archive_corpus_snapshot

            snapshot = archive_corpus_snapshot(owner)
            archive = column_archive(owner)
            panel.set_archive_info(
                active=True,
                query=archive.committed_query,
                grouping=archive.grouping,
                count=snapshot.count,
                indexed_rows=snapshot.indexed_rows,
                status=snapshot.status,
                refreshing=snapshot.refreshing,
            )
        else:
            panel.set_archive_info(active=False)
        try:
            owner.query_one("#agents-header").set_class(active, "archive-hidden")
        except Exception:
            pass
        try:
            indicator = owner.query_one("#agent-load-indicator", AgentLoadIndicator)
            if active:
                if not hasattr(owner, "_archive_saved_load_indicator_display"):
                    owner._archive_saved_load_indicator_display = indicator.display
                indicator.display = False
            elif hasattr(owner, "_archive_saved_load_indicator_display"):
                indicator.display = owner._archive_saved_load_indicator_display
                del owner._archive_saved_load_indicator_display
        except Exception:
            pass
        try:
            owner.query_one("#tab-bar", TabBar).set_agents_archive_active(active)
        except Exception:
            pass
    except Exception:
        log.debug("archive info chrome sync failed", exc_info=True)
    content = _agents_content(owner)
    try:
        if content is not None:
            if active:
                _ensure_column(owner, content)
            content.set_class(active, "-archive-active")
    except Exception:
        log.debug("archive chrome sync failed", exc_info=True)
        return
    if active:
        refresh_column(owner, request=request)
        widget = column_widget(owner)
        if widget is not None:
            widget.reveal_cursor()
        schedule_detail(owner)
        refresh_archive_footer(owner)
        return
    if column_widget(owner) is not None:
        repaint = getattr(owner, "_refresh_agents_display_debounced", None)
        if callable(repaint):
            repaint()


# --- detail seam ----------------------------------------------------------


def _paint_detail_placeholder(owner: Any) -> None:
    """Paint archived identity and the titled loading placeholder immediately."""
    from ._archive_reader import paint_archive_detail_placeholder

    paint_archive_detail_placeholder(owner)


def schedule_detail(owner: Any) -> None:
    """Paint identity immediately, then debounce pump-free hydration (150 ms)."""
    from ._archive_reader import arm_archive_detail_hydration

    column_runtime(owner).last_detail_key = column_archive(owner).selected_key
    # Call the local wrapper so tests can intercept the immediate paint
    # without patching the reader module.
    _paint_detail_placeholder(owner)
    arm_archive_detail_hydration(owner)
    refresh_archive_footer(owner)


__all__ = [
    "archive_container_members",
    "archive_light_row",
    "banner_is_default_open",
    "column_archive",
    "column_runtime",
    "column_widget",
    "on_archive_snapshot_applied",
    "plan_archive_view_windows",
    "refresh_column",
    "refresh_archive_footer",
    "schedule_detail",
    "sync_archive_chrome",
    "update_archive_pulse",
]

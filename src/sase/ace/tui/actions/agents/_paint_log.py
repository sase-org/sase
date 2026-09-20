"""Per-refresh paint observations for the Agents tab.

One :class:`_AgentsPaintFrame` is captured whenever an Agents-display refresh
completes, and again whenever the agent-list column width moves outside a
refresh. A frame records what the mounted ``AgentList`` panels look like at
that instant (widget identity, row count, collapse and grouping state,
negotiated widths and heights, highlight and scroll) next to the refresh's
``source`` / ``display_cost`` / ``fallback_reason``, so a panel's appearance
across consecutive refreshes can be asserted instead of aggregate counters.

Collection is off unless the app exposes ``_agents_paint_log`` as a list (tests)
or ``SASE_TUI_TRACE=1`` is set, in which case each frame is also emitted as an
``agents.paint_frame`` trace event.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal

from ...util.trace import is_enabled, trace_event
from ._display_helpers import agent_list_widgets_in, panel_widget_id_for_key
from ._panel_fold_intent import effective_panel_collapses
from ._refresh_trace import (
    AgentRefreshDisplayCost,
    normalize_refresh_source,
    paint_log_active,
    paint_log_collector,
    take_display_outcome,
)

log = logging.getLogger(__name__)

PaintFrameKind = Literal[
    "full_rebuild",
    "incremental",
    "highlight",
    "container_width",
    "settled",
]

# Only a completed refresh owns the display costs and fallback recorded since
# the previous frame; a width-change or settle observation must not consume them.
_REFRESH_KINDS: frozenset[PaintFrameKind] = frozenset(
    {"full_rebuild", "incremental", "highlight"}
)

_SEQ_ATTR = "_agents_paint_seq"


@dataclass(frozen=True)
class _PanelPaint:
    """One mounted ``AgentList`` as it looked when a frame was captured."""

    widget_id: str | None
    object_id: int
    option_count: int
    collapsed: bool
    # Whether the app's own collapse decision for this panel's slice says
    # collapsed (user collapse, fold intent, or an empty unexpanded slice).
    collapse_intent: bool
    grouping_mode: str
    requested_width: int
    height: str | None
    highlighted: int | None
    highlighted_identity: tuple[Any, ...] | None
    scroll_y: int
    viewport_height: int


@dataclass(frozen=True)
class _AgentsPaintFrame:
    """One observation of the Agents tab's visible panel state."""

    seq: int
    kind: PaintFrameKind
    source: str
    display_cost: AgentRefreshDisplayCost | None
    fallback_reason: str | None
    app_grouping_mode: str
    selected_identity: tuple[Any, ...] | None
    focused_widget_id: str | None
    # ``styles.width`` of ``#agent-list-container`` (cells), the width the app
    # has negotiated, versus the ``size.width`` the last layout pass resolved.
    container_width: int | None
    container_layout_width: int
    panels: tuple[_PanelPaint, ...]


def _container_style_width(container: Any) -> int | None:
    width = getattr(getattr(container, "styles", None), "width", None)
    value = getattr(width, "value", None)
    return None if value is None else int(value)


def _highlighted_identity(widget: Any) -> tuple[Any, ...] | None:
    row = getattr(widget, "highlighted", None)
    entries = getattr(widget, "_row_entries", [])
    agents = getattr(widget, "_agents", [])
    if row is None or not 0 <= row < len(entries):
        return None
    agent_idx = entries[row][0]
    if not 0 <= agent_idx < len(agents):
        return None
    return tuple(agents[agent_idx].identity)


def _panel_paints(app: Any, container: Any) -> tuple[_PanelPaint, ...]:
    group_keys = list(getattr(getattr(app, "_panel_group", None), "panel_keys", ()))
    # Observe the same mounted set the painter paints: occupancy plus
    # session-sticky keys. The group alone drops an emptied sticky panel whose
    # widget stays mounted as a collapsed strip, which would misreport that
    # strip's collapse intent as not collapsed.
    sorted_keys_fn = getattr(app, "_sorted_widget_panel_keys", None)
    occupancy_fn = getattr(app, "_occupancy_keys_with_rows", None)
    if callable(sorted_keys_fn) and callable(occupancy_fn):
        panel_keys = sorted_keys_fn(group_keys, occupancy_with_rows=occupancy_fn())
    else:
        panel_keys = group_keys
    collapsed_keys = effective_panel_collapses(app, panel_keys)
    panel_index = app._agent_panel_index()
    key_by_widget_id = {panel_widget_id_for_key(key): key for key in panel_keys}
    paints: list[_PanelPaint] = []
    for widget in agent_list_widgets_in(container):
        key = key_by_widget_id.get(widget.id)
        slice_agents = (
            panel_index.slice_for(key).agents if widget.id in key_by_widget_id else []
        )
        height = widget.styles.height
        paints.append(
            _PanelPaint(
                widget_id=widget.id,
                object_id=id(widget),
                option_count=int(widget.option_count),
                collapsed=bool(widget._panel_collapsed),
                collapse_intent=(
                    widget.id in key_by_widget_id
                    and app._panel_should_render_collapsed(
                        key, slice_agents, collapsed_keys
                    )
                ),
                grouping_mode=widget._grouping_mode.name,
                requested_width=int(widget._requested_width),
                height=None if height is None else str(height),
                highlighted=widget.highlighted,
                highlighted_identity=_highlighted_identity(widget),
                scroll_y=int(widget.scroll_y),
                viewport_height=int(widget.size.height),
            )
        )
    return tuple(paints)


def _capture_frame(app: Any, kind: PaintFrameKind) -> _AgentsPaintFrame:
    container = app.query_one("#agent-list-container")
    display_cost, fallback_reason = (
        take_display_outcome(app) if kind in _REFRESH_KINDS else (None, None)
    )
    seq = int(getattr(app, _SEQ_ATTR, 0))
    setattr(app, _SEQ_ATTR, seq + 1)
    agents = app._agents
    selected = (
        tuple(agents[app.current_idx].identity)
        if 0 <= app.current_idx < len(agents)
        else None
    )
    focused_key = app._panel_group.focused_key
    return _AgentsPaintFrame(
        seq=seq,
        kind=kind,
        source=normalize_refresh_source(
            getattr(app, "_agents_refresh_active_source", None)
        ),
        display_cost=display_cost,
        fallback_reason=fallback_reason,
        app_grouping_mode=app._grouping_mode.name,
        selected_identity=selected,
        focused_widget_id=panel_widget_id_for_key(focused_key),
        container_width=_container_style_width(container),
        container_layout_width=int(container.size.width),
        panels=_panel_paints(app, container),
    )


def record_agents_paint_frame(app: object, *, kind: PaintFrameKind) -> None:
    """Capture one paint frame when collection is enabled; else do nothing."""

    if not paint_log_active(app):
        return
    collector = paint_log_collector(app)
    try:
        frame = _capture_frame(app, kind)
    except Exception:
        # A diagnostic must never break a refresh; tests collecting into a
        # list still see the failure.
        if collector is not None:
            raise
        log.debug("agents paint frame capture failed", exc_info=True)
        return
    if collector is not None:
        collector.append(frame)
    if is_enabled():
        trace_event("agents.paint_frame", **asdict(frame))

"""Navigation and key-bound actions for the Agents-tab zoom panel modal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll

from ..widgets.tools_panel import ToolDetailLevel
from .zoom_panel_rendering import ACTIVE_STATUSES
from .zoom_panel_types import _TARGET_ORDER, ZoomPanelTarget
from .zoom_panel_widgets import ZoomFilePanel, ZoomToolsPanel

if TYPE_CHECKING:
    from ..models import Agent


def zoom_target_view_selector(target: ZoomPanelTarget) -> str:
    """Return the top-level view selector for a zoom panel target."""
    if target == ZoomPanelTarget.FILE:
        return "#zoom-file-view"
    return f"#zoom-{target.value}-scroll"


def available_targets(modal: Any) -> list[ZoomPanelTarget]:
    targets = [ZoomPanelTarget.METADATA]
    if modal._has_file_content:
        targets.append(ZoomPanelTarget.FILE)
    if modal._has_tools_content:
        targets.append(ZoomPanelTarget.TOOLS)
    return [target for target in _TARGET_ORDER if target in targets]


def show_target(modal: Any, target: ZoomPanelTarget) -> None:
    available = modal._available_targets()
    if target not in available:
        target = available[0]
    modal._target = target

    for item in _TARGET_ORDER:
        view = modal.query_one(zoom_target_view_selector(item))
        if item == modal._target:
            view.remove_class("hidden")
        else:
            view.add_class("hidden")
    modal._update_header()
    modal._update_hints()
    modal.call_after_refresh(modal._reset_active_scroll)


def active_scroll(modal: Any) -> VerticalScroll:
    if getattr(modal, "_is_zoom_search_overlay_visible", lambda: False)():
        return modal.query_one("#zoom-search-scroll", VerticalScroll)
    return modal.query_one(f"#zoom-{modal._target.value}-scroll", VerticalScroll)


def reset_active_scroll(modal: Any) -> None:
    try:
        active_scroll(modal).focus()
    except Exception:
        pass


def action_scroll_down(modal: Any) -> None:
    active_scroll(modal).scroll_relative(y=1, animate=False)


def action_scroll_up(modal: Any) -> None:
    active_scroll(modal).scroll_relative(y=-1, animate=False)


def action_scroll_half_down(modal: Any) -> None:
    scroll = active_scroll(modal)
    height = scroll.scrollable_content_region.height
    scroll.scroll_relative(y=max(1, height // 2), animate=False)


def action_scroll_half_up(modal: Any) -> None:
    scroll = active_scroll(modal)
    height = scroll.scrollable_content_region.height
    scroll.scroll_relative(y=-max(1, height // 2), animate=False)


def action_scroll_top(modal: Any) -> None:
    active_scroll(modal).scroll_home(animate=False)


def action_scroll_bottom(modal: Any) -> None:
    active_scroll(modal).scroll_end(animate=False)


def action_next_panel(modal: Any) -> None:
    cycle_target(modal, step=1)


def action_prev_panel(modal: Any) -> None:
    cycle_target(modal, step=-1)


def cycle_target(modal: Any, *, step: int) -> None:
    available = modal._available_targets()
    if len(available) <= 1:
        return
    modal._clear_reveal_state()
    current = available.index(modal._target) if modal._target in available else 0
    modal._show_target(available[(current + step) % len(available)])
    modal._refresh_active_panel(force=False)


def agent_has_files(modal: Any, agent: Agent) -> bool:
    if modal._seed.attempt_number is not None:
        return False
    if modal._has_file_content:
        return True
    if agent.all_files:
        return True
    return agent.status in ACTIVE_STATUSES


def reveal_file_panel(modal: Any, *, direction: str) -> bool:
    origin_target = modal._target
    agent = modal._agent_provider()
    if agent is None or not agent_has_files(modal, agent):
        modal.notify("No files for this agent", severity="warning")
        modal._update_header()
        return False

    modal._last_agent = agent
    modal._has_file_content = True
    modal._show_target(ZoomPanelTarget.FILE)
    modal._refresh_active_panel(force=False)
    # Record the reveal origin only if the file panel is actually active now
    # (an attempt-pinned refresh can bounce us back to metadata).
    if modal._target == ZoomPanelTarget.FILE:
        file_panel = modal.query_one("#zoom-file-panel", ZoomFilePanel)
        modal._reveal_origin_target = origin_target
        modal._reveal_direction = direction
        modal._reveal_file_index = file_panel.current_file_index
    return True


def clear_reveal_state(modal: Any) -> None:
    modal._reveal_origin_target = None
    modal._reveal_direction = None
    modal._reveal_file_index = None


def try_reveal_undo(modal: Any, *, pressed: str) -> bool:
    """Return to the reveal origin if ``pressed`` undoes a fresh reveal.

    Only the key opposite the reveal direction undoes, and only while the file
    panel still shows the just-revealed file (the user has not paged).
    """
    if modal._reveal_origin_target is None or modal._reveal_direction is None:
        return False
    opposite = {"next": "prev", "prev": "next"}[modal._reveal_direction]
    if pressed != opposite:
        return False
    file_panel = modal.query_one("#zoom-file-panel", ZoomFilePanel)
    if (
        modal._reveal_file_index is None
        or file_panel.current_file_index != modal._reveal_file_index
    ):
        return False
    origin = modal._reveal_origin_target
    clear_reveal_state(modal)
    modal._show_target(origin)
    modal._refresh_active_panel(force=False)
    return True


def action_next_file(modal: Any) -> None:
    if modal._target != ZoomPanelTarget.FILE:
        reveal_file_panel(modal, direction="next")
        return
    if try_reveal_undo(modal, pressed="next"):
        return
    clear_reveal_state(modal)
    modal.query_one("#zoom-file-panel", ZoomFilePanel).next_file()
    modal._update_header()


def action_prev_file(modal: Any) -> None:
    if modal._target != ZoomPanelTarget.FILE:
        reveal_file_panel(modal, direction="prev")
        return
    if try_reveal_undo(modal, pressed="prev"):
        return
    clear_reveal_state(modal)
    modal.query_one("#zoom-file-panel", ZoomFilePanel).prev_file()
    modal._update_header()


def action_expand_tools_detail(modal: Any) -> None:
    if modal._target == ZoomPanelTarget.TOOLS:
        modal.query_one("#zoom-tools-panel", ZoomToolsPanel).expand_detail()


def action_collapse_tools_detail(modal: Any) -> None:
    if modal._target == ZoomPanelTarget.TOOLS:
        modal.query_one("#zoom-tools-panel", ZoomToolsPanel).collapse_detail()


def action_full_tools_detail(modal: Any) -> None:
    if modal._target == ZoomPanelTarget.TOOLS:
        modal.query_one("#zoom-tools-panel", ZoomToolsPanel).set_detail_level(
            ToolDetailLevel.FULL
        )


def action_compact_tools_detail(modal: Any) -> None:
    if modal._target == ZoomPanelTarget.TOOLS:
        modal.query_one("#zoom-tools-panel", ZoomToolsPanel).set_detail_level(
            ToolDetailLevel.COMPACT
        )

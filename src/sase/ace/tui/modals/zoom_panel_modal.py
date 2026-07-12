"""Near-fullscreen zoom modal for Agents-tab detail panels."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Label, Static

from ..widgets.file_panel import (
    FileLineCountChanged,
    FileListChanged,
    FileVisibilityChanged,
)
from ..widgets.prompt_panel import AgentPromptPanel
from ..widgets.tools_panel import ToolsVisibilityChanged
from .zoom_panel_content import (
    action_copy_zoom_content,
    action_edit_zoom_content,
    action_refresh_zoom_content,
    editor_info,
    open_in_editor,
    refresh_active_panel,
    refresh_file,
    refresh_metadata,
    refresh_tools,
    seed_panels,
    zoom_text,
)
from .zoom_panel_events import (
    on_file_list_changed,
    on_file_line_count_changed,
    on_file_visibility_changed,
    on_tools_visibility_changed,
)
from .zoom_panel_navigation import (
    action_collapse_tools_detail,
    action_compact_tools_detail,
    action_expand_tools_detail,
    action_full_tools_detail,
    action_next_file,
    action_next_panel,
    action_prev_file,
    action_prev_panel,
    action_scroll_bottom,
    action_scroll_down,
    action_scroll_half_down,
    action_scroll_half_up,
    action_scroll_top,
    action_scroll_up,
    active_scroll,
    agent_has_files,
    available_targets,
    clear_reveal_state,
    cycle_target,
    reset_active_scroll,
    reveal_file_panel,
    show_target,
    try_reveal_undo,
)
from .zoom_panel_rendering import agent_label, renderable_to_text, status_text
from .zoom_panel_search import ZoomSearchMixin
from .zoom_panel_types import ZoomPanelSeed, ZoomPanelTarget
from .zoom_panel_widgets import ZoomFilePanel, ZoomFileRail, ZoomToolsPanel

if TYPE_CHECKING:
    from ..models import Agent


_renderable_to_text = renderable_to_text
_status_text = status_text
_ZoomFilePanel = ZoomFilePanel
_ZoomFileRail = ZoomFileRail
_ZoomToolsPanel = ZoomToolsPanel

_HEADER_TAB_STYLE = {
    ZoomPanelTarget.METADATA: "bold black on #D7AF5F",
    ZoomPanelTarget.FILE: "bold black on #A8FF60",
    ZoomPanelTarget.TOOLS: "bold black on #87D7FF",
}


class ZoomPanelModal(ZoomSearchMixin, ModalScreen[None]):
    """Modal that zooms one Agents-tab detail panel at a time."""

    BINDINGS = [
        Binding("q,escape,z", "close_zoom", "Close"),
        Binding("j,down", "scroll_down", "Down"),
        Binding("k,up", "scroll_up", "Up"),
        Binding("ctrl+d", "scroll_half_down", "Half Down"),
        Binding("ctrl+u", "scroll_half_up", "Half Up"),
        Binding("g", "scroll_top", "Top"),
        Binding("G", "scroll_bottom", "Bottom"),
        Binding("right_square_bracket", "next_panel", "Next Panel"),
        Binding("left_square_bracket", "prev_panel", "Prev Panel"),
        Binding("l", "expand_tools_detail", "More Detail"),
        Binding("h", "collapse_tools_detail", "Less Detail"),
        Binding("L", "full_tools_detail", "Full Detail"),
        Binding("H", "compact_tools_detail", "Compact Detail"),
        Binding("ctrl+n", "next_file", "Next File"),
        Binding("ctrl+p", "prev_file", "Prev File"),
        Binding("E", "edit_zoom_content", "Edit"),
        Binding("y", "copy_zoom_content", "Copy"),
        Binding("r", "refresh_zoom_content", "Refresh"),
    ]

    def __init__(
        self,
        *,
        agent_provider: Callable[[], Agent | None],
        initial_agent: Agent,
        initial_target: ZoomPanelTarget,
        seed: ZoomPanelSeed,
        refresh_interval: int,
    ) -> None:
        super().__init__()
        self._agent_provider = agent_provider
        self._last_agent = initial_agent
        self._target = initial_target
        self._seed = seed
        self._has_file_content = seed.has_file_content
        self._has_tools_content = seed.has_tools_content
        self._refresh_interval = max(refresh_interval, 2)
        self._refresh_timer: Timer | None = None
        self._metadata_generation = 0
        self._content_seeded = False
        # Reveal-undo state: when Ctrl-N/Ctrl-P reveals the file panel from
        # another target, remember where we came from so the immediately
        # opposite keypress can return there instead of paging files.
        self._reveal_origin_target: ZoomPanelTarget | None = None
        self._reveal_direction: str | None = None
        self._reveal_file_index: int | None = None

    def compose(self) -> ComposeResult:
        """Compose the zoom modal."""
        with Container(id="zoom-panel-container"):
            with Horizontal(id="zoom-panel-header"):
                yield Static(id="zoom-panel-title")
                yield Static(id="zoom-panel-agent")
            with VerticalScroll(
                id="zoom-metadata-scroll", classes="hidden zoom-scroll"
            ):
                yield AgentPromptPanel(id="zoom-metadata-panel")
            with Horizontal(id="zoom-file-view", classes="hidden"):
                yield ZoomFileRail(id="zoom-file-rail", classes="collapsed")
                with VerticalScroll(id="zoom-file-scroll", classes="zoom-scroll"):
                    yield ZoomFilePanel(id="zoom-file-panel")
            with VerticalScroll(id="zoom-tools-scroll", classes="hidden zoom-scroll"):
                yield ZoomToolsPanel(id="zoom-tools-panel")
            with VerticalScroll(id="zoom-search-scroll", classes="hidden zoom-scroll"):
                yield Static(id="zoom-search-panel")
            yield Static(id="zoom-search-command", classes="hidden")
            yield Label(
                "j/k g/G ^D/^U scroll  /? search  n/N match  ]/[ panel  ^N/^P file  E edit  y copy  r refresh  q close",
                id="zoom-panel-hints",
            )

    def on_mount(self) -> None:
        """Seed the hosted panels and start live refresh."""
        self._seed_panels()
        self._show_target(self._target)
        self._refresh_active_panel(force=False)
        self._refresh_timer = self.set_interval(
            self._refresh_interval,
            lambda: self._refresh_active_panel(force=False),
        )

    def on_unmount(self) -> None:
        """Stop the modal-local refresh timer."""
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def _update_hints(self) -> None:
        hints = (
            "j/k g/G ^D/^U scroll  ]/[ panel  ^N/^P file  "
            "/? search  n/N match  E edit  y copy  r refresh  q close"
        )
        if self._target == ZoomPanelTarget.TOOLS:
            hints = (
                "j/k g/G ^D/^U scroll  ]/[ panel  h/l detail  "
                "/? search  n/N match  E edit  y copy  r refresh  q close"
            )
        self.query_one("#zoom-panel-hints", Label).update(hints)

    def _update_header(self) -> None:
        title = self.query_one("#zoom-panel-title", Static)
        agent_label_widget = self.query_one("#zoom-panel-agent", Static)

        available = self._available_targets()
        text = Text("ZOOM  ", style="bold")
        for index, target in enumerate(available):
            if index > 0:
                text.append(" · ", style="dim")
            label = target.value.upper()
            if target == ZoomPanelTarget.FILE and self._has_file_content:
                file_panel = self.query_one("#zoom-file-panel", ZoomFilePanel)
                if file_panel.current_file_count > 1:
                    label = (
                        f"FILE {file_panel.current_file_index + 1}/"
                        f"{file_panel.current_file_count}"
                    )
            if target == self._target:
                text.append(f" {label} ", style=_HEADER_TAB_STYLE[target])
            else:
                text.append(label, style="dim")

        title.update(text)
        self._update_rail()

        agent = self._agent_provider() or self._last_agent
        if agent is not None:
            self._last_agent = agent
        label = agent_label(agent)
        status = status_text(agent.status if agent is not None else "MISSING")
        agent_label_widget.update(Text.assemble((label, "bold"), "  ", status))

    def _update_rail(self) -> None:
        rail = self.query_one("#zoom-file-rail", ZoomFileRail)
        if self._target != ZoomPanelTarget.FILE or not self._has_file_content:
            rail.update_entries((), 0)
            return
        file_panel = self.query_one("#zoom-file-panel", ZoomFilePanel)
        rail.update_entries(
            file_panel.file_source_labels(), file_panel.current_file_index
        )

    def _seed_panels(self) -> None:
        seed_panels(self)

    def _refresh_active_panel(self, *, force: bool) -> None:
        refresh_active_panel(self, force=force)

    def _refresh_metadata(self, agent: Agent) -> None:
        refresh_metadata(self, agent)

    def _refresh_file(self, agent: Agent, *, force: bool) -> None:
        refresh_file(self, agent, force=force)

    def _refresh_tools(self, agent: Agent, *, force: bool) -> None:
        refresh_tools(self, agent, force=force)

    def _zoom_text(self) -> str | None:
        return zoom_text(self)

    def _editor_info(self) -> tuple[str | None, str | None, str]:
        return editor_info(self)

    def _open_in_editor(
        self, file_path: str | None, content: str | None, suffix: str
    ) -> None:
        open_in_editor(self, file_path, content, suffix)

    def _available_targets(self) -> list[ZoomPanelTarget]:
        return available_targets(self)

    def _show_target(self, target: ZoomPanelTarget) -> None:
        show_target(self, target)

    def _active_scroll(self) -> VerticalScroll:
        return active_scroll(self)

    def _reset_active_scroll(self) -> None:
        reset_active_scroll(self)

    def _cycle_target(self, *, step: int) -> None:
        cycle_target(self, step=step)

    def _agent_has_files(self, agent: Agent) -> bool:
        return agent_has_files(self, agent)

    def _reveal_file_panel(self, *, direction: str) -> bool:
        return reveal_file_panel(self, direction=direction)

    def _clear_reveal_state(self) -> None:
        clear_reveal_state(self)

    def _try_reveal_undo(self, *, pressed: str) -> bool:
        return try_reveal_undo(self, pressed=pressed)

    def on_file_visibility_changed(self, message: FileVisibilityChanged) -> None:
        on_file_visibility_changed(self, message)

    def on_file_list_changed(self, message: FileListChanged) -> None:
        on_file_list_changed(self, message)

    def on_file_line_count_changed(self, message: FileLineCountChanged) -> None:
        on_file_line_count_changed(self, message)

    def on_tools_visibility_changed(self, message: ToolsVisibilityChanged) -> None:
        on_tools_visibility_changed(self, message)

    def on_key(self, event: Key) -> None:
        """Capture search keys before modal bindings or app bindings fire."""
        if self._handle_zoom_search_key(event):
            event.prevent_default()
            event.stop()

    def action_close_zoom(self) -> None:
        """Close the zoom modal."""
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        action_scroll_down(self)

    def action_scroll_up(self) -> None:
        action_scroll_up(self)

    def action_scroll_half_down(self) -> None:
        action_scroll_half_down(self)

    def action_scroll_half_up(self) -> None:
        action_scroll_half_up(self)

    def action_scroll_top(self) -> None:
        action_scroll_top(self)

    def action_scroll_bottom(self) -> None:
        action_scroll_bottom(self)

    def action_next_panel(self) -> None:
        action_next_panel(self)

    def action_prev_panel(self) -> None:
        action_prev_panel(self)

    def action_next_file(self) -> None:
        action_next_file(self)

    def action_prev_file(self) -> None:
        action_prev_file(self)

    def action_expand_tools_detail(self) -> None:
        action_expand_tools_detail(self)

    def action_collapse_tools_detail(self) -> None:
        action_collapse_tools_detail(self)

    def action_full_tools_detail(self) -> None:
        action_full_tools_detail(self)

    def action_compact_tools_detail(self) -> None:
        action_compact_tools_detail(self)

    def action_edit_zoom_content(self) -> None:
        action_edit_zoom_content(self)

    def action_copy_zoom_content(self) -> None:
        action_copy_zoom_content(self)

    def action_refresh_zoom_content(self) -> None:
        action_refresh_zoom_content(self)


__all__ = ["ZoomPanelModal", "ZoomPanelSeed", "ZoomPanelTarget"]

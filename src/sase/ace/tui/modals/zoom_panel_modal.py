"""Near-fullscreen zoom modal for Agents-tab detail panels."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO
from typing import TYPE_CHECKING, Any

from rich.console import Console, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Label, Static

from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    PLAN_APPROVED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)
from sase.core.paths import get_sase_tmpdir

from ..actions.clipboard import copy_to_system_clipboard
from ..models.agent_status import STOPPED_COLOR, STOPPED_GLYPH, STOPPED_STATUS
from ..widgets.file_panel import (
    AgentFilePanel,
    FileListChanged,
    FileTrimChanged,
    FileVisibilityChanged,
)
from ..widgets.prompt_panel import AgentPromptPanel
from ..widgets.tools_panel import AgentToolsPanel, ToolsVisibilityChanged

if TYPE_CHECKING:
    from ..models import Agent


class ZoomPanelTarget(StrEnum):
    """Panel targets supported by the Agents-tab zoom modal."""

    METADATA = "metadata"
    FILE = "file"
    TOOLS = "tools"


@dataclass(frozen=True)
class ZoomPanelSeed:
    """Lightweight state copied from the base Agents detail panels."""

    metadata_renderable: RenderableType | None = None
    file_renderable: RenderableType | None = None
    tools_renderable: RenderableType | None = None
    metadata_subtitle: Any = None
    file_subtitle: Any = None
    tools_subtitle: Any = None
    file_list: tuple[str, ...] = ()
    file_index: int = 0
    has_file_content: bool = False
    has_tools_content: bool = False
    attempt_view_mode: str = "merged"
    attempt_number: int | None = None


_TARGET_ORDER: tuple[ZoomPanelTarget, ...] = (
    ZoomPanelTarget.METADATA,
    ZoomPanelTarget.FILE,
    ZoomPanelTarget.TOOLS,
)


class _ZoomFilePanel(AgentFilePanel):
    """Agent file panel variant whose scroll container lives inside the modal."""

    def _get_scroll_container(self) -> VerticalScroll | None:
        try:
            return self.screen.query_one("#zoom-file-scroll", VerticalScroll)
        except Exception:
            return None


class _ZoomToolsPanel(AgentToolsPanel):
    """Agent tools panel variant whose scroll container lives inside the modal."""

    def _get_scroll_container(self) -> VerticalScroll | None:
        try:
            return self.screen.query_one("#zoom-tools-scroll", VerticalScroll)
        except Exception:
            return None


class ZoomPanelModal(ModalScreen[None]):
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
        Binding("ctrl+n", "next_file", "Next File"),
        Binding("ctrl+p", "prev_file", "Prev File"),
        Binding("equals_sign", "show_all_file_lines", "Show All"),
        Binding("minus", "reset_file_trim", "Reset Trim"),
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
            with VerticalScroll(id="zoom-file-scroll", classes="hidden zoom-scroll"):
                yield _ZoomFilePanel(id="zoom-file-panel")
            with VerticalScroll(id="zoom-tools-scroll", classes="hidden zoom-scroll"):
                yield _ZoomToolsPanel(id="zoom-tools-panel")
            yield Label(
                "j/k g/G ^D/^U scroll  ]/[ panel  ^N/^P file  E edit  y copy  r refresh  q close",
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

    def _seed_panels(self) -> None:
        """Paint base-panel renderables immediately to avoid an empty first frame."""
        if self._content_seeded:
            return
        self._content_seeded = True
        if self._seed.metadata_renderable:
            self.query_one("#zoom-metadata-panel", AgentPromptPanel).update(
                self._seed.metadata_renderable
            )
        self.query_one("#zoom-metadata-scroll", VerticalScroll).border_subtitle = (
            self._seed.metadata_subtitle or ""
        )
        file_panel = self.query_one("#zoom-file-panel", _ZoomFilePanel)
        if self._seed.file_renderable:
            file_panel.update(self._seed.file_renderable)
        self.query_one("#zoom-file-scroll", VerticalScroll).border_subtitle = (
            self._seed.file_subtitle or ""
        )
        file_panel._current_agent = self._last_agent
        if self._seed.file_list:
            file_panel._file_list = list(self._seed.file_list)
            file_panel._current_file_index = min(
                max(self._seed.file_index, 0),
                len(self._seed.file_list) - 1,
            )
        if self._seed.tools_renderable:
            self.query_one("#zoom-tools-panel", _ZoomToolsPanel).update(
                self._seed.tools_renderable
            )
        self.query_one("#zoom-tools-scroll", VerticalScroll).border_subtitle = (
            self._seed.tools_subtitle or ""
        )

    def _available_targets(self) -> list[ZoomPanelTarget]:
        targets = [ZoomPanelTarget.METADATA]
        if self._has_file_content:
            targets.append(ZoomPanelTarget.FILE)
        if self._has_tools_content:
            targets.append(ZoomPanelTarget.TOOLS)
        return [target for target in _TARGET_ORDER if target in targets]

    def _show_target(self, target: ZoomPanelTarget) -> None:
        available = self._available_targets()
        if target not in available:
            target = available[0]
        self._target = target

        for item in _TARGET_ORDER:
            scroll = self.query_one(f"#zoom-{item.value}-scroll", VerticalScroll)
            if item == self._target:
                scroll.remove_class("hidden")
            else:
                scroll.add_class("hidden")
        self._update_header()
        self.call_after_refresh(self._reset_active_scroll)

    def _update_header(self) -> None:
        title = self.query_one("#zoom-panel-title", Static)
        agent_label = self.query_one("#zoom-panel-agent", Static)

        available = self._available_targets()
        position = available.index(self._target) + 1 if self._target in available else 1
        total = len(available)
        target_name = self._target.value.upper()
        if self._target == ZoomPanelTarget.FILE and self._has_file_content:
            file_panel = self.query_one("#zoom-file-panel", _ZoomFilePanel)
            if file_panel.current_file_count > 1:
                target_name = (
                    f"FILE ({file_panel.current_file_index + 1}/"
                    f"{file_panel.current_file_count})"
                )
            source_label = file_panel.current_source_label()
            if source_label:
                target_name = f"{target_name} · {source_label}"

        title.update(f"⛶ ZOOM - {target_name} ({position}/{total})")

        agent = self._agent_provider() or self._last_agent
        if agent is not None:
            self._last_agent = agent
        label = _agent_label(agent)
        status = _status_text(agent.status if agent is not None else "MISSING")
        agent_label.update(Text.assemble((label, "bold"), "  ", status))

    def _refresh_active_panel(self, *, force: bool) -> None:
        agent = self._agent_provider()
        if agent is None:
            self._update_header()
            return
        self._last_agent = agent
        if self._target == ZoomPanelTarget.METADATA:
            self._refresh_metadata(agent)
        elif self._target == ZoomPanelTarget.FILE:
            self._refresh_file(agent, force=force)
        else:
            self._refresh_tools(agent, force=force)
        self._update_header()

    def _refresh_metadata(self, agent: Agent) -> None:
        panel = self.query_one("#zoom-metadata-panel", AgentPromptPanel)
        panel.attempt_view_mode = self._seed.attempt_view_mode
        panel.attempt_pinned_number = self._seed.attempt_number
        self._metadata_generation += 1
        generation = self._metadata_generation

        def is_current(
            agent_identity: tuple[Any, ...],
            worker_generation: int,
            attempt_view_mode: str,
            attempt_pinned_number: int | None,
        ) -> bool:
            current = self._agent_provider()
            return (
                current is not None
                and current.identity == agent_identity
                and self._metadata_generation == worker_generation
                and self._seed.attempt_view_mode == attempt_view_mode
                and self._seed.attempt_number == attempt_pinned_number
                and self._target == ZoomPanelTarget.METADATA
            )

        if (
            self._seed.attempt_number is None
            and agent.agent_type.value == "workflow"
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        ):
            panel.start_workflow_detail_render(
                agent,
                generation=generation,
                attempt_view_mode=self._seed.attempt_view_mode,
                attempt_pinned_number=self._seed.attempt_number,
                is_current=is_current,
            )
            return
        set_render_context = getattr(panel, "set_agent_detail_render_context", None)
        if callable(set_render_context):
            set_render_context(
                generation=generation,
                attempt_view_mode=self._seed.attempt_view_mode,
                attempt_pinned_number=self._seed.attempt_number,
                is_current=is_current,
            )
        panel.update_display(agent)

    def _refresh_file(self, agent: Agent, *, force: bool) -> None:
        panel = self.query_one("#zoom-file-panel", _ZoomFilePanel)
        if self._seed.attempt_number is not None:
            panel.show_empty()
            self._has_file_content = False
            self._show_target(ZoomPanelTarget.METADATA)
            return

        if force:
            current_path = panel.get_current_file_path()
            if current_path is not None:
                panel.display_static_file(current_path)
            else:
                panel.refresh_file(agent)
            return

        files = agent.all_files
        if agent.status not in _ACTIVE_STATUSES and files:
            start_index = min(max(panel.current_file_index, 0), len(files) - 1)
            if panel.current_file_count == 0 and self._seed.file_list:
                start_index = min(max(self._seed.file_index, 0), len(files) - 1)
            panel.set_file_list(files, start_index=start_index)
        else:
            panel.update_display(agent, stale_threshold_seconds=self._refresh_interval)
        # Initial renders can happen before the modal is laid out (hidden
        # container -> trim size 0), so retry the default trim until the
        # panel has a measured viewport. Once a trim size is established,
        # leave it alone: re-trimming every tick would revert the user's
        # show-all (=) / reset (-) adjustments.
        if panel._base_trim_size <= 0:
            self.call_after_refresh(panel.reset_trim)

    def _refresh_tools(self, agent: Agent, *, force: bool) -> None:
        panel = self.query_one("#zoom-tools-panel", _ZoomToolsPanel)
        if force:
            panel.refresh_tools(agent)
        else:
            panel.update_display(agent, stale_threshold_seconds=self._refresh_interval)

    def _active_scroll(self) -> VerticalScroll:
        return self.query_one(f"#zoom-{self._target.value}-scroll", VerticalScroll)

    def _reset_active_scroll(self) -> None:
        try:
            self._active_scroll().focus()
        except Exception:
            pass

    def _zoom_text(self) -> str | None:
        file_path: str | None = None
        if self._target == ZoomPanelTarget.FILE:
            file_panel = self.query_one("#zoom-file-panel", _ZoomFilePanel)
            content = file_panel.get_current_content()
            if content:
                return content
            file_path = file_panel.get_current_file_path()
        elif self._target == ZoomPanelTarget.TOOLS:
            content = self.query_one(
                "#zoom-tools-panel", _ZoomToolsPanel
            ).get_tools_text()
            if content:
                return content
        active_panel = self.query_one(f"#zoom-{self._target.value}-panel", Static)
        rendered_text = _renderable_to_text(getattr(active_panel, "content", None))
        return rendered_text or file_path

    def _editor_info(self) -> tuple[str | None, str | None, str]:
        if self._target == ZoomPanelTarget.FILE:
            panel = self.query_one("#zoom-file-panel", _ZoomFilePanel)
            return panel.get_current_file_path(), panel.get_current_content(), ".diff"
        if self._target == ZoomPanelTarget.TOOLS:
            return (
                None,
                self.query_one("#zoom-tools-panel", _ZoomToolsPanel).get_tools_text(),
                ".md",
            )
        return (None, self._zoom_text(), ".md")

    def _open_in_editor(
        self, file_path: str | None, content: str | None, suffix: str
    ) -> None:
        editor = os.environ.get("EDITOR") or "nvim"
        if file_path is not None:
            with self.app.suspend():  # type: ignore[attr-defined]
                subprocess.run([editor, os.path.expanduser(file_path)], check=False)
            return
        if content is None:
            self.notify("No content to edit", severity="warning")
            return
        fd, tmp_path = tempfile.mkstemp(
            suffix=suffix,
            prefix="sase_ace_zoom_",
            dir=get_sase_tmpdir(),
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            with self.app.suspend():  # type: ignore[attr-defined]
                subprocess.run([editor, tmp_path], check=False)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def on_file_visibility_changed(self, message: FileVisibilityChanged) -> None:
        """Track file availability inside the modal."""
        self._has_file_content = message.has_file
        self._update_header()
        if not message.has_file and self._target == ZoomPanelTarget.FILE:
            self._show_target(ZoomPanelTarget.METADATA)
        message.stop()

    def on_file_list_changed(self, message: FileListChanged) -> None:
        """Refresh the header counter after file cycling."""
        self._has_file_content = message.file_count > 0
        self._update_header()
        message.stop()

    def on_file_trim_changed(self, message: FileTrimChanged) -> None:
        """Mirror file trim state in the modal border subtitle."""
        scroll = self.query_one("#zoom-file-scroll", VerticalScroll)
        if message.total_lines == 0:
            scroll.border_subtitle = ""
        elif message.is_trimmed:
            scroll.border_subtitle = Text(
                f"Lines 1-{message.visible_lines} of {message.total_lines}",
                style="dim #87D7FF",
            )
        else:
            scroll.border_subtitle = Text(
                f"{message.total_lines} lines",
                style="dim #5FAFAF",
            )
        message.stop()

    def on_tools_visibility_changed(self, message: ToolsVisibilityChanged) -> None:
        """Track tools availability inside the modal."""
        self._has_tools_content = message.has_tools
        self._update_header()
        if not message.has_tools and self._target == ZoomPanelTarget.TOOLS:
            self._show_target(ZoomPanelTarget.METADATA)
        message.stop()

    def action_close_zoom(self) -> None:
        """Close the zoom modal."""
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        self._active_scroll().scroll_relative(y=1, animate=False)

    def action_scroll_up(self) -> None:
        self._active_scroll().scroll_relative(y=-1, animate=False)

    def action_scroll_half_down(self) -> None:
        scroll = self._active_scroll()
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=max(1, height // 2), animate=False)

    def action_scroll_half_up(self) -> None:
        scroll = self._active_scroll()
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-max(1, height // 2), animate=False)

    def action_scroll_top(self) -> None:
        self._active_scroll().scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self._active_scroll().scroll_end(animate=False)

    def action_next_panel(self) -> None:
        self._cycle_target(step=1)

    def action_prev_panel(self) -> None:
        self._cycle_target(step=-1)

    def _cycle_target(self, *, step: int) -> None:
        available = self._available_targets()
        if len(available) <= 1:
            return
        current = available.index(self._target) if self._target in available else 0
        self._show_target(available[(current + step) % len(available)])
        self._refresh_active_panel(force=False)

    def _agent_has_files(self, agent: Agent) -> bool:
        if self._seed.attempt_number is not None:
            return False
        if self._has_file_content:
            return True
        if agent.all_files:
            return True
        return agent.status in _ACTIVE_STATUSES

    def _reveal_file_panel(self) -> bool:
        agent = self._agent_provider()
        if agent is None or not self._agent_has_files(agent):
            self.notify("No files for this agent", severity="warning")
            self._update_header()
            return False

        self._last_agent = agent
        self._has_file_content = True
        self._show_target(ZoomPanelTarget.FILE)
        self._refresh_active_panel(force=False)
        return True

    def action_next_file(self) -> None:
        if self._target != ZoomPanelTarget.FILE:
            self._reveal_file_panel()
            return
        self.query_one("#zoom-file-panel", _ZoomFilePanel).next_file()
        self._update_header()

    def action_prev_file(self) -> None:
        if self._target != ZoomPanelTarget.FILE:
            self._reveal_file_panel()
            return
        self.query_one("#zoom-file-panel", _ZoomFilePanel).prev_file()
        self._update_header()

    def action_show_all_file_lines(self) -> None:
        if self._target == ZoomPanelTarget.FILE:
            self.query_one("#zoom-file-panel", _ZoomFilePanel).show_all_lines()

    def action_reset_file_trim(self) -> None:
        if self._target == ZoomPanelTarget.FILE:
            self.query_one("#zoom-file-panel", _ZoomFilePanel).reset_trim()

    def action_edit_zoom_content(self) -> None:
        self._open_in_editor(*self._editor_info())

    def action_copy_zoom_content(self) -> None:
        content = self._zoom_text()
        if not content:
            self.notify("No content to copy", severity="warning")
            return
        line_count = content.count("\n") + (1 if not content.endswith("\n") else 0)
        if copy_to_system_clipboard(content):
            self.notify(f"Copied: zoom content ({line_count} lines)")
        else:
            self.notify("Copy failed - clipboard tool not available", severity="error")

    def action_refresh_zoom_content(self) -> None:
        self._refresh_active_panel(force=True)


def _agent_label(agent: Agent | None) -> str:
    if agent is None:
        return "agent missing"
    name = agent.agent_name or agent.display_name
    return name[:72] + "..." if len(name) > 75 else name


def _status_text(status: str) -> Text:
    style = {
        "RUNNING": "bold green",
        "WAITING": "bold yellow",
        "WAITING INPUT": "bold yellow",
        "QUESTION": "bold yellow",
        "ANSWERED": "bold #5FD7FF",
        "PLAN": "bold #FFD787",
        PLAN_APPROVED_STATUS: "bold #FFD787",
        TALE_APPROVED_STATUS: "bold #FFD7AF",
        WORKING_PLAN_STATUS: "bold #FFAF87",
        WORKING_TALE_STATUS: "bold #FFAFAF",
        "DONE": "bold cyan",
        "FAILED": "bold red",
        "MISSING": "dim",
        STOPPED_STATUS: f"bold {STOPPED_COLOR}",
    }.get(status, "bold")
    if status == STOPPED_STATUS:
        icon = STOPPED_GLYPH
    else:
        icon = "▶" if status in _ACTIVE_STATUSES else "●"
    return Text(f"{icon} {status}", style=style)


def _renderable_to_text(renderable: object) -> str | None:
    if renderable is None:
        return None
    console = Console(record=True, width=120, color_system=None, file=StringIO())
    console.print(renderable)
    text = console.export_text(clear=True).rstrip()
    return text or None


_ACTIVE_STATUSES = frozenset(
    {
        "RUNNING",
        "WAITING",
        "WAITING INPUT",
        "PLAN",
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "QUESTION",
        "ANSWERED",
        "RETRYING",
    }
)


__all__ = ["ZoomPanelModal", "ZoomPanelSeed", "ZoomPanelTarget"]

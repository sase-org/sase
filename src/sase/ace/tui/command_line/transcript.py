"""Transcript widgets for the Command Line panel.

Each block renders its gutter glyph, command, right-aligned metadata, and a
collapsed body (last 12 lines) fed by :class:`ProcLogCursor`. A pump-free
task polls only visible running blocks every 200 ms while the panel is
shown; a running block repaints only its own widget.
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.command_line.block_render import (
    BLOCK_SPINNER_FRAMES,
    block_header_right,
    collapsed_body_lines,
    expanded_body_lines,
    gutter_glyph,
    render_block_output,
)
from sase.ace.tui.command_line.session import CommandLineBlock
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.procs.logs import ProcLogCursor

#: Tail poll interval in seconds.
TAIL_POLL_SECONDS = 0.2


#: Divider above blocks restored from the proc store after a restart.
EARLIER_DIVIDER = "── earlier ──"


class _CommandLineBlockWidget(Static):
    """One transcript block widget; repaints only itself on tail ticks."""

    def __init__(
        self,
        block: CommandLineBlock,
        *,
        selected: bool = False,
        show_divider: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            self.render_block(block, selected=selected, show_divider=show_divider),
            **kwargs,
        )
        self._block = block
        self._selected = selected
        self._show_divider = show_divider
        self._spinner_index = 0

    @property
    def block(self) -> CommandLineBlock:
        """Return the session block this widget renders."""
        return self._block

    def repaint(self) -> None:
        """Re-render this block's content from session state."""
        self.update(
            self.render_block(
                self._block,
                spinner_index=self._spinner_index,
                selected=self._selected,
                show_divider=self._show_divider,
            )
        )

    def set_state(self, *, selected: bool, show_divider: bool) -> None:
        """Update the selection bar and divider, then repaint."""
        self._selected = selected
        self._show_divider = show_divider

    @staticmethod
    def render_block(
        block: CommandLineBlock,
        *,
        spinner_index: int = 0,
        selected: bool = False,
        show_divider: bool = False,
    ) -> Text:
        """Build the block's renderable from session state (pure)."""
        glyph = gutter_glyph(
            block.status, exit_code=block.exit_code, declined=block.declined
        )
        if block.status in ("submitting", "running"):
            glyph = BLOCK_SPINNER_FRAMES[spinner_index % len(BLOCK_SPINNER_FRAMES)]
        header_right = block_header_right(
            block.status,
            exit_code=block.exit_code,
            elapsed=block.elapsed,
            finished_at=block.finished_at,
            proc_id=block.proc_id,
            declined=block.declined,
        )
        text = Text()
        if show_divider:
            text.append(f"{EARLIER_DIVIDER}\n", style="dim")
        if selected:
            text.append("▌", style="#00D7AF")
        else:
            text.append(" ")
        text.append(f"{glyph} ", style="bold")
        if block.unseen:
            text.append("• ", style="bold #FFD700")
        text.append(block.line, style="bold")
        if header_right:
            text.append(f"  {header_right}", style="dim")
        text.append("\n")
        if block.lost_bytes:
            text.append("⋯ earlier output rotated\n", style="dim")
        if block.status == "submit_failed" and block.error:
            error = Text(f"│ {block.error}", style="red")
            text.append_text(error)
            text.append("\n")
            return text
        if block.expanded:
            body_lines, _capped = expanded_body_lines(block.tail_text)
            hidden_count = 0
        else:
            body_lines, hidden_count = collapsed_body_lines(block.tail_text)
        if hidden_count:
            text.append(f"⋯ {hidden_count} more lines · o expand\n", style="dim")
        if block.tail_text.strip():
            rendered = render_block_output(
                block.proc_id or block.block_id, len(block.tail_text), block.tail_text
            )
            for line in body_lines:
                text.append("│ ", style="dim")
            text.append_text(rendered)
            if not str(rendered).endswith("\n"):
                text.append("\n")
        if block.pruned:
            text.append("record pruned\n", style="dim")
        return text


class CommandLineTranscript(VerticalScroll):
    """Scrollable transcript of Command Line blocks."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cursors: dict[str, ProcLogCursor] = {}
        self._tail_task_registry = "_command_line_tail_tasks"

    def refresh_blocks(
        self, blocks: list[CommandLineBlock], *, selected_id: str | None = None
    ) -> None:
        """Reconcile widgets with session blocks, repainting each in place."""
        by_id = {block.block_id: block for block in blocks}
        first_restored = next(
            (index for index, block in enumerate(blocks) if block.restored),
            None,
        )
        for widget in list(self.query(_CommandLineBlockWidget)):
            if widget.block.block_id not in by_id:
                widget.remove()
        existing = {
            widget.block.block_id: widget
            for widget in self.query(_CommandLineBlockWidget)
        }
        for index, block in enumerate(blocks):
            selected = block.block_id == selected_id
            show_divider = first_restored is not None and index == first_restored
            existing_widget = existing.get(block.block_id)
            if existing_widget is None:
                self.mount(
                    _CommandLineBlockWidget(
                        block, selected=selected, show_divider=show_divider
                    )
                )
            else:
                existing_widget.set_state(selected=selected, show_divider=show_divider)
                existing_widget.repaint()
        for block_id in list(self._cursors):
            if block_id not in by_id:
                self._cursors.pop(block_id, None)

    def start_tail_task(self) -> None:
        """Poll visible running blocks in a pump-free task (cancelled at teardown)."""
        spawn_pump_free_task(
            self,
            self._tail_loop(),
            name="command-line-tail",
            registry_attr=self._tail_task_registry,
        )

    def stop_tail_task(self) -> None:
        """Cancel tail polling (panel teardown)."""
        registry = getattr(self, self._tail_task_registry, None)
        if not registry:
            return
        for task in list(registry):
            task.cancel()

    async def _tail_loop(self) -> None:
        while True:
            await asyncio.sleep(TAIL_POLL_SECONDS)
            self._poll_once()

    def _poll_once(self) -> None:
        try:
            widgets = list(self.query(_CommandLineBlockWidget))
        except Exception:  # noqa: BLE001 - teardown races degrade silently.
            return
        for widget in widgets:
            block = widget.block
            if not block.running or block.proc_id is None:
                continue
            cursor = self._cursors.get(block.block_id)
            if cursor is None:
                cursor = ProcLogCursor(proc_id=block.proc_id)
                self._cursors[block.block_id] = cursor
            try:
                read = cursor.read_new()
            except Exception:  # noqa: BLE001 - log reads never break the panel.
                continue
            if read.text:
                block.tail_text += read.text
                block.tail_loaded = True
            if read.lost_bytes:
                block.lost_bytes += read.lost_bytes
            widget._spinner_index += 1
            try:
                widget.repaint()
            except Exception:  # noqa: BLE001 - teardown races degrade silently.
                continue


__all__ = [
    "EARLIER_DIVIDER",
    "TAIL_POLL_SECONDS",
    "CommandLineTranscript",
]

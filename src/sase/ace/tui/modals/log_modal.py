"""Log panel modal — the visible half of the ``,L`` Log panel.

Opened from any tab via the leader ``,L`` chord, this modal surfaces the
canonical SASE logs (launch/fan-out failures, TUI diagnostics, agent runs, and
events) defined by the :mod:`sase.ace.tui.logs` registry. The left panel lists
the sources; the right panel shows the selected log's tail, severity-colorized
and (for JSONL sources) pretty-rendered.

This is presentation-only Textual state: *what* logs exist and *how* to read
them lives in the backend registry (``sase.ace.tui.logs.sources``); this file
only renders that contract.
"""

from __future__ import annotations

import re
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from ..logs import LogSource, log_sources
from .base import CopyModeForwardingMixin, OptionListNavigationMixin

# Palette shared with the other modals (HelpModal / AgentRunLogModal).
_CYAN = "#87D7FF"
_GOLD = "#FFD700"

# Tail size read per source. Bounded so the panel stays responsive even on
# multi-megabyte logs (the read itself is O(tail) via ``read_tail_seek``).
_MAX_TAIL_LINES = 500

# Leading-timestamp shapes for both log formats:
#   ``[2026-06-17 14:30:00 UTC] ...``  (launch_failures.log header)
#   ``2026-06-17 14:30:00,123 WARNING ...`` (tui.log)
_TIMESTAMP_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[^\]]*\]?")
# A trailing exception-summary line, e.g. ``RuntimeError: boom``.
_EXC_SUMMARY_RE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Interrupt|Warning):")
# Catch-all logging level tokens (uppercase, as emitted by ``logging``).
_ERROR_LEVEL_RE = re.compile(r"\b(ERROR|CRITICAL|FATAL)\b")
_WARNING_LEVEL_RE = re.compile(r"\bWARNING\b")


def _format_size(num_bytes: int) -> str:
    """Human-readable byte size (``1.2 KB``, ``3 B``, ...)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _format_mtime(source: LogSource) -> str | None:
    """Last-modified time of *source* as ``YYYY-MM-DD HH:MM`` (``None`` if absent)."""
    try:
        ts = source.path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _source_size(source: LogSource) -> int | None:
    try:
        return source.path.stat().st_size
    except OSError:
        return None


def _empty_message(source: LogSource) -> str:
    """Friendly empty-state copy for a missing/empty *source*."""
    if source.id == "launch_failures":
        return "No launch failures logged \U0001f389"
    return f"No {source.title.lower()} yet."


def _line_severity_style(line: str) -> str | None:
    """Return a Rich style for a whole log *line* by severity, or ``None``."""
    stripped = line.strip()
    if stripped.startswith("Traceback (most recent call last)") or stripped == (
        "traceback:"
    ):
        return "bold red"
    if stripped.startswith("error:") or _EXC_SUMMARY_RE.match(stripped):
        return "red"
    if _ERROR_LEVEL_RE.search(line):
        return "red"
    if _WARNING_LEVEL_RE.search(line):
        return _GOLD
    return None


def _styled_log_line(line: str) -> Text:
    """Render one raw log *line* as colorized Rich :class:`Text`."""
    stripped = line.strip()
    # Separator rules and stack frames are de-emphasised.
    if stripped and set(stripped) <= {"=", "-", "─"}:
        return Text(line, style="dim")
    if stripped.startswith('File "'):
        return Text(line, style="dim")

    severity = _line_severity_style(line)
    if severity is not None:
        return Text(line, style=severity)

    # No severity: highlight a leading timestamp (header / tui.log) in cyan.
    match = _TIMESTAMP_RE.match(line)
    if match:
        text = Text()
        text.append(match.group(0), style=_CYAN)
        text.append(line[match.end() :])
        return text
    return Text(line)


def _render_log_detail(source: LogSource, max_lines: int = _MAX_TAIL_LINES) -> Text:
    """Build the full colorized detail body (header + tail) for *source*.

    Module-level and pure so it can be unit-tested without a running app.
    """
    body = source.read_rendered_tail(max_lines)
    text = Text()

    # Header: path · last modified · shown line count.
    text.append(str(source.path), style=f"bold {_CYAN}")
    mtime = _format_mtime(source)
    if mtime is not None:
        text.append(f"  ·  {mtime}", style="dim")
    if body:
        shown = len(body.splitlines())
        text.append(f"  ·  {shown} lines", style="dim")
    text.append("\n")
    text.append("─" * 48 + "\n", style="dim")

    if not body:
        text.append(_empty_message(source), style="dim italic")
        return text

    for line in body.splitlines():
        text.append_text(_styled_log_line(line))
        text.append("\n")
    return text


class LogModal(OptionListNavigationMixin, CopyModeForwardingMixin, ModalScreen[None]):
    """Two-panel Log panel: source list (left) + colorized tail (right)."""

    _option_list_id = "log-source-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("left_square_bracket", "cycle_log_prev", "Prev Log"),
        ("right_square_bracket", "cycle_log_next", "Next Log"),
        ("ctrl+d", "scroll_detail_down", "Scroll Down"),
        ("ctrl+u", "scroll_detail_up", "Scroll Up"),
        ("r", "refresh_logs", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._sources: list[LogSource] = log_sources()
        # Last detail body rendered into the right panel (the colorized tail of
        # the highlighted source). Kept for cheap re-inspection / testing.
        self._last_detail_text: Text = Text()

    def compose(self) -> ComposeResult:
        with Container(id="log-modal-container"):
            yield Label("\U0001f4dc  Logs", id="log-modal-title")
            with Horizontal(id="log-modal-panels"):
                with Vertical(id="log-modal-list-panel"):
                    yield OptionList(
                        *self._create_options(),
                        id=self._option_list_id,
                    )
                with Vertical(id="log-modal-detail-panel"):
                    with VerticalScroll(id="log-modal-detail-scroll"):
                        yield Static("", id="log-modal-detail")
            yield Static(
                "j/k navigate · [ ] cycle logs · ctrl+d/u scroll · "
                "r refresh · esc close",
                id="log-modal-hints",
            )

    def _create_options(self) -> list[Option]:
        """Build the left-panel source rows (marker + title + size/mtime)."""
        options: list[Option] = []
        for idx, source in enumerate(self._sources):
            options.append(Option(self._source_label(source), id=f"log__{idx}"))
        return options

    def _source_label(self, source: LogSource) -> Text:
        """Two-line row: ``● Title`` then a dim metadata subtitle."""
        non_empty = source.exists()
        text = Text()
        if non_empty:
            text.append("● ", style="bold green")  # ●
            text.append(source.title, style=f"bold {_CYAN}")
        else:
            text.append("○ ", style="dim")  # ○
            text.append(source.title, style="dim")

        text.append("\n   ")
        if non_empty:
            size = _source_size(source)
            mtime = _format_mtime(source)
            meta_parts = [p for p in (_format_size(size) if size else None, mtime) if p]
            text.append(" · ".join(meta_parts) or source.description, style="dim")
        else:
            text.append("empty", style="dim italic")
        return text

    def on_mount(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        if self._sources:
            option_list.highlighted = 0
            self._update_detail(self._sources[0])

    def _source_for_option(self, opt_id: str | None) -> LogSource | None:
        if not opt_id or not opt_id.startswith("log__"):
            return None
        try:
            idx = int(opt_id.removeprefix("log__"))
        except ValueError:
            return None
        if 0 <= idx < len(self._sources):
            return self._sources[idx]
        return None

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option and event.option.id:
            source = self._source_for_option(str(event.option.id))
            if source is not None:
                self._update_detail(source)

    def _update_detail(self, source: LogSource) -> None:
        self._last_detail_text = _render_log_detail(source)
        try:
            detail = self.query_one("#log-modal-detail", Static)
        except Exception:
            return
        detail.update(self._last_detail_text)
        # Reset scroll to the top for the freshly selected source.
        try:
            scroll = self.query_one("#log-modal-detail-scroll", VerticalScroll)
            scroll.scroll_home(animate=False)
        except Exception:
            pass

    def _highlighted_source(self) -> LogSource | None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        idx = option_list.highlighted
        if idx is None:
            return None
        if 0 <= idx < len(self._sources):
            return self._sources[idx]
        return None

    def action_cycle_log_next(self) -> None:
        """Cycle to the next source, wrapping at the end."""
        self._cycle(1)

    def action_cycle_log_prev(self) -> None:
        """Cycle to the previous source, wrapping at the start."""
        self._cycle(-1)

    def _cycle(self, delta: int) -> None:
        if not self._sources:
            return
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted or 0
        option_list.highlighted = (current + delta) % len(self._sources)

    def action_refresh_logs(self) -> None:
        """Re-read the highlighted source (logs grow live) and rebuild rows."""
        current = self._highlighted_source()
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        highlighted = option_list.highlighted
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)
        if highlighted is not None and 0 <= highlighted < len(self._sources):
            option_list.highlighted = highlighted
        if current is not None:
            self._update_detail(current)

    def action_scroll_detail_down(self) -> None:
        scroll = self.query_one("#log-modal-detail-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_detail_up(self) -> None:
        scroll = self.query_one("#log-modal-detail-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

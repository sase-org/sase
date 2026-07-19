"""Logs pane for the SASE Admin Center."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.core.paths import sase_home
from sase.logs import TOAST_HISTORY_LIMIT, current_toast_session, read_recent_toasts

from ..actions.navigation.jump_hints import (
    JumpHintMatchOutcome,
    build_jump_hint_maps,
    match_jump_hint,
    normalize_jump_key,
)
from ..logs import LogSource, log_sources
from .base import CopyModeForwardingMixin
from .logs_pane_toasts import render_toast_detail_body

# Palette shared with the other log-style modals (HelpModal / AgentRunLogModal).
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


@dataclass(frozen=True)
class _LogPaneLoadResult:
    sources: list[LogSource]
    options: list[tuple[str, Text]]
    active_count: int
    selected_index: int
    detail: Text


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
    """Last-modified time of *source* as ``YYYY-MM-DD HH:MM UTC``."""
    try:
        ts = source.path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _source_size(source: LogSource) -> int | None:
    try:
        return source.path.stat().st_size
    except OSError:
        return None


def _display_path(path: Path) -> str:
    """Return a stable, user-facing path for a log file."""
    try:
        resolved_path = path.expanduser().resolve(strict=False)
        resolved_home = sase_home().expanduser().resolve(strict=False)
        rel = resolved_path.relative_to(resolved_home)
    except (OSError, RuntimeError, ValueError):
        return str(path)
    return str(Path("~/.sase") / rel)


def _empty_message(source: LogSource) -> str:
    """Friendly empty-state copy for a missing/empty *source*."""
    if source.id == "launch_failures":
        return "No launch failures logged."
    if source.id == "tui_toasts":
        return "No toasts yet — notifications shown in the TUI will appear here."
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
    """Build the full colorized detail body (header + tail) for *source*."""
    body = "" if source.render == "toasts" else source.read_rendered_tail(max_lines)
    body_text: Text | None = None
    toast_count: int | None = None
    if source.render == "toasts":
        records = read_recent_toasts(TOAST_HISTORY_LIMIT)
        toast_count = len(records)
        if records:
            body_text = render_toast_detail_body(
                records,
                current_toast_session().session_id,
            )
            body = body_text.plain
        else:
            body = ""
    text = Text()

    # Header: source title, path, last modified, and shown line count.
    text.append(source.title, style=f"bold {_GOLD}")
    text.append("\n")
    text.append(f"{source.description}\n", style="dim")
    text.append(_display_path(source.path), style=f"bold {_CYAN}")
    mtime = _format_mtime(source)
    if mtime is not None:
        text.append(f"  ·  {mtime}", style="dim")
    if body:
        if toast_count is not None:
            text.append(f"  ·  {toast_count} toasts", style="dim")
        else:
            shown = len(body.splitlines())
            text.append(f"  ·  {shown} lines", style="dim")
    text.append("\n")
    text.append("─" * 48 + "\n", style="dim")

    if not body:
        text.append(_empty_message(source), style="dim italic")
        return text

    if body_text is not None:
        text.append_text(body_text)
        return text

    for line in body.splitlines():
        text.append_text(_styled_log_line(line))
        text.append("\n")
    return text


def _source_label(source: LogSource) -> Text:
    """Two-line row: ``● Title`` then a dim metadata subtitle."""
    non_empty = source.exists()
    text = Text()
    if non_empty:
        text.append("● ", style="bold green")
        text.append(source.title, style=f"bold {_CYAN}")
    else:
        text.append("○ ", style="dim")
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


def _build_log_pane_load_result(selected_index: int) -> _LogPaneLoadResult:
    """Read source metadata and the selected detail body off the UI thread."""
    sources = log_sources()
    if sources:
        selected_index = max(0, min(selected_index, len(sources) - 1))
    else:
        selected_index = 0
    options = [
        (f"log__{idx}", _source_label(source)) for idx, source in enumerate(sources)
    ]
    active_count = sum(1 for source in sources if source.exists())
    detail = (
        _render_log_detail(sources[selected_index])
        if sources
        else Text("No log sources configured.", style="dim italic")
    )
    return _LogPaneLoadResult(
        sources=sources,
        options=options,
        active_count=active_count,
        selected_index=selected_index,
        detail=detail,
    )


class _LogSourceList(OptionList):
    """Source list that reserves vim top/bottom keys for the detail pane."""

    BINDINGS = [
        ("g", "scroll_detail_top", "Top"),
        ("G", "scroll_detail_bottom", "Bottom"),
        ("shift+g", "scroll_detail_bottom", "Bottom"),
        *OptionList.BINDINGS,
    ]

    async def handle_key(self, event: events.Key) -> bool:
        if self._handle_detail_scroll_key(event):
            return True
        return await super().handle_key(event)

    def on_key(self, event: events.Key) -> None:
        self._handle_detail_scroll_key(event)

    def _handle_detail_scroll_key(self, event: events.Key) -> bool:
        character = getattr(event, "character", None)
        if event.key in ("G", "shift+g") or character == "G":
            event.prevent_default()
            event.stop()
            pane = self._pane()
            if pane is not None:
                pane.action_scroll_to_bottom()
            return True
        if event.key == "g":
            event.prevent_default()
            event.stop()
            pane = self._pane()
            if pane is not None:
                pane.action_scroll_to_top()
            return True
        return False

    def action_scroll_detail_top(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_to_top()

    def action_scroll_detail_bottom(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_to_bottom()

    def _pane(self) -> LogsPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, LogsPane):
                return node
            node = getattr(node, "parent", None)
        return None


class LogsPane(CopyModeForwardingMixin, Vertical):
    """Two-panel Logs tab: source list (left) + colorized tail (right)."""

    can_focus = False

    _option_list_id = "log-source-list"
    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("ctrl+d", "scroll_detail_down", "Scroll Down"),
        ("ctrl+u", "scroll_detail_up", "Scroll Up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
        ("shift+g", "scroll_to_bottom", "Bottom"),
        ("r", "refresh", "Refresh"),
        ("apostrophe", "jump_to_entry", "Jump"),
    ]

    def __init__(self, *, auto_load: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._sources: list[LogSource] = log_sources()
        self._source_options: list[tuple[str, Text]] = []
        self._active_count = 0
        self._loading = auto_load
        self._worker: Worker[Any] | None = None
        self._worker_reset_scroll = False
        self._syncing_options = False
        self._selected_index = 0
        self._last_detail_text: Text = Text("Loading logs...", style="dim")
        self._log_jump_mode_active = False
        self._log_jump_pending_prefix = ""
        self._log_jump_hint_to_index: dict[str, int] = {}
        self._log_jump_index_to_hint: dict[int, str] = {}
        self._log_jump_back_stack: list[int] = []

    def compose(self) -> ComposeResult:
        yield Label(self._title_text(), id="logs-pane-title")
        with Horizontal(id="logs-panels"):
            with Vertical(id="logs-source-panel"):
                yield Label("Sources", classes="config-region-header")
                yield _LogSourceList(id=self._option_list_id)
            with Vertical(id="logs-detail-panel"):
                yield Label("Detail", classes="config-region-header")
                with VerticalScroll(id="log-detail-scroll"):
                    yield Static(self._last_detail_text, id="log-detail", markup=False)
        yield Static(self._hints(), id="logs-hints", markup=False)

    def on_mount(self) -> None:
        if self._loading:
            self._start_load(selected_index=0, reset_scroll=True)

    def focus_default(self) -> None:
        """Focus the source list (browse-first) when the Logs tab activates."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    def on_key(self, event: events.Key) -> None:
        """Forward copy-mode keys and keep detail scrolling pane-scoped."""
        CopyModeForwardingMixin.on_key(self, event)
        if getattr(event, "_stop_propagation", False):
            return
        if self._log_jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self._handle_log_jump_key(key):
                event.prevent_default()
                event.stop()
                return
        character = getattr(event, "character", None)
        if event.key == "apostrophe":
            event.prevent_default()
            event.stop()
            self.action_jump_to_entry()
        elif event.key in ("G", "shift+g") or character == "G":
            event.prevent_default()
            event.stop()
            self.action_scroll_to_bottom()
        elif event.key == "g":
            event.prevent_default()
            event.stop()
            self.action_scroll_to_top()

    def _start_load(self, *, selected_index: int, reset_scroll: bool) -> None:
        self._loading = True
        self._worker_reset_scroll = reset_scroll
        self._update_static("#logs-pane-title", self._title_text())

        def task() -> _LogPaneLoadResult:
            return _build_log_pane_load_result(selected_index)

        self._worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            self._loading = False
            result = event.worker.result
            if not isinstance(result, _LogPaneLoadResult):
                self._last_detail_text = Text(
                    "Failed to load logs: no result", style="red"
                )
                self._update_static("#log-detail", self._last_detail_text)
                self._update_static("#logs-pane-title", self._title_text())
                return
            self._apply_load_result(result, reset_scroll=self._worker_reset_scroll)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            message = str(event.worker.error) if event.worker.error else "load failed"
            self._last_detail_text = Text(
                f"Failed to load logs: {message}", style="red"
            )
            self._update_static("#log-detail", self._last_detail_text)
            self._update_static("#logs-pane-title", self._title_text())

    def _apply_load_result(
        self, result: _LogPaneLoadResult, *, reset_scroll: bool
    ) -> None:
        previous_source_ids = [source.id for source in self._sources]
        next_source_ids = [source.id for source in result.sources]
        if previous_source_ids != next_source_ids:
            self._clear_log_jump_hints()
            self._log_jump_back_stack = []
        elif self._log_jump_mode_active and not self._log_jump_hints_are_valid(
            len(result.sources)
        ):
            self._clear_log_jump_hints()

        self._sources = result.sources
        self._source_options = result.options
        self._active_count = result.active_count
        self._selected_index = result.selected_index
        self._last_detail_text = result.detail
        self._update_static("#logs-pane-title", self._title_text())
        self._update_static("#log-detail", self._last_detail_text)
        self._update_hints()
        self._rebuild_options(selected_index=result.selected_index)
        if reset_scroll:
            self._scroll_detail_home()

    def _log_jump_hints_are_valid(self, source_count: int) -> bool:
        return all(
            0 <= index < source_count for index in self._log_jump_hint_to_index.values()
        )

    def _render_source_option_label(self, source_index: int, label: Text) -> Text:
        hint = self._log_jump_index_to_hint.get(source_index)
        if not self._log_jump_mode_active or hint is None:
            return label.copy()

        text = Text()
        text.append(f"[{hint}] ", style=f"bold {_GOLD}")
        text.append_text(label.copy())
        return text

    def _render_source_options(self) -> list[Option]:
        return [
            Option(self._render_source_option_label(idx, label), id=option_id)
            for idx, (option_id, label) in enumerate(self._source_options)
        ]

    def _rebuild_options(self, *, selected_index: int | None = None) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        if selected_index is None:
            selected_index = self._highlighted_index()
        if self._source_options:
            selected_index = max(0, min(selected_index, len(self._source_options) - 1))
        self._syncing_options = True
        try:
            option_list.clear_options()
            option_list.add_options(self._render_source_options())
            if self._source_options:
                option_list.highlighted = selected_index
            if self._is_active_tab():
                option_list.focus()
        finally:
            self._syncing_options = False

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one(f"#{self._option_list_id}", OptionList)
        except Exception:
            return None

    def _source_index_for_option(self, opt_id: str | None) -> int | None:
        if not opt_id or not opt_id.startswith("log__"):
            return None
        try:
            idx = int(opt_id.removeprefix("log__"))
        except ValueError:
            return None
        if 0 <= idx < len(self._sources):
            return idx
        return None

    def _highlighted_index(self) -> int:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return 0
        return max(0, min(option_list.highlighted, max(0, len(self._sources) - 1)))

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._syncing_options:
            return
        if event.option and event.option.id:
            idx = self._source_index_for_option(str(event.option.id))
            if idx is not None:
                if idx == self._selected_index:
                    return
                self._start_load(selected_index=idx, reset_scroll=True)

    def action_next_option(self) -> None:
        """Move to next log source."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.action_cursor_down()

    def action_prev_option(self) -> None:
        """Move to previous log source."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.action_cursor_up()

    def action_refresh(self) -> None:
        """Re-read the highlighted source and rebuild source rows."""
        self._start_load(selected_index=self._highlighted_index(), reset_scroll=True)

    def action_jump_to_entry(self) -> None:
        """Enter adaptive jump mode for log source rows."""
        indices = list(range(len(self._source_options)))
        if not indices:
            return
        self._log_jump_hint_to_index, self._log_jump_index_to_hint = (
            build_jump_hint_maps(indices)
        )
        if not self._log_jump_hint_to_index:
            return

        self._log_jump_pending_prefix = ""
        self._log_jump_mode_active = True
        self._rebuild_options(selected_index=self._highlighted_index())
        self._update_hints()

    def _clear_log_jump_hints(self) -> None:
        self._log_jump_mode_active = False
        self._log_jump_pending_prefix = ""
        self._log_jump_hint_to_index = {}
        self._log_jump_index_to_hint = {}

    def _exit_log_jump_mode(self) -> None:
        selected_index = self._highlighted_index()
        self._clear_log_jump_hints()
        self._rebuild_options(selected_index=selected_index)
        self._update_hints()

    def _handle_log_jump_key(self, key: str) -> bool:
        if not self._log_jump_mode_active:
            return False
        if key == "escape":
            self._exit_log_jump_mode()
            return True

        push_current = True
        if key == "apostrophe":
            while self._log_jump_back_stack:
                target_index = self._log_jump_back_stack.pop()
                if 0 <= target_index < len(self._source_options):
                    return self._jump_to_source_index(
                        target_index,
                        push_current=False,
                    )
            hint_target_index = next(
                iter(self._log_jump_hint_to_index.values()),
                None,
            )
        else:
            match = match_jump_hint(
                self._log_jump_hint_to_index,
                self._log_jump_pending_prefix,
                key,
            )
            if match.outcome is JumpHintMatchOutcome.PENDING:
                self._log_jump_pending_prefix = match.prefix
                return True
            if match.outcome is JumpHintMatchOutcome.INVALID:
                self._exit_log_jump_mode()
                return True
            hint_target_index = match.target
            self._log_jump_pending_prefix = ""

        if hint_target_index is None:
            self._exit_log_jump_mode()
            return True
        return self._jump_to_source_index(hint_target_index, push_current=push_current)

    def _jump_to_source_index(self, target_index: int, *, push_current: bool) -> bool:
        if not 0 <= target_index < len(self._source_options):
            self._exit_log_jump_mode()
            return True

        current_index = self._highlighted_index()
        if push_current and current_index != target_index:
            self._log_jump_back_stack.append(current_index)
            del self._log_jump_back_stack[:-10]

        self._clear_log_jump_hints()
        self._rebuild_options(selected_index=target_index)
        self._update_hints()
        if current_index != target_index:
            self._start_load(selected_index=target_index, reset_scroll=True)
        return True

    def action_scroll_detail_down(self) -> None:
        scroll = self.query_one("#log-detail-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        self._force_scroll_detail_to(scroll.scroll_y + height // 2)

    def action_scroll_detail_up(self) -> None:
        scroll = self.query_one("#log-detail-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        self._force_scroll_detail_to(scroll.scroll_y - height // 2)

    def action_scroll_to_top(self) -> None:
        """Scroll the detail pane to the very top (highlight unchanged)."""
        self._scroll_detail_home()

    def action_scroll_to_bottom(self) -> None:
        """Scroll the detail pane to the very bottom (highlight unchanged)."""
        scroll = self.query_one("#log-detail-scroll", VerticalScroll)
        self._force_scroll_detail_to(scroll.max_scroll_y)

    def _scroll_detail_home(self) -> None:
        try:
            self._force_scroll_detail_to(0)
        except Exception:
            pass

    def _force_scroll_detail_to(self, y: float) -> None:
        scroll = self.query_one("#log-detail-scroll", VerticalScroll)
        target = max(0, min(int(y), int(scroll.max_scroll_y)))
        scroll._scroll_to(y=target, animate=False, force=True)  # noqa: SLF001

    def _update_static(self, selector: str, content: Text | str) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass

    def _update_hints(self) -> None:
        self._update_static("#logs-hints", self._hints())

    def _title_text(self) -> str:
        if self._loading:
            return f"Logs  [{len(self._sources)} sources · loading]"
        return f"Logs  [{len(self._sources)} sources · {self._active_count} active]"

    def _hints(self) -> str:
        if self._log_jump_mode_active:
            action = "back" if self._log_jump_back_stack else "first"
            return f"JUMP ' {action}  <esc> cancel"
        return (
            "j/k: move   ctrl+d/u: scroll   g/G: top/bottom   "
            "': jump   r: refresh   Tab/Shift+Tab: tab   Esc: close"
        )


__all__ = [
    "LogsPane",
    "_CYAN",
    "_GOLD",
    "_build_log_pane_load_result",
    "_format_mtime",
    "_format_size",
    "_render_log_detail",
    "_styled_log_line",
]

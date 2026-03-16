"""Activity Dashboard modal for the ace TUI.

Shows session info, current activity state, summary statistics,
and a chronological timeline of idle/active transitions.
"""

from __future__ import annotations

import time
from datetime import datetime
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ..activity_log import ActivityEventType, ActivityLog

# ── Box drawing constants ──────────────────────────────────────────
_CONTENT_WIDTH = 50

# ── Event display metadata ─────────────────────────────────────────
_EVENT_STYLES: dict[ActivityEventType, tuple[str, str, str]] = {
    # event → (icon, label, style)
    ActivityEventType.SESSION_START: ("▶", "Session started", "bold #87D7FF"),
    ActivityEventType.ACTIVE: ("●", "Active", "bold #00D7AF"),
    ActivityEventType.IDLE_AUTO: ("○", "Idle (auto)", "#FFD700"),
    ActivityEventType.IDLE_MANUAL: ("◆", "Idle (manual)", "#FF8C00"),
    ActivityEventType.IDLE_PINNED: ("◉", "Idle (pinned)", "bold #FF5F5F"),
    ActivityEventType.IDLE_RESTORED: ("◈", "Idle (restored)", "#FF5F5F"),
}


def _fmt_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 0:
        return "—"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    secs = total % 60
    if minutes < 60:
        return f"{minutes}m {secs:02d}s" if secs else f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    if secs:
        return f"{hours}h {mins:02d}m {secs:02d}s"
    if mins:
        return f"{hours}h {mins:02d}m"
    return f"{hours}h"


def _fmt_time(epoch: float) -> str:
    """Format an epoch timestamp as HH:MM:SS."""
    return datetime.fromtimestamp(epoch).strftime("%H:%M:%S")


class ActivityModal(ModalScreen[None]):
    """Activity Dashboard showing session info and timeline."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("i", "close", "Close"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, activity_log: ActivityLog, inactive_seconds: int) -> None:
        super().__init__()
        self._activity_log = activity_log
        self._inactive_seconds = inactive_seconds

    def compose(self) -> ComposeResult:
        with Container(id="activity-modal-container"):
            yield Static(self._build_title(), id="activity-title")
            with VerticalScroll(id="activity-content-scroll"):
                yield Static(self._build_content(), id="activity-content")
            yield Static(
                "Press i / q / Esc to close  |  Ctrl+D/U to scroll",
                id="activity-footer",
            )

    def _build_title(self) -> Text:
        text = Text()
        text.append("\n")
        text.append("  ", style="")
        text.append("\u2726 ", style="bold #FFD700")
        text.append("Activity Dashboard", style="bold white")
        text.append(" \u2726", style="bold #FFD700")
        text.append("\n")

        # Uptime line
        start = self._activity_log.session_start_mono
        if start is not None:
            uptime = time.monotonic() - start
            text.append(f"  Session uptime: {_fmt_duration(uptime)}", style="#87D7FF")
        return text

    def _build_content(self) -> Text:
        text = Text()
        self._add_current_state(text)
        self._add_session_summary(text)
        self._add_timeline(text)
        return text

    # ── Sections ───────────────────────────────────────────────────

    def _add_current_state(self, text: Text) -> None:
        """Add the Current State section."""
        current = self._activity_log.current_state()
        if current is None:
            return

        bindings: list[tuple[str, str]] = []
        icon, label, style = _EVENT_STYLES[current.event]

        # State line
        since = _fmt_time(current.timestamp)
        duration = _fmt_duration(time.monotonic() - current.mono)
        bindings.append((f"{icon}  {label}", f"for {duration} (since {since})"))

        # Last keypress
        try:
            from sase.ace.tui_activity import get_last_keypress

            lkp = get_last_keypress()
            if lkp is not None and lkp > 0:
                ago = _fmt_duration(time.time() - lkp)
                bindings.append(("   Last keypress", f"{ago} ago"))
        except Exception:
            pass

        # Idle threshold
        bindings.append(("   Idle threshold", _fmt_duration(self._inactive_seconds)))

        self._add_section(text, "Current State", bindings, style_override=style)

    def _add_session_summary(self, text: Text) -> None:
        """Add the Session Summary section."""
        log = self._activity_log
        start_ts = log.session_start_time
        if start_ts is None:
            return

        active_secs, idle_secs, idle_episodes = log.compute_totals()
        total = active_secs + idle_secs

        # Build percentage bars
        active_pct = (active_secs / total * 100) if total > 0 else 100
        idle_pct = (idle_secs / total * 100) if total > 0 else 0

        bindings: list[tuple[str, str]] = [
            ("Started", _fmt_time(start_ts)),
            ("Active time", f"{_fmt_duration(active_secs)}  ({active_pct:.0f}%)"),
            ("Idle time", f"{_fmt_duration(idle_secs)}  ({idle_pct:.0f}%)"),
            ("Idle episodes", str(idle_episodes)),
        ]

        # Activity bar visualization
        bar_width = 36
        active_bar = int(bar_width * active_pct / 100)
        idle_bar = bar_width - active_bar
        bindings.append(("", ""))  # spacer
        bindings.append(("", f"{'█' * active_bar}{'░' * idle_bar}"))

        self._add_section(text, "Session Summary", bindings)

    def _add_timeline(self, text: Text) -> None:
        """Add the Activity Timeline section (reverse chronological)."""
        entries = self._activity_log.entries
        if not entries:
            return

        now_mono = time.monotonic()

        # Section header
        text.append("\n")
        text.append("  \u250c\u2500 ", style="dim #87D7FF")
        text.append("Activity Timeline", style="bold #87D7FF")
        text.append(" ", style="")
        remaining = _CONTENT_WIDTH - len("Activity Timeline")
        text.append("\u2500" * remaining + "\u2510", style="dim #87D7FF")
        text.append("\n")

        # Reverse chronological - newest first
        for i in range(len(entries) - 1, -1, -1):
            entry = entries[i]
            icon, label, style = _EVENT_STYLES[entry.event]

            # Duration in this state
            if i + 1 < len(entries):
                duration = entries[i + 1].mono - entry.mono
            else:
                duration = now_mono - entry.mono

            ts = _fmt_time(entry.timestamp)

            text.append("  \u2502  ", style="dim #87D7FF")
            text.append(f"{ts}  ", style="dim white")
            text.append(f"{icon} ", style=style)
            text.append(f"{label:<15}", style=style)
            text.append(f"({_fmt_duration(duration)})", style="dim")

            # Pad to right border
            line_len = len(ts) + 2 + 2 + 15 + len(f"({_fmt_duration(duration)})")
            padding = _CONTENT_WIDTH - line_len
            if padding > 0:
                text.append(" " * padding, style="")
            text.append(" \u2502", style="dim #87D7FF")
            text.append("\n")

        # Section footer
        text.append("  \u2514", style="dim #87D7FF")
        text.append("\u2500" * 53, style="dim #87D7FF")
        text.append("\u2518", style="dim #87D7FF")
        text.append("\n")

    # ── Helpers ────────────────────────────────────────────────────

    def _add_section(
        self,
        text: Text,
        section_name: str,
        bindings: list[tuple[str, str]],
        *,
        style_override: str | None = None,
    ) -> None:
        """Add a key-value section with box drawing."""
        # Section header
        text.append("\n")
        text.append("  \u250c\u2500 ", style="dim #87D7FF")
        text.append(section_name, style="bold #87D7FF")
        text.append(" ", style="")
        remaining = _CONTENT_WIDTH - len(section_name)
        text.append("\u2500" * remaining + "\u2510", style="dim #87D7FF")
        text.append("\n")

        key_width = 20
        for key, value in bindings:
            if not key and not value:
                # Spacer - empty line within the box
                text.append("  \u2502", style="dim #87D7FF")
                text.append(" " * (_CONTENT_WIDTH + 3), style="")
                text.append("\u2502", style="dim #87D7FF")
                text.append("\n")
                continue

            text.append("  \u2502  ", style="dim #87D7FF")

            if not key:
                # Value-only line (e.g., the activity bar)
                val_style = style_override or ""
                text.append(f"{value}", style=val_style)
                padding = _CONTENT_WIDTH - len(value)
                if padding > 0:
                    text.append(" " * padding, style="")
            else:
                # Key-value line
                key_style = style_override or "bold #00D7AF"
                text.append(f"{key:<{key_width}}", style=key_style)
                max_val = _CONTENT_WIDTH - key_width - 2
                display_val = value[:max_val] if len(value) > max_val else value
                text.append(display_val, style="")
                padding = _CONTENT_WIDTH - key_width - len(display_val)
                if padding > 0:
                    text.append(" " * padding, style="")

            text.append(" \u2502", style="dim #87D7FF")
            text.append("\n")

        # Section footer
        text.append("  \u2514", style="dim #87D7FF")
        text.append("\u2500" * 53, style="dim #87D7FF")
        text.append("\u2518", style="dim #87D7FF")
        text.append("\n")

    # ── Actions ────────────────────────────────────────────────────

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#activity-content-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#activity-content-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

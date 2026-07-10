"""Status and startup-stopwatch helpers for :class:`KeybindingFooter`."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.timer import Timer


_AXE_LABEL_TEXT = " AXE "
_AXE_LABEL_STYLE = "bold white on rgb(68,71,90)"
_STARTUP_STOPWATCH_TIMEOUT_SECS = 30.0
_STOPWATCH_GLYPH_FRAMES = ("◴", "◷", "◶", "◵")
_STOPWATCH_TIER_YELLOW_SECS = 3.0
_STOPWATCH_TIER_ORANGE_SECS = 5.0
_STOPWATCH_TIER_RED_SECS = 8.0
_STOPWATCH_TIER_FLASH_SECS = 13.0
_STOPWATCH_FLASH_PERIOD_TICKS = 5
_STOPWATCH_BG_NORMAL = "rgb(155,89,182)"
_STOPWATCH_BG_YELLOW = "rgb(250,204,21)"
_STOPWATCH_BG_ORANGE = "rgb(249,115,22)"
_STOPWATCH_BG_RED = "rgb(220,38,38)"
_STOPWATCH_BG_FLASH_ON = "rgb(255,40,40)"
_STOPWATCH_BG_FLASH_OFF = "rgb(120,0,0)"
_STOPWATCH_FG_LIGHT = "white"
_STOPWATCH_FG_DARK = "black"


def _stopwatch_palette(elapsed: float, frame: int) -> tuple[str, str, bool]:
    """Return ``(background, foreground, emphasized)`` for a startup badge."""
    if elapsed >= _STOPWATCH_TIER_FLASH_SECS:
        flash_on = (frame // _STOPWATCH_FLASH_PERIOD_TICKS) % 2 == 0
        bg = _STOPWATCH_BG_FLASH_ON if flash_on else _STOPWATCH_BG_FLASH_OFF
        return bg, _STOPWATCH_FG_LIGHT, True
    if elapsed >= _STOPWATCH_TIER_RED_SECS:
        return _STOPWATCH_BG_RED, _STOPWATCH_FG_LIGHT, False
    if elapsed >= _STOPWATCH_TIER_ORANGE_SECS:
        return _STOPWATCH_BG_ORANGE, _STOPWATCH_FG_DARK, False
    if elapsed >= _STOPWATCH_TIER_YELLOW_SECS:
        return _STOPWATCH_BG_YELLOW, _STOPWATCH_FG_DARK, False
    return _STOPWATCH_BG_NORMAL, _STOPWATCH_FG_LIGHT, False


class KeybindingStatusMixin:
    """AXE status-pill and startup-stopwatch rendering logic."""

    if TYPE_CHECKING:
        _axe_running: bool
        _axe_starting: bool
        _axe_stopping: bool
        _axe_restarting: bool
        _bgcmd_running_count: int
        _bgcmd_done_count: int
        _startup_stopwatch_active: bool
        _startup_start_time: float
        _startup_elapsed: float
        _startup_stopwatch_timer: Timer | None
        _stopwatch_frame: int
        _last_status_signature: tuple[Any, ...] | None

        def _resolve_status_widget(self) -> Static | None: ...

    def _on_stopwatch_tick(self) -> None:
        """Recompute elapsed time, refresh the status, and enforce the safety timeout."""
        if not self._startup_stopwatch_active:
            return
        self._startup_elapsed = time.monotonic() - self._startup_start_time
        self._stopwatch_frame += 1
        if self._startup_elapsed >= _STARTUP_STOPWATCH_TIMEOUT_SECS:
            self.end_startup_stopwatch()
            return
        self._update_status()

    def end_startup_stopwatch(self) -> None:
        """Stop the startup stopwatch and re-render the real AXE status.

        Idempotent — safe to call from both the real-end signal and the
        safety timeout even if they race.
        """
        if not self._startup_stopwatch_active:
            return
        self._startup_stopwatch_active = False
        if self._startup_stopwatch_timer is not None:
            self._startup_stopwatch_timer.stop()
            self._startup_stopwatch_timer = None
        self._update_status()

    def set_axe_running(self, running: bool) -> None:
        """Update the axe running state for binding labels.

        Args:
            running: Whether axe daemon is currently running.
        """
        self._axe_running = running
        self._update_status()

    def set_axe_starting(self, starting: bool) -> None:
        """Update the axe starting state.

        Args:
            starting: Whether axe daemon is currently starting.
        """
        self._axe_starting = starting
        self._update_status()

    def set_axe_stopping(self, stopping: bool) -> None:
        """Update the axe stopping state.

        Args:
            stopping: Whether axe daemon is currently stopping.
        """
        self._axe_stopping = stopping
        self._update_status()

    def set_axe_restarting(self, restarting: bool) -> None:
        """Update the axe restarting state.

        Args:
            restarting: Whether axe daemon is currently restarting.
        """
        self._axe_restarting = restarting
        self._update_status()

    def set_bgcmd_count(self, running_count: int, done_count: int) -> None:
        """Update the background command counts.

        Args:
            running_count: Number of running background commands.
            done_count: Number of done (completed) background commands.
        """
        self._bgcmd_running_count = running_count
        self._bgcmd_done_count = done_count
        self._update_status()

    def _status_signature(self) -> tuple[Any, ...]:
        """Compact signature of every input that drives status rendering."""
        if self._startup_stopwatch_active:
            bg, _, _ = _stopwatch_palette(self._startup_elapsed, self._stopwatch_frame)
            return (
                "startup",
                round(self._startup_elapsed, 1),
                self._stopwatch_frame % len(_STOPWATCH_GLYPH_FRAMES),
                bg,
            )
        return (
            "axe",
            self._axe_restarting,
            self._axe_starting,
            self._axe_stopping,
            self._axe_running,
            self._bgcmd_running_count,
            self._bgcmd_done_count,
        )

    def _update_status(self) -> None:
        """Update the status indicator widget if its signature changed."""
        signature = self._status_signature()
        if signature == self._last_status_signature:
            return
        widget = self._resolve_status_widget()
        if widget is None:
            return
        widget.update(self._get_status_text())
        self._last_status_signature = signature

    def _get_status_text(self) -> Text:
        """Get styled status indicator text.

        Returns:
            Formatted Text object for the status indicator.
        """
        text = Text()
        text.append(_AXE_LABEL_TEXT, style=_AXE_LABEL_STYLE)
        if self._startup_stopwatch_active:
            bg, fg, emphasized = _stopwatch_palette(
                self._startup_elapsed, self._stopwatch_frame
            )
            glyph = _STOPWATCH_GLYPH_FRAMES[
                self._stopwatch_frame % len(_STOPWATCH_GLYPH_FRAMES)
            ]
            label_weight = "bold " if emphasized else ""
            text.append(f"  {glyph} ", style=f"bold {fg} on {bg}")
            text.append("starting ", style=f"{label_weight}{fg} on {bg}")
            text.append(
                f"{self._startup_elapsed:.1f}s  ",
                style=f"bold {fg} on {bg}",
            )
        elif self._axe_restarting:
            text.append(" RESTARTING ", style="bold black on rgb(0,191,255)")
        elif self._axe_starting:
            text.append(" STARTING ", style="bold black on rgb(255,255,0)")
        elif self._axe_stopping:
            text.append(" STOPPING ", style="bold black on rgb(255,165,0)")
        elif self._axe_running:
            text.append(" RUNNING ", style="bold black on green")
        else:
            text.append(" STOPPED ", style="bold white on red")

        # Add bgcmd badges if there are any background commands.
        if self._bgcmd_running_count > 0 or self._bgcmd_done_count > 0:
            text.append(" ")
            if self._bgcmd_running_count > 0:
                text.append(
                    f" [*{self._bgcmd_running_count}] ", style="bold black on #00D7AF"
                )
            if self._bgcmd_done_count > 0:
                text.append(
                    f" [✓{self._bgcmd_done_count}] ", style="bold black on #FFD700"
                )

        return text

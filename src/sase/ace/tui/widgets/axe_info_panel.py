"""Axe info panel widget for the ace TUI."""

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from ..keymaps import KeymapRegistry, leader_key_display, load_keymap_registry

if TYPE_CHECKING:
    from ..bgcmd import BackgroundCommandInfo


class AxeInfoPanel(Static):
    """Top bar showing axe running status and auto-refresh countdown."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the info panel."""
        super().__init__(**kwargs)
        self._is_running = False
        self._countdown = 0
        self._interval = 0
        self._bgcmd_mode = False
        self._bgcmd_slot: int | None = None
        self._bgcmd_info: BackgroundCommandInfo | None = None
        self._bgcmd_running = False
        self._lumberjack_mode = False
        self._lumberjack_name: str = ""
        self._lumberjack_idx: int = 0
        self._lumberjack_total: int = 0
        self._chop_mode = False
        self._chop_lumberjack_name: str = ""
        self._chop_name: str = ""
        self._chop_run_idx: int = 0
        self._chop_run_total: int = 0
        self._loading: bool = False
        self._registry: KeymapRegistry = load_keymap_registry({})

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active keymap registry and refresh the guide hint."""
        self._registry = registry
        self._update_display()

    def set_loading(self, loading: bool) -> None:
        """Show or hide the startup-loading ellipsis.

        While True, the panel renders ``AXE …`` (dim italic) instead of
        a ``not running`` / status claim that may be wrong during the
        first-load window.
        """
        if self._loading != loading:
            self._loading = loading
            self._update_display()

    def update_status(self, is_running: bool) -> None:
        """Update the running status display for axe daemon.

        Args:
            is_running: Whether axe daemon is currently running.
        """
        self._is_running = is_running
        self._bgcmd_mode = False
        self._lumberjack_mode = False
        self._chop_mode = False
        self._update_display()

    def update_lumberjack_status(self, name: str, idx: int, total: int) -> None:
        """Update the status display for a lumberjack view.

        Args:
            name: Lumberjack name.
            idx: Current index (0-based).
            total: Total number of lumberjacks.
        """
        self._bgcmd_mode = False
        self._lumberjack_mode = True
        self._chop_mode = False
        self._lumberjack_name = name
        self._lumberjack_idx = idx
        self._lumberjack_total = total
        self._update_display()

    def update_chop_status(
        self,
        lumberjack_name: str,
        chop_name: str,
        run_idx: int,
        run_total: int,
    ) -> None:
        """Update the top-bar copy for a chop-run-detail view.

        Args:
            lumberjack_name: Parent lumberjack name.
            chop_name: Chop name.
            run_idx: 0-based displayed run index.
            run_total: Total runs in cached history.
        """
        self._bgcmd_mode = False
        self._lumberjack_mode = False
        self._chop_mode = True
        self._chop_lumberjack_name = lumberjack_name
        self._chop_name = chop_name
        self._chop_run_idx = run_idx
        self._chop_run_total = run_total
        self._update_display()

    def update_bgcmd_status(
        self,
        slot: int,
        info: "BackgroundCommandInfo | None",
        is_running: bool,
    ) -> None:
        """Update the status display for a background command.

        Args:
            slot: Slot number (1-9).
            info: Background command info.
            is_running: Whether the command is still running.
        """
        self._bgcmd_mode = True
        self._lumberjack_mode = False
        self._chop_mode = False
        self._bgcmd_slot = slot
        self._bgcmd_info = info
        self._bgcmd_running = is_running
        self._update_display()

    def update_countdown(self, countdown: int, interval: int) -> None:
        """Update the countdown display.

        Args:
            countdown: Seconds remaining until auto-refresh.
            interval: Total refresh interval in seconds.
        """
        self._countdown = countdown
        self._interval = interval
        self._update_display()

    def _update_display(self) -> None:
        """Refresh the displayed text."""
        text = Text()

        if self._loading:
            text.append("AXE ", style="bold")
            text.append("…", style="dim italic")
            self._append_help_guide_hint(text)
            self.update(text)
            return

        if self._chop_mode:
            text.append(
                f"[{self._chop_lumberjack_name} / {self._chop_name}]",
                style="bold #FFD700",
            )
            if self._chop_run_total > 0:
                text.append(
                    f" Run {self._chop_run_idx + 1}/{self._chop_run_total}",
                    style="dim",
                )
            else:
                text.append(" (no runs)", style="dim italic")
            text.append("  ", style="")
        elif self._lumberjack_mode:
            # Show lumberjack name with index
            text.append(f"[{self._lumberjack_name}]", style="bold #FFD700")
            text.append(
                f" ({self._lumberjack_idx + 1}/{self._lumberjack_total})",
                style="dim",
            )
            text.append("  ", style="")
        elif self._bgcmd_mode:
            # Show bgcmd info (just project name)
            if self._bgcmd_info:
                text.append(self._bgcmd_info.display_project, style="#87D7FF")
            text.append("  ", style="")
        else:
            # Show axe info (just the countdown for now)
            pass

        if self._interval > 0:
            text.append("(auto-refresh in ", style="dim")
            text.append(f"{self._countdown}s", style="bold #FFD700")
            text.append(")", style="dim")

        self._append_help_guide_hint(text)
        self.update(text)

    def _append_help_guide_hint(self, text: Text) -> None:
        """Append the persistent Help Guide hint."""
        if text.plain:
            text.append("  ", style="")
        text.append(
            f" {leader_key_display(self._registry, 'show_help')} ",
            style="bold #1a1a1a on #00D7AF",
        )
        text.append(" ] ", style="bold #1a1a1a on #00D7AF")
        text.append(" tab guide", style="dim")

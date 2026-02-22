"""Axe display and state management mixin for the ace TUI app."""

from __future__ import annotations

import types
from typing import Literal

from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    read_lumberjack_log_tail,
    read_lumberjack_status,
    read_metrics,
    read_output_log_tail,
)

from ..bgcmd import (
    BackgroundCommandInfo,
    get_active_slots,
    get_slot_info,
    is_slot_running,
    mark_slot_finished,
    read_slot_output_tail,
)

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int


def get_axe_process_module() -> types.ModuleType:
    """Return the axe process module."""
    import importlib

    return importlib.import_module("sase.axe.process")


class AxeDisplayMixin:
    """Mixin providing axe display refresh and state loading."""

    # Type hints for attributes accessed from AceApp
    current_tab: TabName
    refresh_interval: int
    axe_running: bool
    _countdown_remaining: int
    _axe_status: AxeStatus | None
    _axe_metrics: AxeMetrics | None
    _axe_output: str
    _axe_pinned_to_bottom: bool
    _axe_current_view: AxeViewType
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    _axe_lumberjack_names: list[str]
    _axe_lumberjack_idx: int | None
    _bang_mode_active: bool

    def _load_axe_status(self) -> None:
        """Load axe status from disk and update display."""
        proc = get_axe_process_module()

        # Check if axe is running
        self.axe_running = proc.is_axe_running()

        # Clear starting state once confirmed running
        if self.axe_running:
            self._set_axe_starting(False)

        # Clear stopping state once confirmed stopped
        if not self.axe_running:
            self._set_axe_stopping(False)

        # Load status data
        if self.axe_running:
            status_dict = proc.get_axe_status()
            if status_dict:
                try:
                    self._axe_status = AxeStatus(**status_dict)
                except TypeError:
                    self._axe_status = None
            else:
                self._axe_status = None
            self._axe_metrics = read_metrics()
        else:
            self._axe_status = None
            self._axe_metrics = None

        # Load output log (always, for display even when stopped)
        self._axe_output = read_output_log_tail(500)

        # Load lumberjack names from config (new architecture only)
        self._load_lumberjack_names()

        # Also load bgcmd state
        self._load_bgcmd_state()

        # Update display if on axe tab
        if self.current_tab == "axe":
            self._refresh_axe_display()

        # Update keybinding footer for all tabs (X binding changes label)
        self._update_axe_keybinding()

    def _load_lumberjack_names(self) -> None:
        """Load lumberjack names from axe config."""
        from sase.axe.config import load_axe_config as load_new_axe_config

        config = load_new_axe_config()
        self._axe_lumberjack_names = sorted(config.lumberjacks.keys())

        # Reset index if it's now out of bounds
        if self._axe_lumberjack_idx is not None and self._axe_lumberjack_idx >= len(
            self._axe_lumberjack_names
        ):
            self._axe_lumberjack_idx = None

        # Default to first lumberjack when lumberjacks exist (skip main view)
        if self._axe_lumberjack_idx is None and self._axe_lumberjack_names:
            self._axe_lumberjack_idx = 0

    def _load_bgcmd_state(self) -> None:
        """Load background command state from disk (running + done commands)."""
        active_slots = get_active_slots()
        self._bgcmd_slots = []

        for slot in active_slots:
            info = get_slot_info(slot)
            if info is not None:
                # Check if command just finished and mark it
                if not is_slot_running(slot) and info.finished_at is None:
                    mark_slot_finished(slot)
                    info = get_slot_info(slot)  # Reload to get updated info
                if info is not None:
                    self._bgcmd_slots.append((slot, info))

        # Update footer with bgcmd count
        self._update_bgcmd_count()

        # Update AXE tab layout if needed
        if self.current_tab == "axe":
            self._update_axe_layout()

    def _update_bgcmd_count(self) -> None:
        """Update the keybinding footer with bgcmd running/done counts."""
        from ..widgets import KeybindingFooter

        running_count, done_count = self._get_bgcmd_counts()
        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_bgcmd_count(running_count, done_count)
        except Exception:
            pass

    def _get_bgcmd_counts(self) -> tuple[int, int]:
        """Get running and done counts for background commands.

        Returns:
            Tuple of (running_count, done_count).
        """
        running_count = 0
        done_count = 0
        for slot, _ in self._bgcmd_slots:
            if is_slot_running(slot):
                running_count += 1
            else:
                done_count += 1
        return running_count, done_count

    def _update_axe_layout(self) -> None:
        """Update AXE tab layout based on whether bgcmds are running."""
        try:
            bgcmd_list_container = self.query_one("#bgcmd-list-container")  # type: ignore[attr-defined]
            has_bgcmds = len(self._bgcmd_slots) > 0

            if has_bgcmds:
                bgcmd_list_container.remove_class("hidden")
            else:
                bgcmd_list_container.add_class("hidden")
                # If current view is a bgcmd that's no longer running, switch to axe
                if self._axe_current_view != "axe":
                    self._axe_current_view = "axe"
        except Exception:
            pass

    def _refresh_axe_display(self) -> None:
        """Refresh the axe dashboard display."""
        from textual.containers import VerticalScroll

        from ..widgets import AxeDashboard, AxeInfoPanel, BgCmdList, KeybindingFooter

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            axe_dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]

            # Update countdown
            axe_info.update_countdown(self._countdown_remaining, self.refresh_interval)

            # Update info panel based on current view
            if self._axe_current_view == "axe":
                if self._axe_lumberjack_idx is not None and self._axe_lumberjack_names:
                    # Show lumberjack-specific view
                    lj_name = self._axe_lumberjack_names[self._axe_lumberjack_idx]
                    lj_output = read_lumberjack_log_tail(lj_name, 500)
                    lj_status = read_lumberjack_status(lj_name)
                    lj_idx = self._axe_lumberjack_idx
                    lj_total = len(self._axe_lumberjack_names)

                    axe_info.update_lumberjack_status(lj_name, lj_idx, lj_total)
                    axe_dashboard.update_lumberjack_display(
                        name=lj_name,
                        idx=lj_idx,
                        total=lj_total,
                        status=lj_status,
                        output=lj_output,
                        countdown=self._countdown_remaining,
                    )
                else:
                    # Show main output (legacy behavior)
                    axe_info.update_status(self.axe_running)

                    # Get full cycles from metrics if available
                    full_cycles = 0
                    if self._axe_metrics:
                        full_cycles = self._axe_metrics.full_cycles_run

                    axe_dashboard.update_display(
                        is_running=self.axe_running,
                        status=self._axe_status,
                        output=self._axe_output,
                        full_cycles=full_cycles,
                        countdown=self._countdown_remaining,
                    )
            else:
                # Showing a bgcmd view
                slot = self._axe_current_view
                info = get_slot_info(slot)
                running = is_slot_running(slot)

                # Check if command just finished and mark it
                if info is not None and not running and info.finished_at is None:
                    mark_slot_finished(slot)
                    info = get_slot_info(slot)  # Reload to get updated info

                output = read_slot_output_tail(slot, 500)

                axe_info.update_bgcmd_status(slot, info, running)
                axe_dashboard.update_bgcmd_display(
                    info, output, running, self._countdown_remaining
                )

            from ..modals import get_runner_count

            footer.set_axe_running(self.axe_running)
            running_count, done_count = self._get_bgcmd_counts()
            footer.set_bgcmd_count(running_count, done_count)
            footer.set_runner_count(get_runner_count())
            if getattr(self, "_bang_mode_active", False):
                footer.update_bang_bindings()
            elif getattr(self, "_copy_mode_active", False):
                footer.update_copy_bindings(self.current_tab)
            else:
                # Compute lumberjack info for footer
                footer_lj_name: str | None = None
                footer_lj_idx: int | None = None
                footer_lj_total = len(self._axe_lumberjack_names)
                if self._axe_lumberjack_idx is not None and self._axe_lumberjack_names:
                    footer_lj_name = self._axe_lumberjack_names[
                        self._axe_lumberjack_idx
                    ]
                    footer_lj_idx = self._axe_lumberjack_idx
                footer.update_axe_bindings(
                    axe_current_view=self._axe_current_view,
                    lumberjack_name=footer_lj_name,
                    lumberjack_idx=footer_lj_idx,
                    lumberjack_total=footer_lj_total,
                )

            # Update bgcmd list if visible
            if len(self._bgcmd_slots) > 0:
                try:
                    bgcmd_list = self.query_one("#bgcmd-list-panel", BgCmdList)  # type: ignore[attr-defined]
                    bgcmd_list.update_list(
                        axe_running=self.axe_running,
                        bgcmd_slots=self._bgcmd_slots,
                        current_item=self._axe_current_view,
                    )
                except Exception:
                    pass

            # Auto-scroll to bottom if pinned and on axe view
            if self._axe_pinned_to_bottom and self._axe_current_view == "axe":
                scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
                scroll_container.scroll_end(animate=False)
        except Exception:
            # Widget not found, possibly not on axe tab
            pass

    def _update_axe_info_panel(self) -> None:
        """Update the axe info panel and dashboard status bar with countdown."""
        from ..widgets import AxeDashboard, AxeInfoPanel

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            if self._axe_current_view == "axe":
                axe_info.update_status(self.axe_running)
            else:
                slot = self._axe_current_view
                info = get_slot_info(slot)
                running = is_slot_running(slot)
                axe_info.update_bgcmd_status(slot, info, running)
            axe_info.update_countdown(self._countdown_remaining, self.refresh_interval)

            # Also update dashboard status bar countdown
            axe_dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            axe_dashboard.update_countdown(self._countdown_remaining)
        except Exception:
            pass

    def _update_axe_keybinding(self) -> None:
        """Update the keybinding footer with current axe state."""
        from ..widgets import KeybindingFooter

        running_count, done_count = self._get_bgcmd_counts()
        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_running(self.axe_running)
            footer.set_bgcmd_count(running_count, done_count)
        except Exception:
            pass

    def _set_axe_starting(self, starting: bool) -> None:
        """Set axe starting state and update footer.

        Args:
            starting: Whether axe is currently starting up.
        """
        from ..widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_starting(starting)
        except Exception:
            pass

    def _set_axe_stopping(self, stopping: bool) -> None:
        """Set axe stopping state and update footer.

        Args:
            stopping: Whether axe is currently stopping.
        """
        from ..widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_stopping(stopping)
        except Exception:
            pass

"""Keybinding footer widget for the ace TUI.

Footer Convention
-----------------
The footer displays **conditional** keymaps — bindings whose availability
is determined by the currently selected entry (Patch, Agent, etc.) or
by transient app state (e.g. marks exist, completed agents present).

Rules:
  1. A keymap appears in the footer **if and only if** it has an associated
     condition that is sometimes true and sometimes false.
  2. Global actions (quit, refresh, tab switch, fold, etc.) are NOT shown —
     they belong in the help modal only.  Contextual query actions are the
     exception because their ownership changes by tab.

Formatting:
  - Keymaps are sorted alphabetically; symbol keys (``<enter>``, ``<space>``,
    ``.``, ``/``, …) come first.
  - Named keys are rendered in angle brackets and lowercased:
    ``<enter>``, ``<space>``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ..keymaps import KeymapRegistry, footer_key_display, load_keymap_registry
from ._keybinding_bindings import KeybindingBindingsMixin
from ._keybinding_layout import _MODE_BADGE_STYLE, KeybindingLayoutMixin
from ._keybinding_modes import KeybindingModesMixin
from ._keybinding_status import (
    _STARTUP_STOPWATCH_TIMEOUT_SECS,
    _STOPWATCH_BG_FLASH_OFF,
    _STOPWATCH_BG_FLASH_ON,
    _STOPWATCH_BG_NORMAL,
    _STOPWATCH_BG_ORANGE,
    _STOPWATCH_BG_RED,
    _STOPWATCH_BG_YELLOW,
    _STOPWATCH_FG_DARK,
    _STOPWATCH_FG_LIGHT,
    _STOPWATCH_FLASH_PERIOD_TICKS,
    _STOPWATCH_GLYPH_FRAMES,
    _STOPWATCH_TIER_FLASH_SECS,
    _STOPWATCH_TIER_ORANGE_SECS,
    _STOPWATCH_TIER_RED_SECS,
    _STOPWATCH_TIER_YELLOW_SECS,
    KeybindingStatusMixin,
)

if TYPE_CHECKING:
    from textual.timer import Timer


class KeybindingFooter(
    KeybindingModesMixin,
    KeybindingLayoutMixin,
    KeybindingStatusMixin,
    KeybindingBindingsMixin,
    Horizontal,
):
    """Footer showing available keybindings with status indicator on the right."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the footer widget."""
        super().__init__(**kwargs)
        self._registry: KeymapRegistry | None = None
        self._axe_running: bool = False
        self._axe_starting: bool = False
        self._axe_stopping: bool = False
        self._axe_restarting: bool = False
        self._bgcmd_running_count: int = 0
        self._bgcmd_done_count: int = 0
        self._runner_count: int = 0
        self._startup_stopwatch_active: bool = True
        self._startup_start_time: float = time.monotonic()
        self._startup_elapsed: float = 0.0
        self._startup_stopwatch_timer: Timer | None = None
        self._stopwatch_frame: int = 0
        # Signatures of the most recently rendered bindings/status text.
        # An update with an identical signature short-circuits before it
        # touches the child widgets — j/k bursts that don't change state
        # repaint zero times.
        self._last_bindings_signature: tuple[Any, ...] | None = None
        self._last_status_signature: tuple[Any, ...] | None = None
        # Last (bindings, mode_label) tuple so ``on_resize`` can recompute
        # the layout without callers having to push state again.
        self._last_layout_inputs: tuple[list[tuple[str, str]], str | None] | None = None
        # Child Static refs cached on mount so each ``_update_display``
        # call avoids a ``query_one`` walk.  ``None`` until ``on_mount``.
        self._content_widget: Static | None = None
        self._status_widget: Static | None = None

    def on_mount(self) -> None:
        """Anchor the startup stopwatch and begin ticking every 0.1s."""
        # Cache child Static refs once so hot updates skip the DOM query.
        try:
            self._content_widget = self.query_one("#keybinding-content", Static)
            self._status_widget = self.query_one("#keybinding-status", Static)
        except Exception:
            self._content_widget = None
            self._status_widget = None
        if not self._startup_stopwatch_active:
            return
        self._startup_start_time = time.monotonic()
        self._startup_elapsed = 0.0
        self._startup_stopwatch_timer = self.set_interval(
            0.1, self._on_stopwatch_tick, name="startup-stopwatch"
        )
        self._update_status()

    def on_resize(self) -> None:
        """Recompute the layout when the footer width changes.

        The bindings/status signature cache absorbs no-op repaints when
        the rendered output is unchanged (e.g. an inline footer that
        comfortably fit before still fits after a small resize).
        """
        if self._last_layout_inputs is None:
            return
        bindings, mode_label = self._last_layout_inputs
        self._update_display(bindings, mode_label)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry with user config."""
        self._registry = registry

    def _kr(self) -> KeymapRegistry:
        """Return the active registry, lazy-loading defaults on first use.

        The default load is only paid by callers that read keymaps before
        ``set_keymap_registry()`` runs (tests, and any pre-mount edge case).
        Production startup wires the real registry from ``on_mount`` before
        any read fires, so the default load is never executed there.
        """
        if self._registry is None:
            self._registry = load_keymap_registry({})
        return self._registry

    def _kd(self, action_name: str) -> str:
        """Get footer display key for an app-level action."""
        return footer_key_display(getattr(self._kr().app, action_name))

    def compose(self) -> ComposeResult:
        """Compose the footer with bindings on left and status on right."""
        yield Static(id="keybinding-content")
        yield Static(id="keybinding-status")

    def set_runner_count(self, count: int) -> None:
        """Update the runner count for AXE tab bindings.

        Args:
            count: Number of active runners (processes + agents).
        """
        self._runner_count = count

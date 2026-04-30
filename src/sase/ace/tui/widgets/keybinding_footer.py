"""Keybinding footer widget for the ace TUI.

Footer Convention
-----------------
The footer displays **conditional** keymaps — bindings whose availability
is determined by the currently selected entry (ChangeSpec, Agent, etc.) or
by transient app state (e.g. marks exist, completed agents present).

Rules:
  1. A keymap appears in the footer **if and only if** it has an associated
     condition that is sometimes true and sometimes false.
  2. Global actions (quit, refresh, tab switch, fold, edit query, etc.) are
     NOT shown — they belong in the help modal only.

Formatting:
  - Keymaps are sorted alphabetically; symbol keys (``<enter>``, ``<space>``,
    ``.``, ``/``, …) come first.
  - Named keys are rendered in angle brackets and lowercased:
    ``<enter>``, ``<space>``.
"""

import time
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ...changespec import ChangeSpec
from ..keymaps import KeymapRegistry, footer_key_display, load_keymap_registry
from ._keybinding_bindings import KeybindingBindingsMixin

if TYPE_CHECKING:
    from textual.timer import Timer

    from ..models.agent import Agent

_STARTUP_STOPWATCH_TIMEOUT_SECS = 30.0
_STARTUP_STOPWATCH_SLOW_THRESHOLD_SECS = 10.0
_STOPWATCH_GLYPH_FRAMES = ("◴", "◷", "◶", "◵")
_STOPWATCH_BG_NORMAL = "rgb(155,89,182)"
_STOPWATCH_BG_SLOW = "rgb(214,51,132)"
_STOPWATCH_FG = "bold white"


class KeybindingFooter(KeybindingBindingsMixin, Horizontal):
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

    def set_runner_count(self, count: int) -> None:
        """Update the runner count for AXE tab bindings.

        Args:
            count: Number of active runners (processes + agents).
        """
        self._runner_count = count

    def _status_signature(self) -> tuple[Any, ...]:
        """Compact signature of every input that drives status rendering."""
        if self._startup_stopwatch_active:
            return (
                "startup",
                round(self._startup_elapsed, 1),
                self._stopwatch_frame % len(_STOPWATCH_GLYPH_FRAMES),
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

    def _resolve_status_widget(self) -> Static | None:
        if self._status_widget is not None:
            return self._status_widget
        try:
            self._status_widget = self.query_one("#keybinding-status", Static)
        except Exception:
            return None
        return self._status_widget

    def _resolve_content_widget(self) -> Static | None:
        if self._content_widget is not None:
            return self._content_widget
        try:
            self._content_widget = self.query_one("#keybinding-content", Static)
        except Exception:
            return None
        return self._content_widget

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
        if self._startup_stopwatch_active:
            if self._startup_elapsed >= _STARTUP_STOPWATCH_SLOW_THRESHOLD_SECS:
                bg = _STOPWATCH_BG_SLOW
            else:
                bg = _STOPWATCH_BG_NORMAL
            glyph = _STOPWATCH_GLYPH_FRAMES[
                self._stopwatch_frame % len(_STOPWATCH_GLYPH_FRAMES)
            ]
            text.append(f"  {glyph} ", style=f"{_STOPWATCH_FG} on {bg}")
            text.append("starting ", style=f"white on {bg}")
            text.append(
                f"{self._startup_elapsed:.1f}s  ",
                style=f"{_STOPWATCH_FG} on {bg}",
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

        # Add bgcmd badges if there are any background commands
        if self._bgcmd_running_count > 0 or self._bgcmd_done_count > 0:
            text.append(" ")
            # Running count badge: [*R] in cyan
            if self._bgcmd_running_count > 0:
                text.append(
                    f" [*{self._bgcmd_running_count}] ", style="bold black on #00D7AF"
                )
            # Done count badge: [✓D] in gold
            if self._bgcmd_done_count > 0:
                text.append(
                    f" [✓{self._bgcmd_done_count}] ", style="bold black on #FFD700"
                )

        return text

    def _update_display(self, bindings_text: Text) -> None:
        """Update both the bindings content and status indicator.

        Skips the actual ``Static.update`` calls when the signatures of
        the bindings text and the status indicator both match the last
        render — j/k bursts on the same entry repaint zero times.

        Args:
            bindings_text: Formatted text for the keybindings.
        """
        # ``Text`` carries spans we want to compare too; the rendered
        # ``__rich_console__`` output isn't readily available, so we hash
        # the plain text plus span tuples.
        bindings_signature = (
            bindings_text.plain,
            tuple((s.start, s.end, str(s.style)) for s in bindings_text.spans),
        )
        status_signature = self._status_signature()
        bindings_dirty = bindings_signature != self._last_bindings_signature
        status_dirty = status_signature != self._last_status_signature
        if not bindings_dirty and not status_dirty:
            return
        content = self._resolve_content_widget()
        status = self._resolve_status_widget()
        if bindings_dirty and content is not None:
            content.update(bindings_text)
            self._last_bindings_signature = bindings_signature
        if status_dirty and status is not None:
            status.update(self._get_status_text())
            self._last_status_signature = status_signature

    def update_bindings(self, changespec: ChangeSpec, *, mark_count: int = 0) -> None:
        """Update bindings based on current ChangeSpec and app state."""
        bindings = self._compute_available_bindings(changespec, mark_count=mark_count)
        text = self._format_bindings(bindings)
        self._update_display(text)

    def show_empty(self, *, project_name: str | None = None) -> None:
        """Show empty state bindings.

        Args:
            project_name: If set, also show the tmux binding (sole project filter).
        """
        text = Text()
        if project_name:
            text.append(self._kd("open_tmux"), style="bold #00D7AF")
            text.append(" tmux", style="dim")
            text.append("  ")
        text.append(self._kd("edit_query"), style="bold #00D7AF")
        text.append(" edit query", style="dim")
        self._update_display(text)

    def update_agent_bindings(
        self,
        agent: "Agent | None",
        *,
        completed_count: int = 0,
        can_jump_to_changespec: bool = False,
        marked_count: int = 0,
        attempt_pinned: bool = False,
        group_focused: bool = False,
    ) -> None:
        """Update bindings for Agents tab."""
        bindings = self._compute_agent_bindings(
            agent,
            completed_count=completed_count,
            can_jump_to_changespec=can_jump_to_changespec,
            marked_count=marked_count,
            attempt_pinned=attempt_pinned,
            group_focused=group_focused,
        )
        text = self._format_bindings(bindings)
        self._update_display(text)

    def update_axe_bindings(
        self,
        *,
        axe_current_view: str | int = "axe",
        selected_slot_done: bool = False,
    ) -> None:
        """Update bindings for Axe tab (entry-dependent only)."""
        bindings = self._compute_axe_bindings(
            axe_current_view, selected_slot_done=selected_slot_done
        )
        text = self._format_bindings(bindings)
        self._update_display(text)

    def update_fold_bindings(self) -> None:
        """Update bindings to show fold mode options."""
        d = footer_key_display
        keys = self._kr().fold_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings = [
            (k("cycle_commits"), "commits"),
            (k("cycle_hooks"), "hooks"),
            (k("cycle_mentors"), "mentors"),
            (k("cycle_timestamps"), "timestamps"),
            (k("cycle_deltas"), "deltas"),
            (k("toggle_commits"), "toggle commits"),
            (k("toggle_hooks"), "toggle hooks"),
            (k("toggle_mentors"), "toggle mentors"),
            (k("toggle_timestamps"), "toggle timestamps"),
            (k("toggle_deltas"), "toggle deltas"),
            (k("cycle_all"), "all"),
            (k("toggle_all"), "toggle"),
        ]
        text = self._format_bindings(bindings)
        prefix = Text()
        prefix.append("FOLD ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_jump_bindings(self, *, has_back: bool = False) -> None:
        """Update bindings to show entry jump mode options."""
        bindings: list[tuple[str, str]] = [("'", "back" if has_back else "first")]
        bindings.append(("<esc>", "cancel"))
        text = self._format_bindings(bindings)
        prefix = Text()
        prefix.append("JUMP ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_leader_bindings(
        self,
        *,
        current_tab: str = "changespecs",
        has_comments: bool = False,
        has_notification: bool = False,
        has_mentor_results: bool = False,
    ) -> None:
        """Update bindings to show leader mode options.

        Args:
            current_tab: The currently active tab name.
            has_comments: Whether the selected ChangeSpec has a COMMENTS field.
            has_notification: Whether the selected agent has a pending notification.
            has_mentor_results: Whether the selected ChangeSpec has mentor results.
        """
        d = footer_key_display
        keys = self._kr().leader_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings: list[tuple[str, str]] = []
        if current_tab == "changespecs":
            if has_comments:
                bindings.append((k("clear_comments"), "clear comments"))
            bindings.append((k("run_cmd"), "run cmd (CL)"))
            bindings.append((k("kill_mentors"), "manage mentors"))
            if has_mentor_results:
                bindings.append((k("review_mentors"), "review mentors"))
        if self._runner_count > 0:
            bindings.append((k("runners"), f"runners ({self._runner_count})"))
        bindings.append((k("agent_home"), "agent (home)"))
        if current_tab in ("changespecs", "agents"):
            bindings.append((k("agent_from_cl"), "run agent (CL)"))
        bindings.append((k("prompt_history"), "prompt history"))
        bindings.append((k("prompt_history_cancelled"), "history (+cancelled)"))
        if current_tab == "agents":
            bindings.append((k("kill_and_edit"), "kill & edit"))
            bindings.append((k("retry_edit"), "retry (edit)"))
            if has_notification:
                bindings.append((k("jump_to_notification"), "notification"))
        bindings.append((k("task_queue"), "task queue"))
        bindings.append((k("activity_info"), "activity"))
        bindings.append((k("temporary_llm_override"), "temporary model"))
        bindings.append((k("mark_inactive"), "mark idle"))
        text = self._format_bindings(bindings)
        # Add leader mode indicator prefix
        prefix = Text()
        prefix.append("LEADER ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_bang_bindings(self) -> None:
        """Update bindings to show bang mode options."""
        d = footer_key_display
        keys = self._kr().bang_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings = [
            (k("run_cmd"), "run cmd"),
            (k("toggle_axe"), "start/stop axe"),
        ]
        text = self._format_bindings(bindings)
        # Add bang mode indicator prefix
        prefix = Text()
        prefix.append("BANG ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_custom_mode_bindings(self, mode_name: str) -> None:
        """Update bindings to show custom mode options.

        Args:
            mode_name: Name of the active custom mode.
        """
        d = footer_key_display
        mode = self._kr().modes.get(mode_name)
        if mode is None:
            return

        bindings: list[tuple[str, str]] = []
        for action_name, spec in mode.keys.items():
            if not isinstance(spec, dict):
                continue
            key = spec.get("key", "")
            desc = spec.get("description", action_name)
            bindings.append((d(key), desc))

        text = self._format_bindings(bindings)
        prefix = Text()
        display_name = mode_name.upper().replace("_", " ")
        prefix.append(f"{display_name} ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_copy_bindings(self, tab: str, *, file_visible: bool = False) -> None:
        """Update bindings to show copy mode options for the current tab.

        Args:
            tab: Current tab name ("changespecs", "agents", or "axe").
            file_visible: Whether the file panel is visible (agents tab only).
        """
        d = footer_key_display
        tab_keys = self._kr().copy_mode.keys.get(tab, {})
        assert isinstance(tab_keys, dict)

        def k(name: str) -> str:
            v = tab_keys[name]
            assert isinstance(v, str)
            return d(v)

        if tab == "changespecs":
            bindings = [
                (k("raw"), "raw"),
                (k("with_snapshot"), "+snap"),
                (k("bug"), "bug"),
                (k("cl_number"), "CL#"),
                (k("name"), "name"),
                (k("spec"), "spec"),
                (k("snapshot"), "snap"),
            ]
        elif tab == "agents":
            bindings = [
                (k("chat"), "chat"),
                (k("name"), "name"),
                (k("prompt"), "prompt"),
                (k("snapshot"), "snap"),
            ]
            if file_visible:
                bindings.append((k("file_path"), "file path"))
        else:  # axe
            bindings = [
                (k("visible"), "visible"),
                (k("full"), "full"),
                (k("snapshot"), "snap"),
            ]
        text = self._format_bindings(bindings)
        prefix = Text()
        prefix.append("COPY ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

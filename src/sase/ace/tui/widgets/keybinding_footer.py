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

from rich.cells import cell_len
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

_MODE_BADGE_STYLE = "bold black on #FFD700"
# `padding: 0 1` on the footer + the 1-cell gutter between content and
# status that Textual leaves between the two flex children.
_CONTENT_RESERVED_CELLS = 2


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

    @staticmethod
    def _render_mode_badge(label: str) -> Text:
        """Mode prefix rendered as a filled pill badge.

        Pulls the mode word (``LEADER``, ``FOLD``, …) out of the binding flow
        so it never reads as another binding label, especially after wrap.
        """
        badge = Text(no_wrap=True)
        badge.append(f" {label} ", style=_MODE_BADGE_STYLE)
        return badge

    def _available_content_width(self) -> int:
        """Cells available to the bindings column on the current footer width.

        Returns 0 when the widget is not yet mounted / sized — callers
        treat this as "width unknown" and fall back to inline mode.
        """
        content = self._resolve_content_widget()
        if content is not None and content.size.width > 0:
            return int(content.size.width)
        try:
            footer_width = int(self.size.width)
        except Exception:
            footer_width = 0
        if footer_width <= 0:
            return 0
        status_w = cell_len(self._get_status_text().plain)
        return max(0, footer_width - status_w - _CONTENT_RESERVED_CELLS)

    def _layout(
        self,
        bindings: list[tuple[str, str]],
        mode_label: str | None,
    ) -> Text:
        """Decide between inline and grid layouts and return the rendered Text.

        The mode badge anchors the top-left in both layouts. In grid mode it
        sits on its own row so the chips can flow left-to-right starting at
        the same column.
        """
        sorted_b = self._sorted_bindings(bindings)
        inline_chips = self._format_bindings_inline(sorted_b)
        badge: Text | None = self._render_mode_badge(mode_label) if mode_label else None

        available = self._available_content_width()

        # Single-line width = badge + (one space) + inline chips.
        inline_chips_width = cell_len(inline_chips.plain)
        badge_width = cell_len(badge.plain) + 1 if badge is not None else 0
        single_line_width = badge_width + inline_chips_width

        # Inline if width is unknown, fits, or there is nothing to flow.
        if available <= 0 or single_line_width <= available or not sorted_b:
            return self._compose_inline(badge, inline_chips)

        # Compute grid columns. If a single chip is wider than the budget,
        # fall back to inline and let Rich wrap the long chip itself.
        max_chip = max(self._chip_plain_width(k, lbl) for k, lbl in sorted_b)
        cell_width = max_chip + 2  # +2 column gap (matches _format_bindings_grid)
        if cell_width > available:
            return self._compose_inline(badge, inline_chips)
        columns = max(1, available // cell_width)
        grid = self._format_bindings_grid(sorted_b, columns=columns)
        return self._compose_grid(badge, grid)

    @staticmethod
    def _compose_inline(badge: Text | None, chips: Text) -> Text:
        out = Text(no_wrap=True)
        if badge is not None:
            out.append_text(badge)
            out.append(" ")
        out.append_text(chips)
        return out

    @staticmethod
    def _compose_grid(badge: Text | None, grid: Text) -> Text:
        out = Text(no_wrap=True)
        if badge is not None:
            out.append_text(badge)
            if len(grid.plain) > 0:
                out.append("\n")
        out.append_text(grid)
        return out

    def _update_display(
        self,
        bindings: list[tuple[str, str]],
        mode_label: str | None = None,
    ) -> None:
        """Lay out the bindings and refresh the content/status widgets.

        Skips the actual ``Static.update`` calls when the signatures of
        the bindings text and the status indicator both match the last
        render — j/k bursts on the same entry repaint zero times.

        Args:
            bindings: ``(key, label)`` pairs to display, unsorted.
            mode_label: Optional mode word (e.g. ``"LEADER"``) rendered as
                a pill badge anchoring the layout.
        """
        # Remember the inputs so ``on_resize`` can re-lay-out without state.
        self._last_layout_inputs = (list(bindings), mode_label)

        bindings_text = self._layout(bindings, mode_label)
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
        self._update_display(bindings)

    def show_empty(self, *, project_name: str | None = None) -> None:
        """Show empty state bindings.

        Args:
            project_name: If set, also show the tmux binding (sole project filter).
        """
        bindings: list[tuple[str, str]] = []
        if project_name:
            bindings.append((self._kd("open_tmux"), "tmux"))
        bindings.append((self._kd("edit_query"), "edit query"))
        self._update_display(bindings)

    def update_agent_bindings(
        self,
        agent: "Agent | None",
        *,
        completed_count: int = 0,
        can_jump_to_changespec: bool = False,
        marked_count: int = 0,
        attempt_pinned: bool = False,
        group_focused: bool = False,
        has_agent_artifacts: bool = False,
        artifact_viewer_active: bool = False,
        sibling_count: int = 0,
    ) -> None:
        """Update bindings for Agents tab."""
        bindings = self._compute_agent_bindings(
            agent,
            completed_count=completed_count,
            can_jump_to_changespec=can_jump_to_changespec,
            marked_count=marked_count,
            attempt_pinned=attempt_pinned,
            group_focused=group_focused,
            has_agent_artifacts=has_agent_artifacts,
            artifact_viewer_active=artifact_viewer_active,
            sibling_count=sibling_count,
        )
        self._update_display(bindings)

    def update_axe_bindings(
        self,
        *,
        axe_current_view: str | int = "axe",
        selected_slot_done: bool = False,
        chop_run_total: int = 0,
        chop_selected: bool = False,
        chop_selected_running: bool = False,
    ) -> None:
        """Update bindings for Axe tab (entry-dependent only)."""
        bindings = self._compute_axe_bindings(
            axe_current_view,
            selected_slot_done=selected_slot_done,
            chop_run_total=chop_run_total,
            chop_selected=chop_selected,
            chop_selected_running=chop_selected_running,
        )
        self._update_display(bindings)

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
        self._update_display(bindings, mode_label="FOLD")

    def update_jump_bindings(self, *, has_back: bool = False) -> None:
        """Update bindings to show entry jump mode options."""
        bindings: list[tuple[str, str]] = [("'", "back" if has_back else "first")]
        bindings.append(("<esc>", "cancel"))
        self._update_display(bindings, mode_label="JUMP")

    def update_leader_bindings(
        self,
        *,
        current_tab: str = "changespecs",
        has_comments: bool = False,
        has_notification: bool = False,
        has_mentor_results: bool = False,
        has_unread_completed_agent: bool = False,
        has_stopped_agent: bool = False,
        has_revertable_agent: bool = False,
    ) -> None:
        """Update bindings to show leader mode options.

        Args:
            current_tab: The currently active tab name.
            has_comments: Whether the selected ChangeSpec has a COMMENTS field.
            has_notification: Whether the selected agent has a pending notification.
            has_mentor_results: Whether the selected ChangeSpec has mentor results.
            has_unread_completed_agent: Whether any completed agent is unread.
            has_stopped_agent: Whether any stopped agent is loaded.
            has_revertable_agent: Whether the selected Agents-tab row is a
                done/failed agent whose commits can be reverted.
        """
        d = footer_key_display
        keys = self._kr().leader_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings: list[tuple[str, str]] = []
        bindings.append((k("repeat_last"), "repeat"))
        if current_tab == "changespecs":
            if has_comments:
                bindings.append((k("clear_comments"), "clear comments"))
            bindings.append((k("run_cmd"), "run cmd (PR)"))
            bindings.append((k("kill_mentors"), "manage mentors"))
            if has_mentor_results:
                bindings.append((k("review_mentors"), "review mentors"))
            bindings.append((k("agent_run_log"), "agent run log"))
        if self._runner_count > 0:
            bindings.append((k("runners"), f"runners ({self._runner_count})"))
        bindings.append((k("agent_home"), "agent (home)"))
        if current_tab in ("changespecs", "agents"):
            bindings.append((k("agent_from_cl"), "run agent (PR)"))
        if current_tab == "agents":
            bindings.append((k("toggle_agent_panel_grouping"), "group panels"))
            bindings.append((k("full_history_refresh"), "full history refresh"))
            if has_stopped_agent:
                bindings.append((k("jump_to_next_stopped_agent"), "next stopped"))
            if has_unread_completed_agent:
                bindings.append(
                    (k("jump_to_next_unread_done_agent"), "next unread done")
                )
                bindings.append(
                    (k("mark_all_unread_done_agents_read"), "mark all read")
                )
        bindings.append((k("prompt_history"), "prompt history"))
        bindings.append((k("prompt_history_edit_first"), "edit history"))
        bindings.append((k("prompt_history_cancelled"), "history (+cancelled)"))
        if current_tab == "agents":
            bindings.append((k("kill_and_edit"), "kill & edit"))
            if has_revertable_agent:
                bindings.append((k("revert_agent"), "revert agent"))
            bindings.append((k("capture_agents_repro"), "capture repro"))
            bindings.append((k("toggle_agents_repro_checks"), "repro checks"))
            if has_notification:
                bindings.append((k("jump_to_notification"), "notification"))
        bindings.append((k("task_queue"), "task queue"))
        bindings.append((k("activity_info"), "activity"))
        bindings.append((k("projects"), "projects"))
        bindings.append((k("temporary_llm_override"), "model overrides"))
        bindings.append((k("mark_inactive"), "mark idle"))
        self._update_display(bindings, mode_label="LEADER")

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
        self._update_display(bindings, mode_label="BANG")

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

        display_name = mode_name.upper().replace("_", " ")
        self._update_display(bindings, mode_label=display_name)

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
                (k("cl_number"), "PR#"),
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
        self._update_display(bindings, mode_label="COPY")

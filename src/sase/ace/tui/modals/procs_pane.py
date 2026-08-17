"""Procs pane for the SASE Admin Center.

The pane renders the app's read-only proc observer projection. This module is
the stable public facade; selection, observer refresh, and user actions live in
focused sibling modules.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Static

from ..actions.navigation.jump_hints import normalize_jump_key
from ..proc_observer import ObservedProc, ProcProjection, proc_projection_for
from ..util.selection import ProgrammaticSelectionGuard
from .config_center_session import ProcsSessionState
from .pane_entry_jump import PaneEntryJumpMixin
from .procs_pane_actions import ProcsPaneActionsMixin
from .procs_pane_render import BodyCache
from .procs_pane_selection import ProcsPaneSelectionMixin, TaskList
from .procs_pane_store import ProcsPaneStoreMixin
from .procs_store_rows import kill_store_task


class ProcsPane(
    PaneEntryJumpMixin,
    ProcsPaneActionsMixin,
    ProcsPaneStoreMixin,
    ProcsPaneSelectionMixin,
    Vertical,
):
    """Two-panel live proc monitor inside the Admin Center."""

    can_focus = False

    _option_list_id = "procs-list"
    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("a", "toggle_scope", "All Sessions"),
        ("d", "dismiss_task", "Dismiss"),
        ("D", "dismiss_all_done", "Dismiss All Done"),
        ("K", "kill_task", "Kill"),
        ("e", "edit_output", "Edit"),
        ("y", "copy_output", "Copy"),
        ("ctrl+d", "scroll_output_down", "Scroll Down"),
        ("ctrl+u", "scroll_output_up", "Scroll Up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
        ("shift+g", "scroll_to_bottom", "Bottom"),
        ("apostrophe", "jump_to_entry", "Jump"),
    ]

    def __init__(
        self,
        *,
        session_state: ProcsSessionState | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._session_state = session_state or ProcsSessionState()
        self._tasks: list[ObservedProc] = []
        self._monitor_agent_names: dict[str, str] = {}
        self._last_statuses: dict[str, tuple[str, str | None, str]] = {}
        self._user_scrolled = False
        self._selection_guard = ProgrammaticSelectionGuard()
        self._refresh_timer: Any | None = None
        self._spinner_index = 0
        self._body_cache: BodyCache = {}
        self._all_sessions = self._session_state.all_sessions
        self._session_id: str | None = None
        self._store_detail_id: str | None = None
        self._store_loaded_once = False
        self._tick_count = 0

    def compose(self) -> ComposeResult:
        yield Label(self._title_text(), id="procs-pane-title")
        with Horizontal(id="procs-panels"):
            with Vertical(id="procs-list-panel"):
                yield Label("Procs", classes="config-region-header")
                yield TaskList(id=self._option_list_id)
            with Vertical(id="procs-output-panel"):
                yield Label(
                    "Output", classes="config-region-header", id="procs-output-title"
                )
                with VerticalScroll(id="procs-output-scroll"):
                    yield Static("", id="procs-output-content", markup=False)
        yield Static(self._hints(), id="procs-hints", markup=False)

    def on_mount(self) -> None:
        self._session_id = self._proc_projection().session_id
        self._refresh_snapshot()
        self._request_store_reload(force=True)
        self._refresh_timer = self.set_interval(0.25, self._refresh_running_output)

    def on_unmount(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def focus_default(self) -> None:
        """Focus the task list and paint the latest snapshot on activation."""
        self._refresh_snapshot()
        self._request_store_reload(force=True)
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    def on_key(self, event: events.Key) -> None:
        if self.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self.handle_jump_key(key):
                event.prevent_default()
                event.stop()
                return
        if event.key == "apostrophe":
            event.prevent_default()
            event.stop()
            self.action_jump_to_entry()

    def _jump_target_count(self) -> int:
        return len(self._tasks)

    def _jump_current_index(self) -> int | None:
        return self._highlighted_row()

    def _jump_select_index(self, index: int) -> None:
        if not 0 <= index < len(self._tasks):
            return
        identity = self._task_identity(self._tasks[index])
        self._rebuild_list(highlight_index=index, prior_identity=identity)

    def _jump_repaint(self) -> None:
        self._rebuild_list()
        self._update_hints()

    def _update_hints(self) -> None:
        try:
            self.query_one("#procs-hints", Static).update(self._hints())
        except Exception:
            pass

    def _proc_projection(self) -> ProcProjection:
        return proc_projection_for(self.app)

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    def _signal_store_task(self, proc_id: str) -> str | None:
        """Call the facade's patchable durable-task kill helper."""
        return kill_store_task(proc_id)

    @staticmethod
    def _run_editor(editor_args: list[str]) -> None:
        """Run the configured editor through the facade's patchable subprocess."""
        subprocess.run(editor_args, check=False)

    def _hints(self) -> str:
        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            return f"JUMP ' {action}  <esc> cancel"
        return (
            "j/k: move  a: scope  d/D: dismiss  K: kill  e: edit  y: copy  "
            "': jump  ctrl+d/u, g/G: scroll  Tab: tab  Esc: close"
        )


__all__ = ["ProcsPane"]

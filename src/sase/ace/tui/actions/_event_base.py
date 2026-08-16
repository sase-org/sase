"""Shared types and helpers for ACE TUI event handlers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ..util.nav_gate import NavigationGate

if TYPE_CHECKING:
    from ...patch import Patch
    from ..models import Agent

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]


class EventHandlersBase:
    """Shared attributes and helpers for event handler mixins."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _countdown_remaining: int
    _fold_mode_active: bool
    _checkout_mode_active: bool
    _saved_query_mode_active: bool
    _copy_mode_active: bool
    _agents: list[Agent]
    _agents_loading: bool
    _patches_last_idx: int
    _agents_last_idx: int
    _ancestor_mode_active: bool
    _child_mode_active: bool
    _sibling_mode_active: bool
    _hint_mode_active: bool
    _accept_mode_active: bool
    _leader_mode_active: bool
    _bang_mode_active: bool
    _bead_issue_mode_active: bool
    _custom_mode_active: str | None
    _custom_mode_prefixes: dict[str, str]
    _entry_jump_mode_active: bool
    _entry_jump_pending_prefix: str
    _member_jump_pending_digit: str | None
    _last_input_mono: float
    _last_input_action: str | None
    _nav_gate: NavigationGate
    _dirty_patches: bool
    _dirty_agents: bool
    _dirty_agent_artifact_dirs: tuple[Path, ...]
    _dirty_deleted_agent_artifact_dirs: tuple[Path, ...]
    _dirty_agent_artifact_fallback_reason: str | None
    _dirty_axe: bool
    _dirty_notifications: bool
    _artifact_change_defer_pending: bool
    _last_full_sanity_refresh: float
    _prompt_editor_suspended: bool

    def _refresh_current_tab(self) -> None:
        """Refresh the display for whichever tab is currently active.

        Use this instead of _refresh_display() when the caller may be on any tab
        (e.g. exiting bang/copy mode).
        """
        if self.current_tab == "artifacts":
            self._refresh_display()  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._refresh_agents_display()  # type: ignore[attr-defined]
        else:  # axe
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _record_jk_navigation(self) -> None:
        """Mark the wall-clock of the latest j/k action.

        Background reconcilers consult :class:`NavigationGate` to decide
        whether to fire now or defer until the user pauses, so the cursor
        highlight wins during long input bursts.
        """
        self._nav_gate.record()

    def _record_input_event(self) -> None:
        """Record input for event handlers that run before timer mixins."""
        raise NotImplementedError

    def _prompt_input_active(self) -> bool:
        """Return True while a prompt surface is mounted or editor-suspended."""
        if getattr(self, "_prompt_editor_suspended", False):
            return True

        query = getattr(self, "query", None)
        if query is None:
            return False

        from ..widgets.prompt_input_bar import PromptInputBar

        return bool(query(PromptInputBar))

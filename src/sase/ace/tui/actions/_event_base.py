"""Shared types and helpers for ACE TUI event handlers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ..util.nav_gate import NavigationGate
from ..widgets import PromptInputBar

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..models import Agent

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class EventHandlersBase:
    """Shared attributes and helpers for event handler mixins."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _countdown_remaining: int
    _fold_mode_active: bool
    _checkout_mode_active: bool
    _copy_mode_active: bool
    _agents: list[Agent]
    _agents_loading: bool
    _changespecs_last_idx: int
    _agents_last_idx: int
    _ancestor_mode_active: bool
    _child_mode_active: bool
    _sibling_mode_active: bool
    _hint_mode_active: bool
    _accept_mode_active: bool
    _leader_mode_active: bool
    _bang_mode_active: bool
    _custom_mode_active: str | None
    _custom_mode_prefixes: dict[str, str]
    _entry_jump_mode_active: bool
    _member_jump_pending_digit: str | None
    _last_input_mono: float
    _last_input_action: str | None
    _nav_gate: NavigationGate
    _dirty_changespecs: bool
    _dirty_agents: bool
    _dirty_agent_artifact_dirs: tuple[Path, ...]
    _dirty_deleted_agent_artifact_dirs: tuple[Path, ...]
    _dirty_agent_artifact_fallback_reason: str | None
    _dirty_axe: bool
    _dirty_notifications: bool
    _artifact_change_defer_pending: bool
    _last_full_sanity_refresh: float

    def _refresh_current_tab(self) -> None:
        """Refresh the display for whichever tab is currently active.

        Use this instead of _refresh_display() when the caller may be on any tab
        (e.g. exiting bang/copy mode).
        """
        if self.current_tab == "changespecs":
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
        """Return True while any prompt-like input surface is mounted."""
        if getattr(self, "_prompt_context", None) is not None:
            return True
        if getattr(self, "_approve_prompt_context", None) is not None:
            return True
        if getattr(self, "_plan_feedback_context", None) is not None:
            return True

        query = getattr(self, "query", None)
        if query is None:
            return False

        return bool(query(PromptInputBar))

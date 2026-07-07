"""Shared type hints and helpers for hint action mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Import ChangeSpec and Agent unconditionally since they are used as type
# annotations in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec
from ...tools.report import SlowToolCallReportSpec
from ...models.agent import Agent
from ...widgets import HintInputBar


class HintMixinBase:
    """Base class providing shared type hints for all hint action mixins.

    These type hints declare attributes that are defined at runtime by AceApp.
    All hint action sub-mixins should inherit from this class.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int

    # Tab and agents state
    current_tab: str
    _agents: list[Agent]

    # Hint mode state
    _hint_mode_active: bool
    _hint_mode_hints_for: str | None
    _hint_mappings: dict[int, str]
    _hint_tool_call_reports: dict[str, SlowToolCallReportSpec]
    _hook_hint_to_idx: dict[int, int]
    _hint_to_entry_id: dict[int, str]
    _mentor_hint_to_info: dict[int, tuple[str, str]]
    _hint_changespec_name: str

    # Accept mode state
    _accept_mode_active: bool
    _accept_last_base: str | None

    # Rewind mode state
    _rewind_mode_active: bool

    # Failed hooks state
    _failed_hooks_targets: list[str]
    _failed_hooks_file_path: str | None

    def _hint_input_bar_active(self) -> bool:
        """Return whether any transient hint input mode is active."""
        return (
            self._hint_mode_active
            or self._accept_mode_active
            or self._rewind_mode_active
        )

    def _refocus_existing_hint_bar(self) -> bool:
        """Focus an already-mounted hint bar, if present.

        Returns ``True`` when a bar exists so callers can avoid mounting a
        duplicate ``#hint-input-bar`` while Textual still has the id registered.
        """
        from textual.css.query import NoMatches

        query_one = getattr(self, "query_one", None)
        if not callable(query_one):
            return False

        try:
            hint_bar = query_one("#hint-input-bar", HintInputBar)
        except NoMatches:
            return False

        try:
            hint_input = hint_bar.query_one("#hint-input")
            hint_input.focus()
        except Exception:
            pass
        return True

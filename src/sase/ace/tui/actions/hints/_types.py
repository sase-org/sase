"""Shared type hints for hint action mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Import ChangeSpec and Agent unconditionally since they are used as type
# annotations in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec
from ...models.agent import Agent


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

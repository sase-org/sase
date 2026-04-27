"""Shared type aliases and protocol attributes for clipboard mixin sub-files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...keymaps import KeymapRegistry
    from ...models import Agent

TabName = Literal["changespecs", "agents", "axe"]
AxeViewType = Literal["axe"] | int


class ClipboardBase:
    """Common attribute hints for AceApp accessed from clipboard mixins."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    _agents: list[Agent]
    _axe_current_view: AxeViewType
    _axe_output: str
    _keymap_registry: KeymapRegistry

"""Shared type aliases and protocol attributes for clipboard mixin sub-files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

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
    current_artifacts_subtab: Any
    _agents: list[Agent]
    _axe_current_view: AxeViewType
    _axe_output: str
    _keymap_registry: KeymapRegistry

    @property
    def current_artifacts_pane_key(self) -> Any:
        """Resolve nested Files identity for standalone clipboard harnesses."""

        from ...artifact_tabs import artifacts_pane_key

        return artifacts_pane_key(
            self.current_artifacts_subtab,
            getattr(self, "current_files_subtab", "other"),
        )

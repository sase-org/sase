"""Shared type aliases and protocol attributes for clipboard mixin sub-files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ....patch import Patch
    from ...keymaps import KeymapRegistry
    from ...models import Agent

TabName = Literal["artifacts", "patches", "agents", "axe"]
AxeViewType = Literal["axe"] | int


class ClipboardBase:
    """Common attribute hints for AceApp accessed from clipboard mixins."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
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

    @property
    def changespecs(self) -> list[Patch]:  # legacy compatibility alias
        return getattr(self, "patches", [])

    @changespecs.setter  # legacy compatibility alias
    def changespecs(self, value: list[Patch]) -> None:  # legacy compatibility alias
        self.patches = value

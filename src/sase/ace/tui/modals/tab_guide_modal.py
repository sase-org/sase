"""Per-tab onboarding guide modal for ACE."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen

from ..keymaps import KeymapRegistry, load_keymap_registry
from ..widgets import AgentOnboarding, AxeOnboarding, ChangeSpecOnboarding

TabName = Literal["changespecs", "agents", "axe"]

_TAB_META: dict[TabName, tuple[str, str]] = {
    "changespecs": ("PRs Guide", "-tab-changespecs"),
    "agents": ("Agents Guide", "-tab-agents"),
    "axe": ("AXE Guide", "-tab-axe"),
}


class TabGuideModal(ModalScreen[None]):
    """Modal that shows the current tab's onboarding guide on demand."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("question_mark", "close", "Close"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(
        self,
        *,
        current_tab: TabName,
        registry: KeymapRegistry | None = None,
        agents_launch_targets_available: bool = False,
        agents_plugins_installed: bool = True,
    ) -> None:
        super().__init__()
        self._current_tab = current_tab
        self._registry = registry or load_keymap_registry({})
        self._agents_launch_targets_available = agents_launch_targets_available
        self._agents_plugins_installed = agents_plugins_installed

    def compose(self) -> ComposeResult:
        """Compose the modal with a fresh guide widget for the active tab."""
        title, tab_class = _TAB_META[self._current_tab]
        with Container(id="tab-guide-container", classes=tab_class) as container:
            container.border_title = title
            container.border_subtitle = "esc closes"
            yield self._build_guide()

    def _build_guide(self) -> VerticalScroll:
        """Build a new guide widget for the selected tab."""
        if self._current_tab == "changespecs":
            changespecs_guide = ChangeSpecOnboarding(
                id="tab-guide-content",
            )
            changespecs_guide.set_keymap_registry(self._registry)
            return changespecs_guide
        elif self._current_tab == "agents":
            agents_guide = AgentOnboarding(id="tab-guide-content")
            agents_guide.set_launch_targets_available(
                self._agents_launch_targets_available,
                refresh=False,
            )
            agents_guide.set_plugins_installed(self._agents_plugins_installed)
            agents_guide.set_keymap_registry(self._registry)
            return agents_guide
        else:
            axe_guide = AxeOnboarding(id="tab-guide-content")
            axe_guide.set_keymap_registry(self._registry)
            return axe_guide

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        """Scroll the guide down by half a page."""
        scroll = self.query_one("#tab-guide-content", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the guide up by half a page."""
        scroll = self.query_one("#tab-guide-content", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

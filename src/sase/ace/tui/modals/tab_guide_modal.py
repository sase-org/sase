"""Per-tab onboarding guide modal for ACE."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen

from ..keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ..widgets import AgentOnboarding, AxeOnboarding, ChangeSpecOnboarding

if TYPE_CHECKING:
    from ..app import AceApp

TabName = Literal["changespecs", "agents", "axe"]

_TAB_META: dict[TabName, tuple[str, str]] = {
    "changespecs": ("PRs Guide", "-tab-changespecs"),
    "agents": ("Agents Guide", "-tab-agents"),
    "axe": ("AXE Guide", "-tab-axe"),
}


def _modal_key_display(key: str) -> str:
    display = key_display_name(key)
    if display in {"Tab", "Shift+Tab"}:
        return display.lower()
    return display


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
            container.border_subtitle = self._guide_border_subtitle()
            yield self._build_guide()

    def _guide_border_subtitle(self) -> str:
        next_tab = _modal_key_display(self._registry.app.next_tab)
        prev_tab = _modal_key_display(self._registry.app.prev_tab)
        return f"esc closes · {next_tab}/{prev_tab} tabs"

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

    def refresh_for_tab(
        self,
        *,
        current_tab: TabName,
        registry: KeymapRegistry,
        agents_launch_targets_available: bool = False,
        agents_plugins_installed: bool = True,
    ) -> None:
        """Refresh the mounted guide for a new tab context."""
        self._current_tab = current_tab
        self._registry = registry
        self._agents_launch_targets_available = agents_launch_targets_available
        self._agents_plugins_installed = agents_plugins_installed

        try:
            container = self.query_one("#tab-guide-container", Container)
        except (NoMatches, LookupError):
            return

        title, tab_class = _TAB_META[self._current_tab]
        container.border_title = title
        container.border_subtitle = self._guide_border_subtitle()
        for _, old_tab_class in _TAB_META.values():
            container.remove_class(old_tab_class)
        container.add_class(tab_class)

        new_guide = self._build_guide()
        try:
            old_guide = self.query_one("#tab-guide-content", VerticalScroll)
        except (NoMatches, LookupError):
            container.mount(new_guide)
            return

        parent = getattr(old_guide, "_parent", None)
        if parent is not None:
            parent._nodes._remove(old_guide)  # type: ignore[attr-defined]
        old_guide.remove()
        container.mount(new_guide)

    def on_mount(self) -> None:
        """Rebuild instance bindings with configured tab-switch keys."""
        from textual.binding import BindingsMap

        new_bindings: list[BindingType] = [
            ("escape", "close", "Close"),
            ("q", "close", "Close"),
            ("question_mark", "close", "Close"),
            ("ctrl+d", "scroll_down", "Scroll down"),
            ("ctrl+u", "scroll_up", "Scroll up"),
            Binding(
                self._registry.app.next_tab,
                "next_tab",
                "Next Tab",
                show=False,
                priority=True,
            ),
            Binding(
                self._registry.app.prev_tab,
                "prev_tab",
                "Prev Tab",
                show=False,
                priority=True,
            ),
        ]
        self._bindings = BindingsMap(new_bindings)

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

    def action_next_tab(self) -> None:
        """Switch the underlying ACE app to the next tab."""
        cast("AceApp", self.app).action_next_tab()

    def action_prev_tab(self) -> None:
        """Switch the underlying ACE app to the previous tab."""
        cast("AceApp", self.app).action_prev_tab()

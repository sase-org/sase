"""Onboarding panel for the empty Agents tab."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ..tab_order import TAB_ORDER, TabName

_DOCS_URL = "https://sase.sh"
_UPDATES_ACCENT = "#AF87FF"

_STEP_BASE_TITLES: tuple[tuple[str, str], ...] = (
    ("#agent-onboarding-launch", "Launch your first agent"),
    ("#agent-onboarding-tabs", "The three tabs"),
    ("#agent-onboarding-plugins", "Install plugins & keep sase current"),
    ("#agent-onboarding-help", "Get more help"),
)

# Per-tab onboarding row copy, keyed by tab name.  Rows are rendered in the
# shared ``TAB_ORDER`` so this guide can never drift from the visible tab bar.
_TAB_ROWS: dict[TabName, tuple[str, str, str]] = {
    "agents": (
        "Agents",
        "#87D7FF",
        "Inspect prompts, diffs, tools, and artifacts. You are here.",
    ),
    "changespecs": (
        "PRs",
        "#00D7AF",
        "Browse ChangeSpecs: commits, hooks, mentors, and status.",
    ),
    "axe": (
        "AXE",
        "#FF5F5F",
        "Monitor the Axe daemon and automation.",
    ),
}


def _append_keycap(text: Text, label: str) -> None:
    text.append(" ")
    text.append(f" {label} ", style="bold #1a1a1a on #00D7AF")
    text.append(" ")


def _append_section_heading(text: Text, label: str) -> None:
    text.append(label, style="bold #87D7FF")
    text.append("\n")


class AgentOnboarding(VerticalScroll):
    """Right-pane guide shown when the Agents tab has no agents."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registry: KeymapRegistry = load_keymap_registry({})
        self._launch_targets_available = False
        self._plugins_installed = True

    def compose(self) -> ComposeResult:
        """Compose the fixed onboarding sections."""
        yield Static(
            self._build_hero(),
            id="agent-onboarding-hero",
            classes="agent-onboarding-hero",
        )

        launch = Static(
            self._build_launch_card(
                self._registry,
                launch_targets_available=self._launch_targets_available,
            ),
            id="agent-onboarding-launch",
            classes="agent-onboarding-card",
        )
        yield launch

        tabs = Static(
            self._build_tabs_card(self._registry),
            id="agent-onboarding-tabs",
            classes="agent-onboarding-card",
        )
        yield tabs

        plugins = Static(
            self._build_plugins_card(self._registry),
            id="agent-onboarding-plugins",
            classes="agent-onboarding-card -recommend hidden",
        )
        yield plugins

        help_card = Static(
            self._build_help_card(self._registry),
            id="agent-onboarding-help",
            classes="agent-onboarding-card",
        )
        yield help_card

        yield Static(
            self._build_footer(),
            id="agent-onboarding-footer",
            classes="agent-onboarding-footer",
        )

    def on_mount(self) -> None:
        """Render with the current registry after mount."""
        self.refresh_content()
        self._apply_plugins_visibility()
        self._apply_step_numbers()

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active keymap registry and refresh displayed hints."""
        self._registry = registry
        self.refresh_content()
        self._apply_plugins_visibility()
        self._apply_step_numbers()

    def set_launch_targets_available(
        self, available: bool, *, refresh: bool = True
    ) -> None:
        """Control whether the project/CL launch-target hint is rendered."""
        changed = self._launch_targets_available != available
        self._launch_targets_available = available
        if changed and refresh:
            self.refresh_launch_card()

    def set_plugins_installed(self, installed: bool) -> None:
        """Control whether the plugin recommendation card is rendered."""
        changed = self._plugins_installed != installed
        self._plugins_installed = installed
        if changed and self.is_mounted:
            self._apply_plugins_visibility()
            self._apply_step_numbers()

    def refresh_launch_card(self) -> None:
        """Refresh only the launch card from current state."""
        if not self.is_mounted:
            return
        self.query_one("#agent-onboarding-launch", Static).update(
            self._build_launch_card(
                self._registry,
                launch_targets_available=self._launch_targets_available,
            )
        )

    def refresh_content(self) -> None:
        """Refresh static sections from the current keymap registry."""
        if not self.is_mounted:
            return
        sections = self.render_content(self._registry)
        for selector, content in sections.items():
            self.query_one(selector, Static).update(content)

    def _apply_plugins_visibility(self) -> None:
        """Show the plugin recommendation only for bare installs."""
        if not self.is_mounted:
            return
        plugins = self.query_one("#agent-onboarding-plugins", Static)
        plugins.set_class(self._plugins_installed, "hidden")

    def _ordered_step_selectors(self) -> list[tuple[str, str]]:
        """Return selectors and base titles for currently visible steps."""
        steps: list[tuple[str, str]] = []
        for selector, base_title in _STEP_BASE_TITLES:
            if selector == "#agent-onboarding-plugins" and self._plugins_installed:
                continue
            steps.append((selector, base_title))
        return steps

    def numbered_step_titles(self) -> list[str]:
        """Return current step border titles without requiring a mounted widget."""
        return [
            f"{step_number} {base_title}"
            for step_number, (_selector, base_title) in enumerate(
                self._ordered_step_selectors(), start=1
            )
        ]

    def _apply_step_numbers(self) -> None:
        """Apply contiguous border-title numbering to visible cards."""
        if not self.is_mounted:
            return
        for border_title, (selector, _base_title) in zip(
            self.numbered_step_titles(),
            self._ordered_step_selectors(),
            strict=True,
        ):
            self.query_one(selector, Static).border_title = border_title

    def render_content(
        self,
        registry: KeymapRegistry,
        *,
        launch_targets_available: bool | None = None,
    ) -> dict[str, Text]:
        """Build all renderable sections for *registry*.

        Tests call this method directly to verify keybinding-driven copy
        without needing a mounted Textual app.
        """
        if launch_targets_available is None:
            launch_targets_available = self._launch_targets_available
        return {
            "#agent-onboarding-hero": self._build_hero(),
            "#agent-onboarding-launch": self._build_launch_card(
                registry,
                launch_targets_available=launch_targets_available,
            ),
            "#agent-onboarding-tabs": self._build_tabs_card(registry),
            "#agent-onboarding-plugins": self._build_plugins_card(registry),
            "#agent-onboarding-help": self._build_help_card(registry),
            "#agent-onboarding-footer": self._build_footer(),
        }

    @staticmethod
    def _build_hero() -> Text:
        text = Text(justify="center")
        text.append("*  ", style="bold #FFD700")
        text.append("Welcome to sase ace", style="bold #FFFFFF")
        text.append("  *\n", style="bold #FFD700")
        text.append("Structured Agentic Software Engineering", style="dim #87D7FF")
        return text

    @staticmethod
    def _build_launch_card(
        registry: KeymapRegistry, *, launch_targets_available: bool = False
    ) -> Text:
        app = registry.app
        text = Text()
        _append_section_heading(text, "Start from the prompt")
        _append_keycap(text, key_display_name(app.start_agent_home))
        text.append("open the prompt bar in your home workspace.")
        text.append("\n")
        if launch_targets_available:
            _append_keycap(text, key_display_name(app.start_custom_agent))
            text.append("pick a project or CL first.")
            text.append("\n")
        text.append("Works from any tab; shell: ", style="dim")
        text.append("sase ace", style="bold #FFD700")
        text.append(".", style="dim")
        return text

    @staticmethod
    def _append_tab_row(text: Text, label: str, style: str, description: str) -> None:
        text.append(f" {label} ", style=f"bold {style}")
        text.append("  ")
        text.append(description)
        text.append("\n")

    @classmethod
    def _build_tabs_card(cls, registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        _append_section_heading(text, "Know where you are")
        for tab in TAB_ORDER:
            label, color, description = _TAB_ROWS[tab]
            cls._append_tab_row(text, label, color, description)
        text.append("Switch with", style="dim")
        _append_keycap(text, key_display_name(app.next_tab))
        text.append("/", style="dim")
        _append_keycap(text, key_display_name(app.prev_tab))
        text.append(".")
        return text

    @staticmethod
    def _build_plugins_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        _append_section_heading(text, "Extend sase from the Admin Center")
        _append_keycap(text, key_display_name(app.open_config_center))
        text.append("open the ")
        text.append("SASE Admin Center", style="bold")
        text.append(", then its ")
        text.append("Updates", style=f"bold {_UPDATES_ACCENT}")
        text.append(" tab.")
        text.append("\n")
        _append_keycap(text, "i")
        text.append("install a plugin", style="dim")
        text.append(" · ", style="dim")
        _append_keycap(text, "u")
        text.append("update sase & all plugins.", style="dim")
        text.append("\n")
        text.append("Recommended first plugin: ", style="dim")
        text.append("sase-github", style=f"bold {_UPDATES_ACCENT}")
        text.append(" adds GitHub PR & repo workflows.", style="dim")
        return text

    @staticmethod
    def _build_help_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        _append_keycap(text, key_display_name(app.show_help))
        text.append("open the help pop-up for this tab.")
        text.append("\n")
        _append_keycap(text, key_display_name(app.open_command_palette))
        text.append("fuzzy-search and run any command.")
        text.append("\n")
        text.append(_DOCS_URL, style=f"bold #87D7FF link {_DOCS_URL}")
        text.append(" full documentation.", style="dim")
        return text

    @staticmethod
    def _build_footer() -> Text:
        text = Text(justify="center")
        text.append(
            "Your first agent appears on the left; this guide moves aside "
            "automatically.",
            style="dim italic",
        )
        return text

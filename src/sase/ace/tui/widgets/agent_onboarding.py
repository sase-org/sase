"""On-demand guide for the Agents tab."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..keymaps import (
    KeymapRegistry,
    key_display_name,
    leader_key_display,
    load_keymap_registry,
)
from ..tab_order import TAB_ORDER, TabName
from ._onboarding_common import (
    append_doc_link,
    append_keycap,
    append_section_heading,
)

_DOCS_URL = "https://sase.sh"
_ACE_DOCS_URL = "https://sase.sh/ace/"
_XPROMPT_DOCS_URL = "https://sase.sh/xprompt/"
_AGENTS_ACCENT = "#87D7FF"
_UPDATES_ACCENT = "#AF87FF"

_STEP_BASE_TITLES: tuple[tuple[str, str], ...] = (
    ("#agent-onboarding-launch", "Launch your first agent"),
    ("#agent-onboarding-inspect", "Inspect the results"),
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
        "Inspect prompts, diffs, tools, and artifact files. You are here.",
    ),
    "changespecs": (
        "Artifacts",
        "#00D7AF",
        "Browse commits, plans, bugs, PRs, and chats in one place.",
    ),
    "axe": (
        "AXE",
        "#FF5F5F",
        "Monitor the Axe daemon and automation.",
    ),
}


class AgentOnboarding(VerticalScroll):
    """In-depth Agents tab guide shown by the Help panel."""

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

        inspect = Static(
            self._build_inspect_card(self._registry),
            id="agent-onboarding-inspect",
            classes="agent-onboarding-card",
        )
        yield inspect

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
        """Control whether the project/ChangeSpec launch-target hint is rendered."""
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
            "#agent-onboarding-inspect": self._build_inspect_card(registry),
            "#agent-onboarding-tabs": self._build_tabs_card(registry),
            "#agent-onboarding-plugins": self._build_plugins_card(registry),
            "#agent-onboarding-help": self._build_help_card(registry),
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
        append_section_heading(text, "Start from the prompt", accent=_AGENTS_ACCENT)
        append_keycap(text, key_display_name(app.start_agent_home))
        text.append(
            "open the prompt bar and describe a task; this launches an agent "
            "in your home workspace."
        )
        text.append("\n")
        if launch_targets_available:
            append_keycap(text, key_display_name(app.start_custom_agent))
            text.append("launch against a specific project or PR instead.")
            text.append("\n")
        text.append("The prompt bar works from any tab.", style="dim")
        return text

    @staticmethod
    def _build_inspect_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(text, "Read what happened", accent=_AGENTS_ACCENT)
        text.append(
            "Watch a running agent live; when it finishes, review its transcript "
            "or jump to its PR.",
            style="dim",
        )
        text.append("\n")
        append_keycap(text, key_display_name(app.next_changespec))
        text.append("/")
        append_keycap(text, key_display_name(app.prev_changespec))
        text.append("select an agent.")
        append_keycap(text, key_display_name(app.edit_spec))
        text.append("open a finished agent's chat transcript in your editor.")
        text.append("\n")
        append_keycap(text, key_display_name(app.jump_to_agent_changespec))
        text.append("jump to the PR it produced.")
        append_keycap(text, key_display_name(app.open_artifact_files))
        text.append("browse artifact files.")
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
        append_section_heading(text, "Know where you are", accent=_AGENTS_ACCENT)
        for tab in TAB_ORDER:
            label, color, description = _TAB_ROWS[tab]
            cls._append_tab_row(text, label, color, description)
        text.append("Switch with", style="dim")
        append_keycap(text, key_display_name(app.next_tab))
        text.append("/", style="dim")
        append_keycap(text, key_display_name(app.prev_tab))
        text.append(".")
        return text

    @staticmethod
    def _build_plugins_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(
            text, "Extend sase from the Admin Center", accent=_AGENTS_ACCENT
        )
        append_keycap(text, key_display_name(app.open_config_center))
        text.append("open the ")
        text.append("SASE Admin Center", style="bold")
        text.append(", then its ")
        text.append("Updates", style=f"bold {_UPDATES_ACCENT}")
        text.append(" tab.")
        text.append("\n")
        append_keycap(text, "i")
        text.append("install a plugin", style="dim")
        text.append(" · ", style="dim")
        append_keycap(text, "u")
        text.append("update sase & all plugins", style="dim")
        text.append(" · ", style="dim")
        append_keycap(text, "A")
        text.append("update agent CLIs.", style="dim")
        text.append("\n")
        text.append("Recommended first plugin: ", style="dim")
        text.append("sase-github", style=f"bold {_UPDATES_ACCENT}")
        text.append(" adds GitHub PR & repo workflows.", style="dim")
        return text

    @staticmethod
    def _build_help_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_doc_link(
            text,
            _ACE_DOCS_URL,
            "the full ACE TUI guide, tab by tab.",
            accent=_AGENTS_ACCENT,
        )
        append_doc_link(
            text,
            _XPROMPT_DOCS_URL,
            "supercharge prompts with #xprompts.",
            accent=_AGENTS_ACCENT,
        )
        append_keycap(text, leader_key_display(registry, "show_help"))
        text.append("full keybinding reference for this tab.")
        text.append("\n")
        append_keycap(text, key_display_name(app.open_command_palette))
        text.append("fuzzy-search and run any command.")
        text.append("\n")
        text.append(_DOCS_URL, style=f"bold {_AGENTS_ACCENT} link {_DOCS_URL}")
        text.append(" full documentation.", style="dim")
        return text

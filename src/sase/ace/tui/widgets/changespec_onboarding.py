"""Onboarding panel for the empty PRs tab."""

from __future__ import annotations

from typing import Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ...display_helpers import get_status_color
from ..keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ._onboarding_common import (
    append_doc_link,
    append_keycap,
    append_leader_keycaps,
    append_section_heading,
    leader_key_sequence_display,
)

_ACCENT = "#00D7AF"
_CHANGESPEC_DOCS_URL = "https://sase.sh/change_spec/"
_VCS_DOCS_URL = "https://sase.sh/vcs/"
_PLUGINS_DOCS_URL = "https://sase.sh/plugins/"
_LIFECYCLE: tuple[str, ...] = ("WIP", "Draft", "Ready", "Mailed", "Submitted")


class ChangeSpecOnboarding(VerticalScroll):
    """PRs-tab guide shown before the first ChangeSpec or saved query exists."""

    def __init__(
        self, *, context: Literal["tab", "modal"] = "tab", **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._registry: KeymapRegistry = load_keymap_registry({})
        self._guide_context = context

    def compose(self) -> ComposeResult:
        """Compose the fixed onboarding sections."""
        yield Static(
            self._build_hero(),
            id="changespec-onboarding-hero",
            classes="changespec-onboarding-hero",
        )

        what = Static(
            self._build_what_card(),
            id="changespec-onboarding-what",
            classes="changespec-onboarding-card",
        )
        what.border_title = "What is a ChangeSpec?"
        yield what

        how = Static(
            self._build_how_card(self._registry),
            id="changespec-onboarding-how",
            classes="changespec-onboarding-card",
        )
        how.border_title = "How ChangeSpecs get here"
        yield how

        learn = Static(
            self._build_learn_card(self._registry),
            id="changespec-onboarding-learn",
            classes="changespec-onboarding-card",
        )
        learn.border_title = "Learn more"
        yield learn

        yield Static(
            self._build_footer(self._registry, context=self._guide_context),
            id="changespec-onboarding-footer",
            classes="changespec-onboarding-footer",
        )

    def on_mount(self) -> None:
        """Render with the current registry after mount."""
        self.refresh_content()

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use the active keymap registry and refresh displayed hints."""
        self._registry = registry
        self.refresh_content()

    def refresh_content(self) -> None:
        """Refresh static sections from the current keymap registry."""
        if not self.is_mounted:
            return
        sections = self.render_content(self._registry, context=self._guide_context)
        for selector, content in sections.items():
            self.query_one(selector, Static).update(content)

    @staticmethod
    def render_content(
        registry: KeymapRegistry,
        *,
        context: Literal["tab", "modal"] = "tab",
    ) -> dict[str, Text]:
        """Build all renderable sections for *registry*.

        Tests call this method directly to verify keybinding-driven copy
        without needing a mounted Textual app.
        """
        return {
            "#changespec-onboarding-hero": ChangeSpecOnboarding._build_hero(),
            "#changespec-onboarding-what": ChangeSpecOnboarding._build_what_card(),
            "#changespec-onboarding-how": ChangeSpecOnboarding._build_how_card(
                registry
            ),
            "#changespec-onboarding-learn": ChangeSpecOnboarding._build_learn_card(
                registry
            ),
            "#changespec-onboarding-footer": ChangeSpecOnboarding._build_footer(
                registry, context=context
            ),
        }

    @staticmethod
    def _build_hero() -> Text:
        text = Text(justify="center")
        text.append("*  ", style="bold #FFD700")
        text.append("Your agents' work, shipped as PRs", style="bold #FFFFFF")
        text.append("  *\n", style="bold #FFD700")
        text.append(
            "Every CL/PR your agents produce, tracked in one place",
            style=f"dim {_ACCENT}",
        )
        return text

    @classmethod
    def _build_what_card(cls) -> Text:
        text = Text()
        append_section_heading(text, "One ChangeSpec = one CL/PR", accent=_ACCENT)
        text.append(
            "Each tracks the full life of a change: commits, hook runs, "
            "review comments, mentors, and status."
        )
        text.append("\n")
        text.append("Status lifecycle: ", style="dim")
        cls._append_lifecycle(text)
        text.append("\n")
        text.append("Stored as plain text you can open anytime: ", style="dim")
        text.append("~/.sase/projects/", style=f"bold {_ACCENT}")
        return text

    @staticmethod
    def _append_lifecycle(text: Text) -> None:
        for idx, status in enumerate(_LIFECYCLE):
            if idx:
                text.append(" -> ", style="dim")
            text.append(status, style=f"bold {get_status_color(status)}")

    @staticmethod
    def _build_how_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(text, "Agents create them for you", accent=_ACCENT)
        text.append(
            "Launch an agent against a project or CL and its work is registered "
            "here automatically."
        )
        text.append("\n")
        text.append(
            "The commit workflow appends commits and hook results as the "
            "agent makes progress.",
            style="dim",
        )
        text.append("\n")
        append_keycap(text, key_display_name(app.prev_tab))
        text.append("switch to the Agents tab and launch your first agent.")
        return text

    @staticmethod
    def _build_learn_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_doc_link(
            text,
            _CHANGESPEC_DOCS_URL,
            "ChangeSpec anatomy & lifecycle.",
            accent=_ACCENT,
        )
        append_doc_link(
            text,
            _VCS_DOCS_URL,
            "sase's pluggable VCS system.",
            accent=_ACCENT,
        )
        append_doc_link(
            text,
            _PLUGINS_DOCS_URL,
            "sase-github & other PR integrations.",
            accent=_ACCENT,
        )
        append_keycap(text, key_display_name(app.show_help))
        text.append("open the help pop-up for this tab.")
        text.append("\n")
        append_leader_keycaps(text, registry, "tab_guide")
        text.append("reopen this guide anytime; it works on every tab.", style="dim")
        return text

    @staticmethod
    def _build_footer(
        registry: KeymapRegistry,
        *,
        context: Literal["tab", "modal"] = "tab",
    ) -> Text:
        text = Text(justify="center")
        if context == "modal":
            text.append("esc closes · ", style="dim italic")
            text.append(leader_key_sequence_display(registry, "tab_guide"), style="dim")
            text.append(" reopens this guide on any tab", style="dim italic")
        else:
            text.append(
                "Your first ChangeSpec replaces this guide with the live PR list.",
                style="dim italic",
            )
        return text

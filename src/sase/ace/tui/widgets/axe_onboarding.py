"""On-demand guide for the AXE tab."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..keymaps import (
    KeymapRegistry,
    key_display_name,
    load_keymap_registry,
)
from ._axe_dashboard_render import CHOP_NAME_STYLE, LJ_NAME_STYLE
from ._onboarding_common import (
    append_doc_link,
    append_keycap,
    append_section_heading,
    key_sequence_display,
)

_ACCENT = "#FF5F5F"
_DOCS_URL = "https://sase.sh"
_AXE_DOCS_URL = "https://sase.sh/axe/"
_WORKFLOW_SPEC_DOCS_URL = "https://sase.sh/workflow_spec/"
_MENTORS_DOCS_URL = "https://sase.sh/mentors/"


class AxeOnboarding(VerticalScroll):
    """AXE-tab guide shown inside the Help panel."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registry: KeymapRegistry = load_keymap_registry({})

    def compose(self) -> ComposeResult:
        """Compose the fixed AXE guide sections."""
        yield Static(
            self._build_hero(),
            id="axe-onboarding-hero",
            classes="axe-onboarding-hero",
        )

        what = Static(
            self._build_what_card(self._registry),
            id="axe-onboarding-what",
            classes="axe-onboarding-card",
        )
        what.border_title = "What is Axe?"
        yield what

        chops = Static(
            self._build_chops_card(self._registry),
            id="axe-onboarding-chops",
            classes="axe-onboarding-card",
        )
        chops.border_title = "Lumberjacks own chops"
        yield chops

        bgcmd = Static(
            self._build_bgcmd_card(self._registry),
            id="axe-onboarding-bgcmd",
            classes="axe-onboarding-card",
        )
        bgcmd.border_title = "Background commands"
        yield bgcmd

        learn = Static(
            self._build_learn_card(self._registry),
            id="axe-onboarding-learn",
            classes="axe-onboarding-card",
        )
        learn.border_title = "Learn more"
        yield learn

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
        sections = self.render_content(self._registry)
        for selector, content in sections.items():
            self.query_one(selector, Static).update(content)

    @staticmethod
    def render_content(registry: KeymapRegistry) -> dict[str, Text]:
        """Build all renderable sections for *registry*."""
        return {
            "#axe-onboarding-hero": AxeOnboarding._build_hero(),
            "#axe-onboarding-what": AxeOnboarding._build_what_card(registry),
            "#axe-onboarding-chops": AxeOnboarding._build_chops_card(registry),
            "#axe-onboarding-bgcmd": AxeOnboarding._build_bgcmd_card(registry),
            "#axe-onboarding-learn": AxeOnboarding._build_learn_card(registry),
        }

    @staticmethod
    def _build_hero() -> Text:
        text = Text(justify="center")
        text.append("*  ", style="bold #FFD700")
        text.append("Automation, always on", style="bold #FFFFFF")
        text.append("  *\n", style="bold #FFD700")
        text.append(
            "Axe is the daemon that keeps your hooks, mentors & workflows moving.",
            style=f"dim {_ACCENT}",
        )
        return text

    @staticmethod
    def _build_what_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(text, "Background automation loop", accent=_ACCENT)
        text.append("Axe starts automatically with ")
        text.append("sase ace", style="bold #FFD700")
        text.append(
            " and cycles through hooks, mentors, workflow checks, pending "
            "checks, and zombie cleanup."
        )
        text.append("\n")
        text.append(
            "Your PRs keep moving while you focus elsewhere.",
            style="dim",
        )
        text.append("\n")
        append_keycap(text, key_display_name(app.kill_agent))
        text.append("start or stop Axe (with the Axe row selected).")
        append_keycap(text, key_display_name(app.stop_axe_and_quit))
        text.append("open the quit/restart menu.")
        text.append("\n")
        text.append("Status bar anatomy: ", style="dim")
        text.append("Runtime", style="bold #FFD700")
        text.append(" · ", style="dim")
        text.append("Cycles", style="bold #87D7FF")
        text.append(" · ", style="dim")
        text.append("Hooks/Agents runner slots", style="bold #00D7AF")
        return text

    @staticmethod
    def _build_chops_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(
            text, "Scheduled work, inspectable output", accent=_ACCENT
        )
        text.append("A ")
        text.append("lumberjack", style=LJ_NAME_STYLE)
        text.append(" wakes on an interval; each owns ")
        text.append("chops", style=CHOP_NAME_STYLE)
        text.append(", the automation tasks it runs every cycle.")
        text.append("\n")
        append_keycap(text, key_display_name(app.next_patch))
        text.append("/")
        append_keycap(text, key_display_name(app.prev_patch))
        text.append("move through the sidebar.")
        append_keycap(text, key_display_name(app.run_workflow))
        text.append("run the selected chop now.")
        text.append("\n")
        append_keycap(text, key_display_name(app.add_axe_item))
        text.append("add a lumberjack or chop.")
        append_keycap(text, key_display_name(app.edit_spec))
        text.append("edit the selected AXE config.")
        text.append("\n")
        append_keycap(text, key_display_name(app.next_agent_file))
        text.append("/")
        append_keycap(text, key_display_name(app.prev_agent_file))
        text.append("next or previous chop run.")
        append_keycap(text, key_display_name(app.edit_panel))
        text.append("open recorded output.")
        text.append("\n")
        text.append(
            "Run history keeps each chop's status, duration, and captured output.",
            style="dim",
        )
        return text

    @staticmethod
    def _build_bgcmd_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        bang = registry.bang_mode
        run_cmd_key = bang.keys["run_cmd"]
        assert isinstance(run_cmd_key, str)
        text = Text()
        append_section_heading(
            text, "Run shell commands without leaving ACE", accent=_ACCENT
        )
        append_keycap(text, key_sequence_display(bang.prefix, run_cmd_key))
        text.append(
            "runs any shell command in a background slot with live output "
            "streaming into the dashboard."
        )
        text.append("\n")
        append_keycap(text, key_display_name(app.kill_agent))
        text.append("kill the selected running command.")
        append_keycap(text, key_display_name(app.open_agent_cleanup_panel))
        text.append("clear output.")
        append_keycap(text, key_display_name(app.run_workflow))
        text.append("re-run a finished command.")
        return text

    @staticmethod
    def _build_learn_card(registry: KeymapRegistry) -> Text:
        text = Text()
        append_doc_link(
            text,
            _AXE_DOCS_URL,
            "the full Axe guide: lumberjacks, chops & configuration.",
            accent=_ACCENT,
        )
        append_doc_link(
            text,
            _WORKFLOW_SPEC_DOCS_URL,
            "author the workflows that hooks & chops launch.",
            accent=_ACCENT,
        )
        append_doc_link(
            text,
            _MENTORS_DOCS_URL,
            "automated review mentors Axe keeps running.",
            accent=_ACCENT,
        )
        app = registry.app
        append_keycap(text, key_display_name(app.show_help))
        text.append("full keybinding reference for this tab.")
        text.append("\n")
        text.append(_DOCS_URL, style=f"bold {_ACCENT} link {_DOCS_URL}")
        text.append(" full documentation.", style="dim")
        return text

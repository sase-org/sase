"""On-demand guide for the Services tab."""

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
    """Services-tab guide shown inside the Help panel."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registry: KeymapRegistry = load_keymap_registry({})

    def compose(self) -> ComposeResult:
        """Compose the fixed Services guide sections."""
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
        what.border_title = "What is Services?"
        yield what

        jobs = Static(
            self._build_chops_card(self._registry),
            id="axe-onboarding-chops",
            classes="axe-onboarding-card",
        )
        jobs.border_title = "Routines own jobs"
        yield jobs

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
            "The service host keeps your service procs, scheduler jobs "
            "& oneshots moving.",
            style=f"dim {_ACCENT}",
        )
        return text

    @staticmethod
    def _build_what_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        bang = registry.bang_mode
        bang_prefix = bang.prefix
        toggle_host_key = bang.keys.get("toggle_axe")
        toggle_enablement_key = bang.keys.get("toggle_service_enablement")
        text = Text()
        append_section_heading(text, "Service host and service procs", accent=_ACCENT)
        text.append("The service host starts automatically with ")
        text.append("sase tui", style="bold #FFD700")
        text.append(" (unless --no-service) and keeps your service procs running.")
        text.append("\n")
        text.append(
            "Each service proc is one supervised row. The Scheduler proc nests "
            "its routines, and each routine nests the jobs it runs.",
            style="dim",
        )
        text.append("\n")
        append_keycap(text, key_display_name(app.kill_agent))
        text.append("start or stop the selected service proc.")
        if isinstance(toggle_host_key, str):
            append_keycap(text, key_sequence_display(bang_prefix, toggle_host_key))
            text.append("start or stop the service host.")
        if isinstance(toggle_enablement_key, str):
            append_keycap(
                text, key_sequence_display(bang_prefix, toggle_enablement_key)
            )
            text.append("enable or disable the selected service proc.")
        append_keycap(text, key_display_name(app.stop_axe_and_quit))
        text.append("open the quit/restart menu.")
        return text

    @staticmethod
    def _build_chops_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(
            text, "Scheduled work, inspectable output", accent=_ACCENT
        )
        text.append("A ")
        text.append("routine", style=LJ_NAME_STYLE)
        text.append(" wakes on an interval; each owns ")
        text.append("jobs", style=CHOP_NAME_STYLE)
        text.append(", the automation tasks it runs every cycle.")
        text.append("\n")
        append_keycap(text, key_display_name(app.next_patch))
        text.append("/")
        append_keycap(text, key_display_name(app.prev_patch))
        text.append("move through the sidebar.")
        append_keycap(text, key_display_name(app.run_workflow))
        text.append("restart the selected service proc or run the selected job now.")
        text.append("\n")
        append_keycap(text, key_display_name(app.add_axe_item))
        text.append("add a routine or job.")
        append_keycap(text, key_display_name(app.edit_spec))
        text.append("edit the selected routine or job config.")
        text.append("\n")
        append_keycap(text, key_display_name(app.next_agent_file))
        text.append("/")
        append_keycap(text, key_display_name(app.prev_agent_file))
        text.append("next or previous job run.")
        append_keycap(text, key_display_name(app.edit_panel))
        text.append("open recorded output.")
        text.append("\n")
        text.append(
            "Run history keeps each job's status, duration, and captured output.",
            style="dim",
        )
        text.append("\n")
        text.append("⚠ 2.4×", style="bold #FFAF5F")
        text.append(
            " marks a job that ran as long as its routine's interval; "
            "raise the interval or give it its own routine.",
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
            text, "Run shell commands without leaving sase's TUI", accent=_ACCENT
        )
        append_keycap(text, key_sequence_display(bang.prefix, run_cmd_key))
        text.append(
            "starts a new oneshot: any shell command with live output "
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
            "the full Services guide: service procs, routines, jobs & configuration.",
            accent=_ACCENT,
        )
        append_doc_link(
            text,
            _WORKFLOW_SPEC_DOCS_URL,
            "author the workflows that hooks & jobs launch.",
            accent=_ACCENT,
        )
        append_doc_link(
            text,
            _MENTORS_DOCS_URL,
            "automated review mentors the scheduler keeps running.",
            accent=_ACCENT,
        )
        app = registry.app
        append_keycap(text, key_display_name(app.show_help))
        text.append("full keybinding reference for this tab.")
        text.append("\n")
        text.append(_DOCS_URL, style=f"bold {_ACCENT} link {_DOCS_URL}")
        text.append(" full documentation.", style="dim")
        return text

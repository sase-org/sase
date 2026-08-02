"""On-demand guide for the Artifacts tab."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..artifact_tabs import (
    ARTIFACTS_ACCENTS,
    ARTIFACTS_SUBTAB_ORDER,
    FILES_SUBTAB_ORDER,
    ArtifactsSubTab,
    FilesSubTab,
)
from ...display_helpers import get_status_color
from ..keymaps import (
    KeymapRegistry,
    key_display_name,
    load_keymap_registry,
)
from ._onboarding_common import (
    append_doc_link,
    append_keycap,
    append_section_heading,
)

_ACCENT = "#00D7AF"
_CHANGESPEC_DOCS_URL = "https://sase.sh/change_spec/"
_VCS_DOCS_URL = "https://sase.sh/vcs/"
_PLUGINS_DOCS_URL = "https://sase.sh/plugins/"
_LIFECYCLE: tuple[str, ...] = ("WIP", "Draft", "Ready", "Mailed", "Submitted")
_ARTIFACT_DESCRIPTIONS: dict[ArtifactsSubTab, str] = {
    "commits": "Trace committed work across projects.",
    "beads": "Review task, epic, and phase work items.",
    "bugs": "Track issues and launch fixes.",
    "prs": "Inspect ChangeSpecs and move PRs through review.",
    "files": "Browse Plans, Chats, and Other artifact files.",
}
_FILES_DESCRIPTIONS: dict[FilesSubTab, str] = {
    "plans": "Plan proposals, active plans, and the archive.",
    "chats": "Agent chat transcripts and their sync state.",
    "other": "Every other artifact file agents have produced.",
}


class ChangeSpecOnboarding(VerticalScroll):
    """In-depth Artifacts tab guide shown by the Help panel."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registry: KeymapRegistry = load_keymap_registry({})

    def compose(self) -> ComposeResult:
        """Compose the fixed onboarding sections."""
        yield Static(
            self._build_hero(),
            id="changespec-onboarding-hero",
            classes="changespec-onboarding-hero",
        )

        tabs = Static(
            self._build_tabs_card(self._registry),
            id="changespec-onboarding-tabs",
            classes="changespec-onboarding-card",
        )
        tabs.border_title = "The five views"
        yield tabs

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

        queue = Static(
            self._build_queue_card(self._registry),
            id="changespec-onboarding-queue",
            classes="changespec-onboarding-card",
        )
        queue.border_title = "Work the PRs pane"
        yield queue

        learn = Static(
            self._build_learn_card(self._registry),
            id="changespec-onboarding-learn",
            classes="changespec-onboarding-card",
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
    def render_content(
        registry: KeymapRegistry,
    ) -> dict[str, Text]:
        """Build all renderable sections for *registry*.

        Tests call this method directly to verify keybinding-driven copy
        without needing a mounted Textual app.
        """
        return {
            "#changespec-onboarding-hero": ChangeSpecOnboarding._build_hero(),
            "#changespec-onboarding-tabs": ChangeSpecOnboarding._build_tabs_card(
                registry
            ),
            "#changespec-onboarding-what": ChangeSpecOnboarding._build_what_card(),
            "#changespec-onboarding-how": ChangeSpecOnboarding._build_how_card(
                registry
            ),
            "#changespec-onboarding-queue": ChangeSpecOnboarding._build_queue_card(
                registry
            ),
            "#changespec-onboarding-learn": ChangeSpecOnboarding._build_learn_card(
                registry
            ),
        }

    @staticmethod
    def _build_hero() -> Text:
        text = Text(justify="center")
        text.append("*  ", style="bold #FFD700")
        text.append(
            "Everything your agents produce, in one place",
            style="bold #FFFFFF",
        )
        text.append("  *\n", style="bold #FFD700")
        text.append(
            "Browse commits, beads, bugs, PRs, and nested files in Artifacts",
            style=f"dim {_ACCENT}",
        )
        return text

    @staticmethod
    def _artifact_label(subtab: ArtifactsSubTab) -> str:
        return subtab.upper() if subtab == "prs" else subtab.title()

    @staticmethod
    def _files_label(subtab: FilesSubTab) -> str:
        return subtab.title()

    @classmethod
    def _append_artifact_row(
        cls,
        text: Text,
        subtab: ArtifactsSubTab,
    ) -> None:
        text.append(
            f" {cls._artifact_label(subtab)} ",
            style=f"bold {ARTIFACTS_ACCENTS[subtab]}",
        )
        text.append("  ")
        text.append(_ARTIFACT_DESCRIPTIONS[subtab])
        text.append("\n")

    @classmethod
    def _append_files_row(cls, text: Text, subtab: FilesSubTab) -> None:
        text.append("    ", style="dim")
        text.append(
            f" {cls._files_label(subtab)} ",
            style=f"bold {ARTIFACTS_ACCENTS[subtab]}",
        )
        text.append("  ")
        text.append(_FILES_DESCRIPTIONS[subtab])
        text.append("\n")

    @classmethod
    def _build_tabs_card(cls, registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(text, "Know what each view shows", accent=_ACCENT)
        for subtab in ARTIFACTS_SUBTAB_ORDER:
            cls._append_artifact_row(text, subtab)
            if subtab == "files":
                for files_subtab in FILES_SUBTAB_ORDER:
                    cls._append_files_row(text, files_subtab)
        text.append("Jump directly:")
        for index, subtab in enumerate(ARTIFACTS_SUBTAB_ORDER, start=1):
            append_keycap(text, str(index))
            text.append(cls._artifact_label(subtab))
        text.append("\n")
        append_keycap(
            text,
            key_display_name(app.cycle_artifacts_subtab_reverse),
        )
        text.append("/")
        append_keycap(text, key_display_name(app.cycle_artifacts_subtab))
        text.append("cycle top-level views.")
        append_keycap(text, key_display_name(app.cycle_files_subtab_reverse))
        text.append("/")
        append_keycap(text, key_display_name(app.cycle_files_subtab))
        text.append("cycle Plans, Chats, and Other inside Files.")
        append_keycap(text, key_display_name(app.pick_artifacts_project))
        text.append("pick project scope.")
        return text

    @classmethod
    def _build_what_card(cls) -> Text:
        text = Text()
        append_section_heading(
            text,
            "In the PRs view, one ChangeSpec = one PR",
            accent=_ACCENT,
        )
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
            "Launch an agent against a project or PR and its work is registered "
            "in the PRs view automatically."
        )
        text.append("\n")
        text.append(
            "As the agent commits, its commits and hook results appear on "
            "the spec automatically.",
            style="dim",
        )
        text.append("\n")
        text.append("No specs yet?")
        append_keycap(text, key_display_name(app.prev_tab))
        text.append("to the Agents tab and launch your first agent.")
        return text

    @staticmethod
    def _build_queue_card(registry: KeymapRegistry) -> Text:
        app = registry.app
        text = Text()
        append_section_heading(text, "Move, inspect, and ship", accent=_ACCENT)
        append_keycap(text, key_display_name(app.next_changespec))
        text.append("/")
        append_keycap(text, key_display_name(app.prev_changespec))
        text.append("move through specs.")
        append_keycap(text, key_display_name(app.show_diff))
        text.append("show the diff.")
        text.append("\n")
        append_keycap(text, key_display_name(app.change_status))
        text.append("change status.")
        append_keycap(text, key_display_name(app.mail))
        text.append("mail for review.")
        append_keycap(text, key_display_name(app.edit_spec))
        text.append("open the spec in $EDITOR.")
        text.append("\n")
        append_keycap(text, key_display_name(app.edit_query))
        text.append("filter with a query.")
        return text

    @staticmethod
    def _build_learn_card(registry: KeymapRegistry) -> Text:
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
        app = registry.app
        append_keycap(text, key_display_name(app.show_help))
        text.append("full keybinding reference for this tab.")
        return text

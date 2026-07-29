"""Pane widgets and lazy lifecycle seam for the Artifacts tab."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from ...keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ..ancestors_children_panel import AncestorsChildrenPanel
from ..changespec_detail import ChangeSpecDetail, SearchQueryPanel
from ..changespec_info_panel import ChangeSpecInfoPanel
from ..changespec_list import ChangeSpecList
from ..tab_quickstart import TabQuickStart
from .lifecycle import ArtifactsPaneLifecycle
from .types import ARTIFACTS_ACCENTS, ArtifactsSubTab


class ArtifactsPrsPane(ArtifactsPaneLifecycle, Horizontal):
    """The existing ChangeSpec surface, hosted unchanged inside Artifacts."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        with Vertical(id="list-container"):
            yield ChangeSpecInfoPanel(id="info-panel")
            yield ChangeSpecList(id="list-panel")
            yield AncestorsChildrenPanel(id="ancestors-children-panel")
        with Vertical(id="detail-container"):
            yield SearchQueryPanel(id="search-query-panel")
            with VerticalScroll(id="detail-scroll"):
                yield ChangeSpecDetail(id="detail-panel")
            yield TabQuickStart(
                tab="changespecs",
                id="changespec-quickstart-panel",
                classes="hidden",
            )

    def on_activate(self) -> None:
        """Restore focus to the PR surface after another pane owned it."""
        if self.is_mounted:
            self.query_one("#list-panel", ChangeSpecList).focus()


_PLACEHOLDER_COPY: dict[ArtifactsSubTab, tuple[str, str, str]] = {
    "commits": (
        "Commits",
        "A cross-repository timeline with messages, tags, and diffs will live here.",
        "The Commits pane is scaffolded and will load only when you open it.",
    ),
    "bugs": (
        "Bugs",
        "Tracker-backed issue triage and links to epics and PRs will live here.",
        "Pick a project to establish the tracker scope for this pane.",
    ),
    "plans": (
        "Plans",
        "Plan proposals, epic progress, and committed plans across enabled projects.",
        "All enabled projects are included by default; pick one to narrow the scope.",
    ),
    "files": (
        "Files",
        "Every indexed artifact file, browsable across agents and projects.",
        "The Files pane loads only when you open it.",
    ),
}


class ArtifactPlaceholderPane(ArtifactsPaneLifecycle, Vertical):
    """Quickstart-style empty state used until a pane's feature phase lands."""

    def __init__(self, subtab: ArtifactsSubTab, **kwargs: Any) -> None:
        if subtab == "prs":
            raise ValueError("the PRs pane is not a placeholder")
        super().__init__(**kwargs)
        self.subtab = subtab
        self.project_scope: str | None = None
        self._project_display_name: str | None = None
        self._registry = load_keymap_registry({})
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        yield Static(self._scope_text(), classes="artifacts-pane-info")
        with VerticalScroll(classes="artifacts-placeholder-scroll"):
            yield Static(
                self._hero_text(),
                classes="artifacts-placeholder-hero",
            )
            card = Static(
                self._card_text(),
                classes="artifacts-placeholder-card",
            )
            card.border_title = "Coming soon"
            yield card
            yield Static(
                self._footer_text(),
                classes="artifacts-placeholder-footer",
            )

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Use configured scope-picker key text in the empty state."""
        self._registry = registry
        self._refresh_content()

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
    ) -> None:
        """Update the shared project scope chip without rebuilding the pane."""
        self.project_scope = project
        self._project_display_name = display_name
        self._refresh_content()

    def _refresh_content(self) -> None:
        if not self.is_mounted:
            return
        self.query_one(".artifacts-pane-info", Static).update(self._scope_text())
        self.query_one(".artifacts-placeholder-card", Static).update(self._card_text())
        self.query_one(".artifacts-placeholder-footer", Static).update(
            self._footer_text()
        )

    def _scope_label(self) -> str:
        if self.project_scope is not None:
            return self._project_display_name or self.project_scope
        if self.subtab == "commits":
            return "All projects"
        return "Pick a project"

    def _scope_text(self) -> Text:
        accent = ARTIFACTS_ACCENTS[self.subtab]
        text = Text()
        text.append(f" {self.subtab.title()} ", style=f"bold #1a1a1a on {accent}")
        text.append("  Project scope  ", style="dim")
        text.append(f" {self._scope_label()} ", style=f"bold {accent}")
        text.append("  ·  ", style="dim")
        text.append(
            f"{key_display_name(self._registry.app.pick_artifacts_project)} change",
            style="dim",
        )
        return text

    def _hero_text(self) -> Text:
        title, summary, _footer = _PLACEHOLDER_COPY[self.subtab]
        accent = ARTIFACTS_ACCENTS[self.subtab]
        text = Text(justify="center")
        text.append("*  ", style="bold #FFD700")
        text.append(title, style="bold #FFFFFF")
        text.append("  *\n", style="bold #FFD700")
        text.append(summary, style=f"dim {accent}")
        return text

    def _card_text(self) -> Text:
        accent = ARTIFACTS_ACCENTS[self.subtab]
        text = Text()
        text.append("Lazy by design\n", style=f"bold {accent}")
        text.append(
            "This pane stays mounted so selection and cached state will survive "
            "sub-tab switches. Its data lifecycle starts on first activation and "
            "pauses whenever the pane is hidden."
        )
        return text

    def _footer_text(self) -> Text:
        _title, _summary, footer = _PLACEHOLDER_COPY[self.subtab]
        return Text(footer, style="dim italic", justify="center")


__all__ = [
    "ArtifactPlaceholderPane",
    "ArtifactsPaneLifecycle",
    "ArtifactsPrsPane",
]

"""Pane widgets and lazy lifecycle seam for the Artifacts tab."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from ...keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ..._artifact_tab_model import ArtifactsPaneContract
from ..ancestors_children_panel import AncestorsChildrenPanel
from ..patch_detail import PatchDetail, SearchQueryPanel
from ..patch_info_panel import PatchInfoPanel
from ..patch_list import PatchList
from ..tab_quickstart import TabQuickStart
from .lifecycle import ArtifactsPaneLifecycle
from .entry_navigation import ArtifactEntryNavigator, ArtifactEntryTarget
from .patch_entry import patch_row_target
from .shell import build_degraded_card
from .types import ARTIFACTS_ACCENTS, ArtifactsSubTab


class ArtifactsPatchesPane(ArtifactEntryNavigator, ArtifactsPaneLifecycle, Horizontal):
    """The existing Patch surface, hosted unchanged inside Artifacts."""

    def __init__(
        self,
        *,
        contract: ArtifactsPaneContract | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._init_artifacts_lifecycle()
        self.contract = contract

    def compose(self) -> ComposeResult:
        with Vertical(id="list-container"):
            yield PatchInfoPanel(id="info-panel")
            yield PatchList(id="list-panel")
            yield AncestorsChildrenPanel(id="ancestors-children-panel")
        with Vertical(id="detail-container"):
            yield SearchQueryPanel(id="search-query-panel")
            with VerticalScroll(id="detail-scroll"):
                yield PatchDetail(id="detail-panel")
            yield TabQuickStart(
                tab="artifacts",
                id="patch-quickstart-panel",
                classes="hidden",
            )

    def on_activate(self) -> None:
        """Restore focus to the PR surface after another pane owned it."""
        if self.is_mounted:
            self.query_one("#list-panel", PatchList).focus()

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        app = cast(Any, self.app)
        return tuple(patch_row_target(patch) for patch in getattr(app, "patches", ()))

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        app = cast(Any, self.app)
        patches = getattr(app, "patches", ())
        idx = getattr(app, "current_idx", 0)
        if not patches or not 0 <= idx < len(patches):
            return None
        return patch_row_target(patches[idx])

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Resolve *target* against the current Patch list and focus it.

        Clears any active banner focus — selecting a concrete Patch row
        always wins over a collapsed group banner — and synchronously
        focuses the Patch list so the row is immediately interactive.
        """
        app = cast(Any, self.app)
        patches = getattr(app, "patches", ())
        for index, patch in enumerate(patches):
            if patch_row_target(patch) != target:
                continue
            app._current_patch_group_key = None
            app.current_idx = index
            if self.is_mounted:
                self.query_one("#list-panel", PatchList).focus()
            return True
        return False

    def request_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Select *target* now.

        Unlike the async-loaded non-PR panes, Patches are already loaded
        into app state by the time this pane can be queried, so there is
        no later row model to defer to — a miss here means the Patch is
        genuinely not in the current filtered list.
        """
        return self.select_entry_target(target)

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        # Patches paint their own adaptive jump hints through the
        # grouping-aware banner/row jump mode; this pane is never the
        # target of the shared non-PR jump-hint renderer.
        del hints

    def clear_entry_jump_hints(self) -> None:
        pass

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        del marks
        app = cast(Any, self.app)
        refresh = getattr(app, "_refresh_display", None)
        if callable(refresh):
            refresh()

    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        # Patches already drive their full conditional footer directly
        # from ``_apply_detail_panel_update``; this pane never feeds the
        # shared non-PR footer-entries renderer.
        return ()


_PLACEHOLDER_COPY: dict[ArtifactsSubTab, tuple[str, str, str]] = {
    "stitches": (
        "Stitches",
        "A cross-repository timeline with messages, tags, and diffs will live here.",
        "The Stitches pane is scaffolded and will load only when you open it.",
    ),
    "beads": (
        "Beads",
        "Task, epic, and phase bead work items will live here.",
        "The Beads pane will load only when you open it.",
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
        if subtab == "patches":
            raise ValueError("the Patches pane is not a placeholder")
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
        if self.subtab == "stitches":
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

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return ()

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        return None

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        del target
        return False

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        del hints

    def clear_entry_jump_hints(self) -> None:
        pass

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        del marks


class ArtifactsDegradedPane(ArtifactsPaneLifecycle, Vertical):
    """Visible failure state for a provider tab that could not be resolved."""

    def __init__(
        self,
        *,
        provider_kind: str,
        provider_label: str,
        error: str,
        error_code: str | None = None,
        error_source: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_kind = provider_kind
        self.provider_label = provider_label
        self.error = error
        self.error_code = error_code
        self.error_source = error_source
        self._init_artifacts_lifecycle()

    def compose(self) -> ComposeResult:
        hero_text, card_text = build_degraded_card(
            provider_kind=self.provider_kind,
            provider_label=self.provider_label,
            error=self.error,
            error_code=self.error_code,
            error_source=self.error_source,
        )
        hero = Static(hero_text, classes="artifacts-degraded-hero")
        card = Static(card_text, classes="artifacts-degraded-card")
        card.border_title = "Provider unavailable"
        yield hero
        yield card


__all__ = [
    "ArtifactPlaceholderPane",
    "ArtifactsDegradedPane",
    "ArtifactsPaneLifecycle",
    "ArtifactsPatchesPane",
]

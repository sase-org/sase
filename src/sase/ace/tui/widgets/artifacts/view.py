"""Top-level Artifacts view with provider-driven pane switching."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import ContentSwitcher

from ...keymaps import KeymapRegistry
from ...tab_order import ARTIFACTS_TAB
from ..panel_tab_strip import PanelTab, PanelTabStrip
from .beads_pane import ArtifactsBeadsPane
from .commits import CommitsPane
from .entry_navigation import ArtifactEntryNavigator
from .files_pane import ArtifactsFilesPane
from .lifecycle import ArtifactsPaneLifecycle
from .panes import ArtifactPlaceholderPane, ArtifactsPatchesPane
from .plans_pane import ArtifactsDocumentsPane, ArtifactsPlansPane
from .types import (
    ArtifactsPaneKey,
    ArtifactsSubTab,
    ArtifactsTabDescriptor,
    DEFAULT_ARTIFACTS_SUBTAB,
    descriptor_for_artifacts_subtab,
    normalize_artifacts_subtab,
    resolve_artifacts_subtabs,
)
from sase.vcs_log.filter_query import CommitLogFilterValues

if TYPE_CHECKING:
    from sase.project_display_names import ProjectRefDisplaySnapshot

    from ...app import AceApp


_DETAIL_SCROLL_IDS: dict[ArtifactsPaneKey, str] = {
    "stitches": "stitches-detail-scroll",
    "beads": "beads-detail-scroll",
    "files": "files-detail-scroll",
}


class ArtifactsView(Vertical):
    """Host fixed Artifacts panes and configured document providers."""

    def __init__(
        self,
        *,
        commits_default_filter: CommitLogFilterValues | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._descriptors = resolve_artifacts_subtabs()
        self._descriptor_by_id = {
            descriptor.id: descriptor for descriptor in self._descriptors
        }
        self._current_subtab: ArtifactsSubTab = normalize_artifacts_subtab(
            DEFAULT_ARTIFACTS_SUBTAB
        )
        self._commits_default_filter = commits_default_filter

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            self._panel_tabs(),
            self._current_subtab,
            show_numbers=True,
            uppercase_active=True,
            reflow_to_fit=True,
            id="artifacts-subtabs",
        )
        with ContentSwitcher(
            initial=self._pane_id(self._current_subtab),
            id="artifacts-content-switcher",
        ):
            for descriptor in self._descriptors:
                yield from self._compose_pane(descriptor)

    def on_mount(self) -> None:
        if getattr(self.app, "current_tab", None) == ARTIFACTS_TAB:
            self._pane(self._current_subtab).activate()

    @property
    def current_subtab(self) -> ArtifactsSubTab:
        return self._current_subtab

    @property
    def descriptors(self) -> tuple[ArtifactsTabDescriptor, ...]:
        return self._descriptors

    def _panel_tabs(self) -> tuple[PanelTab, ...]:
        return tuple(
            PanelTab(
                descriptor.id,
                descriptor.label,
                descriptor.accent,
                shortcut=descriptor.digit_shortcut,
                icon=descriptor.icon,
            )
            for descriptor in self._descriptors
        )

    def _compose_pane(self, descriptor: ArtifactsTabDescriptor) -> ComposeResult:
        if descriptor.id == "patches":
            yield ArtifactsPatchesPane(id=descriptor.pane_id)
        elif descriptor.id == "stitches":
            yield CommitsPane(
                initial_filters=self._commits_default_filter,
                id=descriptor.pane_id,
            )
        elif descriptor.id == "beads":
            yield ArtifactsBeadsPane(id=descriptor.pane_id)
        elif descriptor.id == "files":
            yield ArtifactsFilesPane(id=descriptor.pane_id)
        elif descriptor.provider_kind == "plan":
            yield ArtifactsPlansPane(
                provider_kind=descriptor.provider_kind,
                provider_label=descriptor.label,
                pane_key=descriptor.id,
                provider_spec=(
                    dict(descriptor.provider_spec)
                    if descriptor.provider_spec is not None
                    else None
                ),
                id=descriptor.pane_id,
                classes="artifacts-documents-pane",
            )
        elif descriptor.provider_kind is not None:
            yield ArtifactsDocumentsPane(
                provider_kind=descriptor.provider_kind,
                provider_label=descriptor.label,
                pane_key=descriptor.id,
                provider_spec=(
                    dict(descriptor.provider_spec)
                    if descriptor.provider_spec is not None
                    else None
                ),
                id=descriptor.pane_id,
                classes="artifacts-documents-pane",
            )

    def _pane_id(self, subtab: ArtifactsSubTab) -> str:
        descriptor = self._descriptor_by_id.get(normalize_artifacts_subtab(subtab))
        if descriptor is None:
            descriptor = descriptor_for_artifacts_subtab(DEFAULT_ARTIFACTS_SUBTAB)
        if descriptor is None:
            raise ValueError(f"Unknown Artifacts pane: {subtab!r}")
        return descriptor.pane_id

    def _pane(self, subtab: ArtifactsSubTab) -> ArtifactsPaneLifecycle:
        pane = self.query_one(f"#{self._pane_id(subtab)}")
        return cast(ArtifactsPaneLifecycle, pane)

    def entry_navigator(self, pane_key: ArtifactsPaneKey) -> ArtifactEntryNavigator:
        """Return the stable-target navigator for a non-PR pane."""

        normalized = normalize_artifacts_subtab(pane_key)
        if normalized == "patches":
            raise ValueError("Patches use the existing Patch navigation model")
        return cast(ArtifactEntryNavigator, self._pane(normalized))

    def detail_scroll(self, pane_key: ArtifactsPaneKey) -> VerticalScroll:
        """Return the right-hand detail viewport for a non-PR pane."""

        normalized = normalize_artifacts_subtab(pane_key)
        pane = cast(Any, self._pane(normalized))
        scroll_id = _DETAIL_SCROLL_IDS.get(normalized)
        if scroll_id is None and normalized.startswith("ref:"):
            scroll_id = "plans-detail-scroll"
        if scroll_id is None:
            raise ValueError("This pane has no Artifacts detail viewport")
        return pane.query_one(f"#{scroll_id}", VerticalScroll)

    def switch_to(self, subtab: ArtifactsSubTab) -> None:
        """Switch visible content and route active-pane lifecycle hooks."""

        subtab = normalize_artifacts_subtab(subtab)
        old_subtab = self._current_subtab
        if old_subtab == subtab:
            return
        artifacts_visible = getattr(self.app, "current_tab", None) == ARTIFACTS_TAB
        if artifacts_visible:
            self._pane(old_subtab).deactivate()
        self._current_subtab = subtab
        self.query_one(
            "#artifacts-content-switcher",
            ContentSwitcher,
        ).current = self._pane_id(subtab)
        self.query_one("#artifacts-subtabs", PanelTabStrip).set_active_tab(subtab)
        if artifacts_visible:
            self._pane(subtab).activate()

    def activate_current(self) -> None:
        self._pane(self._current_subtab).activate()

    def deactivate_current(self) -> None:
        self._pane(self._current_subtab).deactivate()

    def request_active_refresh(self) -> None:
        self._pane(self._current_subtab).request_refresh()

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Forward configured key display to project-backed panes."""

        for pane in self.query(ArtifactPlaceholderPane):
            pane.set_keymap_registry(registry)
        for pane_type in (
            ArtifactsBeadsPane,
            ArtifactsFilesPane,
            ArtifactsDocumentsPane,
            CommitsPane,
        ):
            for concrete_pane in self.query(pane_type):
                cast(Any, concrete_pane).set_keymap_registry(registry)

    def set_project_scope(
        self,
        project: str | None,
        *,
        display_name: str | None = None,
        project_file: str | None = None,
        update_commits: bool = True,
    ) -> None:
        """Apply the shared scope to every project-backed pane."""

        if update_commits:
            self.query_one(CommitsPane).set_project_scope(
                project,
                display_name=display_name,
                project_file=project_file,
            )
        for pane in self.query(ArtifactPlaceholderPane):
            pane.set_project_scope(project, display_name=display_name)
        for pane_type in (
            ArtifactsBeadsPane,
            ArtifactsFilesPane,
            ArtifactsDocumentsPane,
        ):
            for concrete_pane in self.query(pane_type):
                cast(Any, concrete_pane).set_project_scope(
                    project,
                    display_name=display_name,
                )

    def set_commits_project_sources(
        self,
        projects: tuple[str, ...],
        *,
        project_files: dict[str, str],
        project_ref_display: ProjectRefDisplaySnapshot,
    ) -> None:
        """Forward the already loaded inventory to project-backed renderers."""

        self.query_one(CommitsPane).set_project_completion_sources(
            projects,
            project_files=project_files,
            project_ref_display=project_ref_display,
        )
        for pane in self.query(ArtifactsFilesPane):
            pane.set_project_ref_display(project_ref_display)

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        if event.tab_id not in self._descriptor_by_id:
            return
        event.stop()
        cast("AceApp", self.app).current_artifacts_subtab = normalize_artifacts_subtab(
            event.tab_id
        )


__all__ = ["ArtifactsView"]

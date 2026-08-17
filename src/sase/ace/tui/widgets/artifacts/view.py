"""Top-level Artifacts view with provider-driven pane switching."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ContentSwitcher, Static

from ...artifact_tabs import artifacts_provider_diagnostics
from ...artifacts_split import (
    ARTIFACTS_SPLIT_CLASSES,
    DEFAULT_ARTIFACTS_SPLIT_MODE,
    ArtifactsSplitMode,
    cycle_artifacts_split_mode,
    normalize_artifacts_split_mode,
)
from ...keymaps import KeymapRegistry
from ...tab_order import ARTIFACTS_TAB
from ..panel_tab_strip import PanelTab, PanelTabStrip
from .beads_pane import ArtifactsBeadsPane
from .commits import CommitsPane
from .entry_navigation import ArtifactEntryNavigator
from .files_pane import ArtifactsFilesPane
from .lifecycle import ArtifactsPaneLifecycle
from .panes import ArtifactPlaceholderPane, ArtifactsDegradedPane, ArtifactsPatchesPane
from .plans_pane import ArtifactsDocumentsPane, ArtifactsPlansPane
from .relation_panel import RelationPanel
from .split_badge import ArtifactsSplitBadge
from .types import (
    ArtifactsPaneContract,
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
        self._split_mode: ArtifactsSplitMode = DEFAULT_ARTIFACTS_SPLIT_MODE
        self._commits_default_filter = commits_default_filter

    def compose(self) -> ComposeResult:
        with Horizontal(id="artifacts-header"):
            yield Static(id="artifacts-split-spacer")
            yield PanelTabStrip(
                self._panel_tabs(),
                self._current_subtab,
                show_numbers=True,
                uppercase_active=True,
                reflow_to_fit=True,
                id="artifacts-subtabs",
            )
            yield ArtifactsSplitBadge(id="artifacts-split-badge")
        with ContentSwitcher(
            initial=self._pane_id(self._current_subtab),
            id="artifacts-content-switcher",
        ):
            for descriptor in self._descriptors:
                yield from self._compose_pane(descriptor)

    def on_mount(self) -> None:
        self.apply_split_mode(cast("AceApp", self.app).artifacts_split_mode)
        self._refresh_provider_diagnostics()
        if getattr(self.app, "current_tab", None) == ARTIFACTS_TAB:
            self._pane(self._current_subtab).activate()

    @property
    def current_subtab(self) -> ArtifactsSubTab:
        return self._current_subtab

    @property
    def descriptors(self) -> tuple[ArtifactsTabDescriptor, ...]:
        return self._descriptors

    @property
    def active_contract(self) -> ArtifactsPaneContract | None:
        descriptor = self._descriptor_by_id.get(self._current_subtab)
        return None if descriptor is None else descriptor.contract

    @property
    def split_mode(self) -> ArtifactsSplitMode:
        return self._split_mode

    def apply_split_mode(self, mode: object) -> None:
        """Apply exactly one shared split class and refresh its badge."""

        normalized = normalize_artifacts_split_mode(mode)
        for candidate, class_name in ARTIFACTS_SPLIT_CLASSES.items():
            self.set_class(candidate == normalized, class_name)
        self._split_mode = normalized
        self._refresh_split_badge()

    def _refresh_split_badge(self) -> None:
        descriptor = self._descriptor_by_id[self._current_subtab]
        self.query_one("#artifacts-split-badge", ArtifactsSplitBadge).set_state(
            self._split_mode,
            descriptor.accent,
        )

    def _panel_tabs(self) -> tuple[PanelTab, ...]:
        return tuple(
            PanelTab(
                descriptor.id,
                descriptor.label,
                descriptor.accent,
                shortcut=descriptor.digit_shortcut,
                icon="⚠" if descriptor.is_degraded else descriptor.icon,
            )
            for descriptor in self._descriptors
        )

    def _refresh_provider_diagnostics(self) -> None:
        """Show a header warning when any provider tab is degraded."""

        degraded = artifacts_provider_diagnostics(self._descriptors)
        spacer = self.query_one("#artifacts-split-spacer", Static)
        if not degraded:
            spacer.update("")
            return
        spacer.update(Text("⚠", style="bold #FF5F5F", justify="center"))

    def _compose_pane(self, descriptor: ArtifactsTabDescriptor) -> ComposeResult:
        if descriptor.is_degraded:
            yield ArtifactsDegradedPane(
                provider_kind=descriptor.provider_kind or descriptor.id,
                provider_label=descriptor.label,
                error=descriptor.error or "Provider failed to load",
                error_code=descriptor.error_code,
                error_source=descriptor.error_source,
                id=descriptor.pane_id,
                classes="artifacts-degraded-pane",
            )
            return
        if descriptor.id == "patches":
            yield ArtifactsPatchesPane(
                contract=descriptor.contract,
                id=descriptor.pane_id,
            )
        elif descriptor.id == "stitches":
            yield CommitsPane(
                initial_filters=self._commits_default_filter,
                contract=descriptor.contract,
                id=descriptor.pane_id,
            )
        elif descriptor.id == "beads":
            yield ArtifactsBeadsPane(
                contract=descriptor.contract,
                id=descriptor.pane_id,
            )
        elif descriptor.id == "files":
            yield ArtifactsFilesPane(
                contract=descriptor.contract,
                id=descriptor.pane_id,
            )
        elif descriptor.provider_kind == "plan":
            yield ArtifactsPlansPane(
                contract=descriptor.contract,
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
                contract=descriptor.contract,
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
        """Return the stable-target navigator for any Artifacts pane."""

        normalized = normalize_artifacts_subtab(pane_key)
        return cast(ArtifactEntryNavigator, self._pane(normalized))

    def detail_scroll(self, pane_key: ArtifactsPaneKey) -> VerticalScroll:
        """Return the right-hand detail viewport for a non-PR pane."""

        normalized = normalize_artifacts_subtab(pane_key)
        pane = cast(Any, self._pane(normalized))
        descriptor = self._descriptor_by_id.get(normalized)
        contract = None if descriptor is None else descriptor.contract
        scroll_id = None if contract is None else contract.detail_scroll_id
        if scroll_id is None:
            scroll_id = _DETAIL_SCROLL_IDS.get(normalized)
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
        self._refresh_split_badge()
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

    @on(ArtifactsSplitBadge.Clicked)
    def _on_split_badge_clicked(self, event: ArtifactsSplitBadge.Clicked) -> None:
        event.stop()
        app = cast("AceApp", self.app)
        app.artifacts_split_mode = cycle_artifacts_split_mode(
            app.artifacts_split_mode,
            1,
        )

    @on(RelationPanel.Clicked)
    def _on_relation_panel_clicked(self, event: RelationPanel.Clicked) -> None:
        event.stop()
        cast("AceApp", self.app).action_toggle_relation_panel()


__all__ = ["ArtifactsView"]

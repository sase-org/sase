"""Composition and shared project-scope actions for the Artifacts tab."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sase.ace.query import get_sole_project_filter
from sase.ace.query.project_scope import (
    PROJECT_SCOPE_NESTED,
    project_scope_of,
    rewrite_project_scope,
)
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)

from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts import FIXED_ARTIFACTS_SUBTAB_ORDER
from .artifacts_beads import ArtifactsBeadsActionsMixin, BEADS_ARTIFACT_ACTIONS
from .artifacts_commits import (
    COMMITS_ARTIFACT_ACTIONS,
    ArtifactsCommitsActionsMixin,
)
from .artifacts_files import ArtifactsFilesActionsMixin, FILES_ARTIFACT_ACTIONS
from .artifacts_navigation import ArtifactsNavigationActionsMixin
from .artifacts_plans import ArtifactsPlansActionsMixin, PLANS_ARTIFACT_ACTIONS

if TYPE_CHECKING:
    from ..modals.inventory_project_picker import InventoryProjectChoice


# When a non-PR pane is active, the top-level internal id is still
# ``artifacts`` (``ARTIFACTS_TAB``); ``patches`` and ``changespecs`` are its
# legacy tab ids. This allowlist prevents historical PR bindings from acting
# on a hidden selection while retaining truly global actions and the scaffold's
# navigation/scope controls.
NON_PRS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        *COMMITS_ARTIFACT_ACTIONS,
        *BEADS_ARTIFACT_ACTIONS,
        *PLANS_ARTIFACT_ACTIONS,
        *FILES_ARTIFACT_ACTIONS,
        "copy_tab_content",
        "toggle_mark",
        "clear_marks",
        "cycle_artifacts_subtab",
        "cycle_artifacts_subtab_reverse",
        "cycle_artifacts_split",
        "cycle_artifacts_split_reverse",
        "files_next_version",
        "files_prev_version",
        "cycle_grouping_mode",
        "cycle_grouping_mode_reverse",
        "expand_or_layout",
        "hooks_or_collapse",
        "hooks_or_collapse_all",
        "expand_all_folds",
        "start_ancestor_mode",
        "start_child_mode",
        "start_sibling_mode",
        *{f"show_artifacts_{subtab}" for subtab in FIXED_ARTIFACTS_SUBTAB_ORDER},
        "show_artifacts_digit",
        "show_artifacts_bugs",
        "show_artifacts_prs",
        "pick_artifacts_project",
        "start_saved_query_mode",
        "scroll_to_top",
        "scroll_to_bottom",
        "scroll_detail_down",
        "scroll_detail_up",
        "scroll_prompt_down",
        "scroll_prompt_up",
        "jump_to_entry",
        "next_tab",
        "prev_tab",
        "quit",
        "stop_axe_and_quit",
        "start_custom_agent",
        "start_agent_from_patch",
        "start_agent_from_changespec",  # legacy compatibility alias
        "start_agent_home",
        "start_last_vcs_xprompt_in_editor",
        "restore_prompt_stash",
        "show_notifications",
        "show_help",
        "open_config_center",
        "open_models_panel",
        "open_command_palette",
        "dismiss_toasts",
        "refresh",
        "edit_query",
        "start_leader_mode",
    }
)


@dataclass(frozen=True)
class _ArtifactsProjectChoices:
    choices: tuple[InventoryProjectChoice, ...]
    enabled_projects: tuple[str, ...]
    display_names: dict[str, str]
    project_files: dict[str, str] = field(default_factory=dict)
    project_ref_display: ProjectRefDisplaySnapshot = field(
        default_factory=ProjectRefDisplaySnapshot
    )

    def __post_init__(self) -> None:
        if not self.project_ref_display.display_snapshot and self.display_names:
            object.__setattr__(
                self,
                "project_ref_display",
                ProjectRefDisplaySnapshot(
                    ProjectDisplaySnapshot(self.display_names),
                ),
            )

    @property
    def completion_display_names(self) -> tuple[str, ...]:
        """Return stable, deduplicated configured names for Stitches."""
        labels = (
            (choice.display_name for choice in self.choices)
            if self.choices
            else iter(self.display_names.values())
        )
        return tuple(dict.fromkeys(labels))

    @property
    def commits_project_files(self) -> dict[str, str]:
        """Return fetch metadata keyed by the visible Stitches project ref."""
        files: dict[str, str] = {}
        for project_key, project_file in self.project_files.items():
            label = self.display_names.get(project_key, project_key)
            files.setdefault(label, project_file)
        return files


def _collect_artifacts_project_choices() -> _ArtifactsProjectChoices:
    """Read project records for the picker; safe to run on a worker thread."""
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.core.project_lifecycle_wire import effective_project_name

    from ..modals.inventory_project_picker import InventoryProjectChoice

    records = list_project_records(
        sase_projects_dir(),
        "all",
        include_home=False,
        projects_only=True,
    )
    project_records = sorted(
        (
            record
            for record in records
            if record.is_project and not record.system_managed
        ),
        key=lambda record: (
            record.state == "disabled",
            effective_project_name(record).casefold(),
            record.project_name,
        ),
    )
    choices: list[InventoryProjectChoice] = []
    display_names: dict[str, str] = {}
    project_files: dict[str, str] = {}
    enabled: list[str] = []
    for record in project_records:
        display = effective_project_name(record)
        display_names[record.project_name] = display
        project_files[record.project_name] = record.project_file
        choices.append(
            InventoryProjectChoice(
                project_key=record.project_name,
                display_name=display,
                state=record.state,
            )
        )
        if record.state == "enabled":
            enabled.append(record.project_name)
    return _ArtifactsProjectChoices(
        choices=tuple(choices),
        enabled_projects=tuple(enabled),
        display_names=display_names,
        project_files=project_files,
        project_ref_display=ProjectRefDisplaySnapshot.from_records(project_records),
    )


class ArtifactsMixin(
    ArtifactsNavigationActionsMixin,
    ArtifactsCommitsActionsMixin,
    ArtifactsBeadsActionsMixin,
    ArtifactsPlansActionsMixin,
    ArtifactsFilesActionsMixin,
):
    """Compose Artifacts pane actions and manage their shared project scope."""

    parsed_query: Any
    query_string: str
    artifacts_project_scope: str | None
    _artifacts_project_choices: _ArtifactsProjectChoices | None
    _artifacts_project_choices_loading: bool
    _artifacts_project_picker_pending: bool
    _artifacts_scope_was_picked: bool

    def _resolve_initial_artifacts_scope(self) -> str | None:
        return get_sole_project_filter(self.parsed_query)

    def _set_artifacts_project_scope(
        self,
        project: str | None,
        *,
        picked: bool,
    ) -> None:
        self._cancel_non_pr_artifacts_jump_mode()
        if project != self.artifacts_project_scope:
            self._clear_all_artifacts_marks()
        self.artifacts_project_scope = project
        if picked:
            self._artifacts_scope_was_picked = True
        display_name = None
        project_file = None
        choices = self._artifacts_project_choices
        if project is not None and choices is not None:
            display_name = choices.display_names.get(project)
            project_file = choices.project_files.get(project)
        view = self._artifacts_view()
        if view is not None:
            commits = self._commits_pane()
            update_commits = bool(
                picked or commits is None or commits.filters.project is None
            )
            view.set_project_scope(
                project,
                display_name=display_name,
                project_file=project_file,
                update_commits=update_commits,
            )

    def _ensure_artifacts_project_choices(self) -> None:
        """Start one coalesced, off-thread project inventory read."""
        if self._artifacts_project_choices is not None:
            if self._artifacts_project_picker_pending:
                self._open_artifacts_project_picker()
            return
        if self._artifacts_project_choices_loading:
            return
        self._artifacts_project_choices_loading = True

        async def _runner() -> None:
            try:
                result = await asyncio.to_thread(_collect_artifacts_project_choices)
            except Exception as exc:
                self._artifacts_project_picker_pending = False
                self.notify(  # type: ignore[attr-defined]
                    f"Unable to load project scope: {exc}",
                    severity="error",
                )
                return
            finally:
                self._artifacts_project_choices_loading = False

            self._artifacts_project_choices = result
            view = self._artifacts_view()
            if view is not None:
                view.set_commits_project_sources(
                    result.completion_display_names,
                    project_files=result.commits_project_files,
                    project_ref_display=result.project_ref_display,
                )
            if (
                self.artifacts_project_scope is None
                and not self._artifacts_scope_was_picked
                and get_sole_project_filter(self.parsed_query) is None
                and len(result.enabled_projects) == 1
            ):
                self._set_artifacts_project_scope(
                    result.enabled_projects[0],
                    picked=False,
                )
            else:
                scope = self.artifacts_project_scope
                normalized = result.project_ref_display.project_key_for_ref(scope)
                self._set_artifacts_project_scope(
                    normalized or scope,
                    picked=False,
                )
            if self._artifacts_project_picker_pending:
                self._open_artifacts_project_picker()

        from ..util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            _runner(),
            name="sase-artifacts-project-choices",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._artifacts_project_choices_loading = False

    def _open_artifacts_project_picker(self) -> None:
        choices = self._artifacts_project_choices
        if choices is None:
            self._artifacts_project_picker_pending = True
            self._ensure_artifacts_project_choices()
            return
        self._artifacts_project_picker_pending = False

        from ..modals.inventory_project_picker import (
            InventoryProjectPicker,
            InventoryProjectPickerResult,
        )

        def _on_picked(result: InventoryProjectPickerResult | None) -> None:
            if result is None:
                return
            if self.current_artifacts_pane_key == "patches":
                project_ref = choices.project_ref_display.label_for_ref(
                    result.project_key
                )
                rewritten = rewrite_project_scope(self.query_string, project_ref)
                if rewritten == PROJECT_SCOPE_NESTED:
                    self.notify(  # type: ignore[attr-defined]
                        "Project scope is inside a grouped expression; "
                        "edit the query with <f>",
                        severity="warning",
                    )
                    return
                self._set_artifacts_project_scope(result.project_key, picked=True)
                self._commit_patch_query(rewritten)  # type: ignore[attr-defined]
                return
            self._set_artifacts_project_scope(result.project_key, picked=True)

        current_project = self.artifacts_project_scope
        if self.current_artifacts_pane_key == "patches":
            current_project = choices.project_ref_display.project_key_for_ref(
                project_scope_of(self.query_string)
            )
        if self.current_artifacts_pane_key == "stitches":
            pane = self._commits_pane()
            if pane is not None:
                current_project = choices.project_ref_display.project_key_for_ref(
                    pane.filters.project
                )
        self.push_screen(  # type: ignore[attr-defined]
            InventoryProjectPicker(
                list(choices.choices),
                current_project=current_project,
            ),
            _on_picked,
        )

    def action_pick_artifacts_project(self) -> None:
        """Open the shared project-scope picker for project-backed panes."""
        if self.current_tab != ARTIFACTS_TAB:
            return
        if self._artifacts_project_choices is None:
            self._artifacts_project_picker_pending = True
            self.notify(  # type: ignore[attr-defined]
                "Loading project scope…", timeout=1.5
            )
        self._open_artifacts_project_picker()

    def _request_active_artifacts_refresh(self) -> None:
        view = self._artifacts_view()
        if view is not None:
            view.request_active_refresh()


__all__ = [
    "ArtifactsMixin",
    "BEADS_ARTIFACT_ACTIONS",
    "COMMITS_ARTIFACT_ACTIONS",
    "NON_PRS_ARTIFACT_ACTIONS",
    "PLANS_ARTIFACT_ACTIONS",
    "_ArtifactsProjectChoices",
    "_collect_artifacts_project_choices",
]

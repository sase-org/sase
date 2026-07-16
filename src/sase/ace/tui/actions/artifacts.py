"""Navigation, scope, and lazy refresh actions for the Artifacts tab."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.ace.query import get_sole_project_filter

from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts import (
    ARTIFACTS_SUBTAB_ORDER,
    ArtifactsSubTab,
    ArtifactsView,
)

if TYPE_CHECKING:
    from ..modals.inventory_project_picker import InventoryProjectChoice


# When a non-PR pane is active, the top-level internal id is still
# ``changespecs``. This allowlist prevents historical PR bindings from acting
# on a hidden selection while retaining truly global actions and the scaffold's
# navigation/scope controls.
NON_PRS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "cycle_artifacts_subtab",
        "cycle_artifacts_subtab_reverse",
        "pick_artifacts_project",
        "next_tab",
        "prev_tab",
        "quit",
        "stop_axe_and_quit",
        "start_custom_agent",
        "start_agent_home",
        "start_last_vcs_xprompt_in_editor",
        "restore_prompt_stash",
        "show_notifications",
        "show_help",
        "open_config_center",
        "open_command_palette",
        "dismiss_toasts",
        "refresh",
    }
)


@dataclass(frozen=True)
class _ArtifactsProjectChoices:
    choices: tuple[InventoryProjectChoice, ...]
    enabled_projects: tuple[str, ...]
    display_names: dict[str, str]


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
    enabled: list[str] = []
    for record in project_records:
        display = effective_project_name(record)
        display_names[record.project_name] = display
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
    )


class ArtifactsMixin:
    """Actions shared by the Artifacts scaffold and future concrete panes."""

    current_tab: Any
    current_artifacts_subtab: ArtifactsSubTab
    parsed_query: Any
    artifacts_project_scope: str | None
    _artifacts_project_choices: _ArtifactsProjectChoices | None
    _artifacts_project_choices_loading: bool
    _artifacts_project_picker_pending: bool
    _artifacts_scope_was_picked: bool

    def _artifacts_view(self) -> ArtifactsView | None:
        try:
            return self.query_one("#changespecs-view", ArtifactsView)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _switch_artifacts_subtab(self, subtab: ArtifactsSubTab) -> None:
        if self.current_tab != ARTIFACTS_TAB:
            # Select while hidden so the top-level tab watcher activates only
            # the requested pane (and does not briefly refresh PRs first).
            self.current_artifacts_subtab = subtab
            self.current_tab = ARTIFACTS_TAB
            return
        self.current_artifacts_subtab = subtab

    def _cycle_artifacts_subtab(self, step: int) -> None:
        if self.current_tab != ARTIFACTS_TAB:
            return
        index = ARTIFACTS_SUBTAB_ORDER.index(self.current_artifacts_subtab)
        self.current_artifacts_subtab = ARTIFACTS_SUBTAB_ORDER[
            (index + step) % len(ARTIFACTS_SUBTAB_ORDER)
        ]

    def action_cycle_artifacts_subtab(self) -> None:
        """Move to the next Artifacts sub-tab with wraparound."""
        self._cycle_artifacts_subtab(1)

    def action_cycle_artifacts_subtab_reverse(self) -> None:
        """Move to the previous Artifacts sub-tab with wraparound."""
        self._cycle_artifacts_subtab(-1)

    def action_show_artifacts_prs(self) -> None:
        self._switch_artifacts_subtab("prs")

    def action_show_artifacts_commits(self) -> None:
        self._switch_artifacts_subtab("commits")

    def action_show_artifacts_bugs(self) -> None:
        self._switch_artifacts_subtab("bugs")

    def action_show_artifacts_plans(self) -> None:
        self._switch_artifacts_subtab("plans")

    def _resolve_initial_artifacts_scope(self) -> str | None:
        return get_sole_project_filter(self.parsed_query)

    def _set_artifacts_project_scope(
        self,
        project: str | None,
        *,
        picked: bool,
    ) -> None:
        self.artifacts_project_scope = project
        if picked:
            self._artifacts_scope_was_picked = True
        display_name = None
        choices = self._artifacts_project_choices
        if project is not None and choices is not None:
            display_name = choices.display_names.get(project)
        view = self._artifacts_view()
        if view is not None:
            view.set_project_scope(project, display_name=display_name)

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
                self._set_artifacts_project_scope(
                    self.artifacts_project_scope,
                    picked=False,
                )
            if self._artifacts_project_picker_pending:
                self._open_artifacts_project_picker()

        self.call_later(_runner)  # type: ignore[attr-defined]

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
            self._set_artifacts_project_scope(result.project_key, picked=True)

        self.push_screen(  # type: ignore[attr-defined]
            InventoryProjectPicker(
                list(choices.choices),
                current_project=self.artifacts_project_scope,
            ),
            _on_picked,
        )

    def action_pick_artifacts_project(self) -> None:
        """Open the shared project-scope picker for project-backed panes."""
        if self.current_tab != ARTIFACTS_TAB or self.current_artifacts_subtab == "prs":
            return
        if self._artifacts_project_choices is None:
            self._artifacts_project_picker_pending = True
            self.notify("Loading project scope…", timeout=1.5)  # type: ignore[attr-defined]
        self._open_artifacts_project_picker()

    def _request_active_artifacts_refresh(self) -> None:
        view = self._artifacts_view()
        if view is not None:
            view.request_active_refresh()


__all__ = [
    "ArtifactsMixin",
    "NON_PRS_ARTIFACT_ACTIONS",
    "_ArtifactsProjectChoices",
    "_collect_artifacts_project_choices",
]

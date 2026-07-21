"""Navigation, scope, and lazy refresh actions for the Artifacts tab."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from sase.ace.query import get_sole_project_filter

from ..tab_order import ARTIFACTS_TAB
from ..widgets.artifacts import (
    ARTIFACTS_SUBTAB_ORDER,
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    ArtifactsSubTab,
    ArtifactsView,
)
from .artifact_bugs import BUG_ARTIFACT_ACTIONS
from .artifacts_commits import (
    COMMITS_ARTIFACT_ACTIONS,
    ArtifactsCommitsActionsMixin,
)
from .artifacts_plans import ArtifactsPlansActionsMixin, PLANS_ARTIFACT_ACTIONS

if TYPE_CHECKING:
    from ..modals.inventory_project_picker import InventoryProjectChoice


# When a non-PR pane is active, the top-level internal id is still
# ``changespecs``. This allowlist prevents historical PR bindings from acting
# on a hidden selection while retaining truly global actions and the scaffold's
# navigation/scope controls.
NON_PRS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        *BUG_ARTIFACT_ACTIONS,
        *COMMITS_ARTIFACT_ACTIONS,
        *PLANS_ARTIFACT_ACTIONS,
        "cycle_artifacts_subtab",
        "cycle_artifacts_subtab_reverse",
        *{f"show_artifacts_{subtab}" for subtab in ARTIFACTS_SUBTAB_ORDER},
        "pick_artifacts_project",
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
        "start_agent_from_changespec",
        "start_agent_home",
        "start_last_vcs_xprompt_in_editor",
        "restore_prompt_stash",
        "show_notifications",
        "open_config_center",
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
    )


class ArtifactsMixin(ArtifactsCommitsActionsMixin, ArtifactsPlansActionsMixin):
    """Actions shared by the Artifacts scaffold and future concrete panes."""

    current_tab: Any
    current_artifacts_subtab: ArtifactsSubTab
    parsed_query: Any
    artifacts_project_scope: str | None
    _artifacts_project_choices: _ArtifactsProjectChoices | None
    _artifacts_project_choices_loading: bool
    _artifacts_project_picker_pending: bool
    _artifacts_scope_was_picked: bool
    _artifacts_jump_mode_subtab: ArtifactsSubTab | None
    _artifacts_jump_pending_prefix: str
    _artifacts_jump_hint_to_target: dict[str, ArtifactEntryTarget]
    _artifacts_jump_target_to_hint: dict[ArtifactEntryTarget, str]
    _artifacts_jump_history: dict[ArtifactsSubTab, ArtifactEntryTarget]

    def _artifacts_view(self) -> ArtifactsView | None:
        try:
            return self.query_one("#changespecs-view", ArtifactsView)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _non_pr_artifacts_active(self) -> bool:
        return self.current_tab == ARTIFACTS_TAB and self.current_artifacts_subtab in {
            "commits",
            "bugs",
            "plans",
        }

    def _sync_active_artifacts_entry_state(self) -> None:
        """Align footer and lazy scope setup with the visible Artifacts pane."""
        if self.current_tab != ARTIFACTS_TAB:
            return
        if self.current_artifacts_subtab == "prs":
            self._refresh_display()  # type: ignore[attr-defined]
            return

        self._ensure_artifacts_project_choices()
        from ..widgets import KeybindingFooter

        self.query_one(  # type: ignore[attr-defined]
            "#keybinding-footer", KeybindingFooter
        ).show_artifacts_pane()

    def _artifacts_entry_navigator(
        self,
        subtab: ArtifactsSubTab | None = None,
    ) -> ArtifactEntryNavigator | None:
        target_subtab = subtab or self.current_artifacts_subtab
        if target_subtab not in {"commits", "bugs", "plans"}:
            return None
        view = self._artifacts_view()
        if view is None:
            return None
        try:
            pane = view.entry_navigator(target_subtab)
        except Exception:
            return None
        return cast(ArtifactEntryNavigator, pane)

    def _navigate_non_pr_artifacts(
        self,
        *,
        action: str,
        offset: int | None = None,
        boundary: str | None = None,
    ) -> bool:
        """Route an existing global navigation action to the active entry list."""
        if not self._non_pr_artifacts_active():
            return False
        pane = self._artifacts_entry_navigator()
        if pane is None:
            return True
        from ..widgets.artifacts.entry_navigation import select_relative_entry

        self._begin_artifacts_navigation(action)
        try:
            select_relative_entry(pane, offset=offset, boundary=boundary)
        finally:
            self._finish_artifacts_navigation()
        return True

    def _scroll_non_pr_artifacts_detail(self, direction: int) -> bool:
        """Scroll only the active non-PR pane's right-hand detail viewport."""
        if not self._non_pr_artifacts_active():
            return False
        view = self._artifacts_view()
        if view is None:
            return True
        try:
            scroll = view.detail_scroll(self.current_artifacts_subtab)
        except Exception:
            return True
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=direction * (height // 2), animate=False)
        return True

    def _begin_non_pr_artifacts_jump_mode(self) -> bool:
        """Paint shared adaptive hints for the active non-PR Artifacts list."""
        if not self._non_pr_artifacts_active():
            return False
        pane = self._artifacts_entry_navigator()
        if pane is None:
            return True
        targets = list(pane.entry_targets())
        if not targets:
            return True
        from .navigation.jump_hints import build_jump_hint_maps

        hint_to_target, target_to_hint = build_jump_hint_maps(targets)
        self._artifacts_jump_hint_to_target = hint_to_target
        self._artifacts_jump_target_to_hint = target_to_hint
        self._artifacts_jump_pending_prefix = ""
        self._artifacts_jump_mode_subtab = self.current_artifacts_subtab
        self._entry_jump_mode_active = True  # type: ignore[attr-defined]
        pane.apply_entry_jump_hints(target_to_hint)
        self._update_jump_footer()  # type: ignore[attr-defined]
        return True

    def _valid_artifacts_jump_history(
        self,
        subtab: ArtifactsSubTab,
        pane: ArtifactEntryNavigator,
    ) -> ArtifactEntryTarget | None:
        target = self._artifacts_jump_history.get(subtab)
        if target is not None and target not in pane.entry_targets():
            self._artifacts_jump_history.pop(subtab, None)
            return None
        return target

    def _artifacts_jump_has_back(self) -> bool:
        subtab = self.current_artifacts_subtab
        pane = self._artifacts_entry_navigator(subtab)
        if pane is None:
            return False
        return self._valid_artifacts_jump_history(subtab, pane) is not None

    def _handle_non_pr_artifacts_jump_key(self, key: str) -> bool:
        """Dispatch one hint/back key without activating the selected entry."""
        subtab = self._artifacts_jump_mode_subtab
        if subtab is None:
            return False
        pane = self._artifacts_entry_navigator(subtab)
        if pane is None:
            self._cancel_non_pr_artifacts_jump_mode()
            return True
        if key == "escape":
            self._cancel_non_pr_artifacts_jump_mode()
            return True

        if key == "apostrophe":
            target = self._valid_artifacts_jump_history(subtab, pane)
            if target is None:
                target = next(iter(self._artifacts_jump_hint_to_target.values()), None)
        else:
            from .navigation.jump_hints import (
                JumpHintMatchOutcome,
                match_jump_hint,
            )

            match = match_jump_hint(
                self._artifacts_jump_hint_to_target,
                self._artifacts_jump_pending_prefix,
                key,
            )
            if match.outcome is JumpHintMatchOutcome.PENDING:
                self._artifacts_jump_pending_prefix = match.prefix
                return True
            if match.outcome is JumpHintMatchOutcome.INVALID:
                self._cancel_non_pr_artifacts_jump_mode()
                return True
            target = match.target
            self._artifacts_jump_pending_prefix = ""

        if target is None or target not in pane.entry_targets():
            self._cancel_non_pr_artifacts_jump_mode()
            return True
        origin = pane.selected_entry_target()
        if origin is not None and origin != target:
            self._artifacts_jump_history[subtab] = origin
        pane.select_entry_target(target)
        self._cancel_non_pr_artifacts_jump_mode()
        return True

    def _cancel_non_pr_artifacts_jump_mode(self) -> None:
        """Clear hints from their owning pane and restore the normal footer."""
        owner = self._artifacts_jump_mode_subtab
        if owner is not None:
            pane = self._artifacts_entry_navigator(owner)
            if pane is not None:
                pane.clear_entry_jump_hints()
        self._artifacts_jump_mode_subtab = None
        self._artifacts_jump_pending_prefix = ""
        self._artifacts_jump_hint_to_target = {}
        self._artifacts_jump_target_to_hint = {}
        if owner is not None:
            self._entry_jump_mode_active = False  # type: ignore[attr-defined]
        if self._non_pr_artifacts_active():
            from ..widgets import KeybindingFooter

            try:
                self.query_one(  # type: ignore[attr-defined]
                    "#keybinding-footer", KeybindingFooter
                ).show_artifacts_pane()
            except Exception:
                pass

    def _cancel_artifacts_jump_mode_for_model_change(
        self, subtab: ArtifactsSubTab
    ) -> None:
        """Cancel transient hints when their loaded row model is replaced."""
        if self._artifacts_jump_mode_subtab == subtab:
            self._cancel_non_pr_artifacts_jump_mode()

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

    def _begin_artifacts_navigation(self, direction: str) -> None:
        """Start activity-gate and key-to-paint tracking for a pane cursor."""
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            perf_begin(f"{self.current_artifacts_subtab}.{direction}")
        record_navigation = getattr(self, "_record_jk_navigation", None)
        if callable(record_navigation):
            record_navigation()

    def _finish_artifacts_navigation(self) -> None:
        """Finish key-to-paint tracking after a pane cursor has moved."""
        perf = getattr(self, "_jk_perf", None)
        if perf is None:
            return
        perf.mark_model_updated()
        self.call_after_refresh(perf.mark_painted)  # type: ignore[attr-defined]

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
        self._cancel_non_pr_artifacts_jump_mode()
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
            view.set_project_scope(
                project,
                display_name=display_name,
                project_file=project_file,
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
    "COMMITS_ARTIFACT_ACTIONS",
    "NON_PRS_ARTIFACT_ACTIONS",
    "PLANS_ARTIFACT_ACTIONS",
    "_ArtifactsProjectChoices",
    "_collect_artifacts_project_choices",
]

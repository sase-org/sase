"""Base action methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from sase.project_display_names import humanize_cl_name
from ..modals import WorkflowSelectModal
from ._admin_center_persistence import AdminCenterPersistenceMixin

if TYPE_CHECKING:
    from ...patch import Patch
    from ..commands import CommandTab
    from ..modals.config_center_modal import CenterTab

# Type alias for tab names (used in type hints)
TabName = Literal["artifacts", "agents", "axe"]


class BaseActionsMixin(AdminCenterPersistenceMixin):
    """Mixin providing workflow, tool, and query actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    query_string: str
    parsed_query: Any
    _last_admin_center_tab: CenterTab | None
    # --- Workflow Actions ---

    def action_run_workflow(self) -> None:
        """Run the contextual ``r`` action for the current tab."""
        # On axe tab, dispatch to re-run for done bgcmds or to manual chop run
        # for chop rows. Other rows (lumberjacks, running bgcmds) are no-ops.
        if self.current_tab == "axe":
            from ..widgets.bgcmd_list import BgCmdItem, ChopItem
            from ..bgcmd import is_slot_running

            items = getattr(self, "_axe_items", [])
            idx = self.current_idx
            if 0 <= idx < len(items):
                item = items[idx]
                if isinstance(item, BgCmdItem) and not is_slot_running(item.slot):
                    self._rerun_bgcmd(item.slot)  # type: ignore[attr-defined]
                elif isinstance(item, ChopItem):
                    self._run_selected_chop()  # type: ignore[attr-defined]
            return

        if self.current_tab == "agents":
            self._retry_edit_agent()  # type: ignore[attr-defined]
            return

        # Only run on patches tab
        if self.current_tab != "artifacts":
            return

        from ...operations import get_available_workflows

        if not self.patches:
            return

        patch = self.patches[self.current_idx]
        workflows = get_available_workflows(patch)

        if not workflows:
            self.notify("No workflows available", severity="warning")  # type: ignore[attr-defined]
            return

        if len(workflows) == 1:
            # Single workflow, run directly
            self._run_workflow(patch, 0)
        else:
            # Multiple workflows, show selection modal

            def on_dismiss(workflow_idx: int | None) -> None:
                if workflow_idx is not None:
                    self._run_workflow(patch, workflow_idx)

            self.push_screen(WorkflowSelectModal(workflows), on_dismiss)  # type: ignore[attr-defined]

    def _run_workflow(self, patch: Patch, workflow_index: int) -> None:
        """Run a specific workflow."""
        from ...handlers import handle_run_workflow
        from .._workflow_context import WorkflowContext

        def run_handler() -> tuple[list[Patch], int]:
            ctx = WorkflowContext()
            return handle_run_workflow(
                ctx,  # type: ignore[arg-type]
                patch,
                self.patches,
                self.current_idx,
                workflow_index,
            )

        with self.suspend():  # type: ignore[attr-defined]
            try:
                new_patches, new_idx = run_handler()
            except Exception as e:
                self.notify(f"Workflow error: {e}", severity="error")  # type: ignore[attr-defined]
                self._reload_and_reposition()  # type: ignore[attr-defined]
                return

        self._reload_and_reposition()  # type: ignore[attr-defined]

    # --- Tool Actions ---

    def action_open_projects_panel(self) -> None:
        """Open the SASE Admin Center on the Projects tab.

        Replaces the removed ``,p`` standalone project-management modal: the
        project lifecycle manager now lives in the Admin Center's Projects
        tab, so this fast path opens that modal pre-focused on Projects.
        """
        self._open_config_center("projects")

    def action_open_log_panel(self) -> None:
        """Open the SASE Admin Center on the Logs tab."""
        self._open_config_center("logs")

    def action_jump_to_last_error(self) -> None:
        """Open the Logs tab on this session's most recent registered error."""
        self._open_config_center("logs")

    def action_open_tasks_panel(self) -> None:
        """Open the SASE Admin Center on the Tasks tab."""
        self._open_config_center("procs")

    def action_open_statistics_panel(self) -> None:
        """Open the SASE Admin Center on the Statistics tab."""
        self._open_config_center("statistics")

    def action_open_updates_panel(self) -> None:
        """Open the SASE Admin Center on the Updates tab."""
        self._open_config_center("updates")

    def action_update_sase_shortcut(self) -> None:
        """Open Updates with a snapshot-gated comprehensive request."""
        # Keystroke dispatch copies only immutable in-memory state.  Provider
        # inventory, disk, network, and subprocess work begins in pane workers.
        provider_names = getattr(self, "_automatic_update_provider_names", None)
        self._open_config_center(
            "updates",
            auto_update=True,
            comprehensive_provider_names=provider_names,
        )

    def action_show_diff(self) -> None:
        """Show diff for the current Patch."""
        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        from ...handlers import handle_show_diff
        from .._workflow_context import WorkflowContext

        def run_handler() -> None:
            ctx = WorkflowContext()
            handle_show_diff(ctx, patch)  # type: ignore[arg-type]

        with self.suspend():  # type: ignore[attr-defined]
            run_handler()

    def action_reword(self) -> None:
        """Reword (change change description) for the current Patch.

        Two-phase approach:
        1. Interactive: fetch description and open editor in suspend()
        2. Background: claim workspace, checkout Patch branch, apply reword
        """
        from ...patch import get_base_status

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        # Validate PR is set
        if patch.pr_url is None:
            self.notify("PR is not set", severity="warning")  # type: ignore[attr-defined]
            return

        # Validate status is WIP, Draft, Ready, or Mailed
        base_status = get_base_status(patch.status)
        if base_status not in ("WIP", "Draft", "Ready", "Mailed"):
            self.notify(  # type: ignore[attr-defined]
                "Reword is only available for WIP, Draft, Ready, or Mailed Patches",
                severity="warning",
            )
            return

        from ...handlers import handle_reword_prepare
        from .._workflow_context import WorkflowContext
        from .patch_durable import submit_patch_operation
        from .proc_actions import TrackedProcCompletion

        # Interactive phase: fetch description and open editor in suspend()
        edited_description = None
        with self.suspend():  # type: ignore[attr-defined]
            ctx = WorkflowContext()
            edited_description = handle_reword_prepare(ctx, patch)  # type: ignore[arg-type]

        # If user cancelled or description unchanged, nothing to do
        if edited_description is None:
            return

        # Non-interactive phase: submit reword as a proc
        cl_name = patch.name
        display_cl_name = humanize_cl_name(cl_name)
        project_file = patch.file_path

        def on_complete(completion: TrackedProcCompletion[object]) -> None:
            if completion.collision or not completion.success:
                return
            from ...hooks import reset_dollar_hooks

            reset_dollar_hooks(project_file, cl_name)

        submitted = submit_patch_operation(
            self,
            verb="reword",
            name=cl_name,
            project_file=project_file,
            payload={"description": edited_description},
            on_complete=on_complete,
        )

        if submitted:
            self.notify(f"Rewording {display_cl_name}...")  # type: ignore[attr-defined]

    def action_add_tag(self) -> None:
        """Add a tag to the current Patch's change description in the background.

        This action:
        1. Validates PR is set and STATUS is editable
        2. Shows TagInputModal for tag name/value input
        3. Submits a proc that claims workspace, checks out Patch branch, adds tag
        4. Shows toast notifications for start/completion/failure
        """
        # On agents tab, dispatch to wait-for action
        if self.current_tab == "agents":
            self.action_wait_for_agent()  # type: ignore[attr-defined]
            return

        from ...patch import get_base_status
        from ...saved_tag_names import load_saved_tags, save_tag
        from ..modals import TagInputModal

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        # Validate PR is set
        if patch.pr_url is None:
            self.notify("PR is not set", severity="warning")  # type: ignore[attr-defined]
            return

        # Validate status is WIP, Draft, Ready, or Mailed
        base_status = get_base_status(patch.status)
        if base_status not in ("WIP", "Draft", "Ready", "Mailed"):
            self.notify(  # type: ignore[attr-defined]
                "Add tag is only available for WIP, Draft, Ready, or Mailed Patches",
                severity="warning",
            )
            return

        saved_tags = load_saved_tags()

        def on_dismiss(result: tuple[str, str] | None) -> None:
            if result is None:
                return

            tag_name, tag_value = result
            save_tag(tag_name, tag_value)

            from .patch_durable import submit_patch_operation
            from .proc_actions import TrackedProcCompletion

            cl_name = patch.name
            display_cl_name = humanize_cl_name(cl_name)
            project_file = patch.file_path

            def on_complete(completion: TrackedProcCompletion[object]) -> None:
                if completion.collision or not completion.success:
                    return
                from ...hooks import reset_dollar_hooks

                reset_dollar_hooks(project_file, cl_name)

            extra = [tag_name]
            if tag_value:
                extra.append(tag_value)
            submitted = submit_patch_operation(
                self,
                verb="tag",
                name=cl_name,
                project_file=project_file,
                extra_argv=tuple(extra),
                payload={"tag": tag_name, "value": tag_value},
                proc_type="add_tag",
                on_complete=on_complete,
            )

            if submitted:
                self.notify(  # type: ignore[attr-defined]
                    f"Adding tag {tag_name}={tag_value} to {display_cl_name}..."
                )

        self.push_screen(TagInputModal(saved_tags), on_dismiss)  # type: ignore[attr-defined]

    def action_mail(self) -> None:
        """Mail the current Patch in the background (post-confirmation).

        This action:
        1. Validates STATUS is "Ready"
        2. Claims workspace and gets workspace directory
        3. Runs interactive prepare_mail in suspend() (y/n prompt)
        4. If confirmed, submits execute_mail + status transition as a proc
        5. Shows toast notifications for start/completion/failure
        """
        import os

        from ...patch import get_base_status

        if not self.patches:
            return

        patch = self.patches[self.current_idx]

        if get_base_status(patch.status) != "Ready":
            self.notify("Patch must be Ready to mail", severity="warning")  # type: ignore[attr-defined]
            return

        from sase.running_field import (
            WorkspaceClaimError,
            claim_next_axe_workspace_dir,
            release_workspace,
        )

        from ...handlers import handle_mail_prepare
        from .._workflow_context import WorkflowContext
        from .patch_durable import submit_patch_operation

        cl_name = patch.name
        project_file = patch.file_path

        try:
            workspace_num, workspace_dir, _ = claim_next_axe_workspace_dir(
                project_file,
                "mail",
                os.getpid(),
                patch.project_basename,
                cl_name=cl_name,
            )
        except WorkspaceClaimError as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to claim workspace: {exc}",
                severity="error",
            )
            return

        # Interactive phase: checkout + prepare_mail (y/n prompt) in suspend()
        prep_result = None
        with self.suspend():  # type: ignore[attr-defined]
            ctx = WorkflowContext()
            prep_result = handle_mail_prepare(ctx, patch, workspace_dir)

        # If user declined or prepare failed, release workspace and return
        if prep_result is None or not prep_result.should_mail:
            release_workspace(project_file, workspace_num, "mail", cl_name)
            return

        submitted = submit_patch_operation(
            self,
            verb="mail",
            name=cl_name,
            project_file=project_file,
            payload={
                "settlement_owns_release": True,
                "workspace_dir": workspace_dir,
                "workspace_num": workspace_num,
            },
            workspace_num=workspace_num,
            workspace_workflow="mail",
        )

        if submitted:
            self.notify(f"Mailing {humanize_cl_name(cl_name)}...")  # type: ignore[attr-defined]
        else:
            # Dedup rejected — release workspace since the durable proc
            # was never reserved.
            release_workspace(project_file, workspace_num, "mail", cl_name)

    # --- Refresh & Query Actions ---

    def action_refresh(self) -> None:
        """Refresh the current tab's content."""
        if self.current_tab == "agents":
            # Route through the async path so the UI returns immediately.
            # _apply_loaded_agents triggers _refresh_agent_file after the
            # background load completes. Normal refresh is always the
            # visible-inbox Tier 1 path; full-history scans are exposed
            # through ``action_refresh_agents_full_history`` instead.
            self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                source="manual",
                full_history=False,
            )
        elif self.current_tab == "artifacts":
            if getattr(self, "current_artifacts_subtab", "patches") == "patches":
                self._schedule_patches_async_refresh()  # type: ignore[attr-defined]
            else:
                self._request_active_artifacts_refresh()  # type: ignore[attr-defined]
        else:  # axe
            # Targeted refresh repaints the focused panel first; the
            # full-fleet refresh lands whenever it lands.
            self._schedule_targeted_axe_refresh()  # type: ignore[attr-defined]
            self._schedule_axe_async_refresh()  # type: ignore[attr-defined]
        self.notify("Refreshed")  # type: ignore[attr-defined]

    def action_refresh_agents_full_history(self) -> None:
        """Explicitly refresh Agents from full artifact history."""
        if self.current_tab != "agents":
            self.notify("Full-history refresh is only available on Agents")  # type: ignore[attr-defined]
            return
        self._agents_history_reconcile_pending = False
        self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
            source="manual_full_history",
            full_history=True,
            full_history_reason="manual_full_history_refresh",
        )
        self.notify("Refreshing Agents from full history")  # type: ignore[attr-defined]

    def action_edit_query(self) -> None:
        """Edit the search query.

        On Agents and Artifacts entry panes, delegates to inline filters.

        Supports saving queries with # prefix:
        - #<N> <query> - Save query to slot N (0-9)
        - # <query> - Save query to next available slot
        - #<N> (no query) - Delete query from slot N
        """
        if self.current_tab == "agents":
            self._edit_agent_search_query()  # type: ignore[attr-defined]
            return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "patches"
        ):
            pane = self._artifacts_entry_navigator("patches")  # type: ignore[attr-defined]
            show_filters = getattr(pane, "show_filters", None)
            if callable(show_filters):
                show_filters()
            return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "stitches"
        ):
            pane = self._commits_pane()  # type: ignore[attr-defined]
            if pane is not None:
                pane.show_filters()
            return
        if self.current_tab == "artifacts":
            from ..artifact_tabs import PaneCapability, artifacts_pane_contract

            pane_key = str(getattr(self, "current_artifacts_pane_key", "patches"))
            contract = getattr(self, "active_artifacts_contract", None) or (
                artifacts_pane_contract(pane_key)
            )
            if (
                contract is not None
                and contract.is_document_provider()
                and contract.has(PaneCapability.FILTER_SESSION)
            ):
                pane = self._active_documents_pane()  # type: ignore[attr-defined]
                if pane is not None:
                    pane.show_filters()
                return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "beads"
        ):
            pane = self._beads_pane()  # type: ignore[attr-defined]
            if pane is not None:
                pane.show_filters()
            return
        if (
            self.current_tab == "artifacts"
            and getattr(self, "current_artifacts_pane_key", "patches") == "files"
        ):
            pane = self._files_pane()  # type: ignore[attr-defined]
            if pane is not None:
                pane.show_filters()
            return

    def action_open_config_center(self) -> None:
        """Open the SASE Admin Center on its lightweight home view."""
        self._open_config_center(None)

    def _open_config_center(
        self,
        initial_tab: Any,
        *,
        auto_update: bool = False,
        comprehensive_provider_names: tuple[str, ...] | None = None,
    ) -> None:
        """Open the SASE Admin Center and refresh updates state on dismiss."""
        from ..modals.config_center_modal import (
            ConfigCenterModal,
            validated_center_tab,
        )
        from ..modals.config_center_session import AdminCenterSessionState

        registry = getattr(self, "_keymap_registry", None)
        app_keymaps = getattr(registry, "app", None)
        opener_binding = getattr(app_keymaps, "open_config_center", "number_sign")
        resume_tab = validated_center_tab(getattr(self, "_last_admin_center_tab", None))
        history = getattr(self, "_admin_center_history", None)
        alternate_tab = validated_center_tab(
            history.alternate if history is not None else None
        )
        session_state = getattr(self, "_admin_center_session_state", None)
        if not isinstance(session_state, AdminCenterSessionState):
            session_state = AdminCenterSessionState()
            self._admin_center_session_state = session_state

        self.push_screen(  # type: ignore[attr-defined]
            ConfigCenterModal(
                initial_tab=initial_tab,
                resume_tab=resume_tab,
                alternate_tab=alternate_tab,
                opener_binding=opener_binding,
                auto_update=auto_update,
                comprehensive_provider_names=comprehensive_provider_names,
                session_state=session_state,
                on_tab_activated=self._on_admin_center_tab_activated,
            ),
            self._on_config_center_dismissed,
        )

    def _on_config_center_dismissed(self, result: object | None = None) -> None:
        from ..modals.config_center_modal import validated_center_tab

        active_tab = validated_center_tab(result)
        if active_tab is not None:
            # Successful activation normally records this before dismissal.
            # Keep the result as an idempotent fallback for narrow callers.
            self._remember_admin_center_tab(active_tab)
        refresh = getattr(self, "_schedule_updates_indicator_revalidation", None)
        if callable(refresh):
            refresh()

    def action_open_command_palette(self) -> None:
        """Open the context-aware command palette modal (bound to ``:``)."""
        from ..commands import (
            CommandPaletteResult,
            build_command_catalog,
            execute_command,
            extract_command_context,
            is_command_available,
        )
        from ..modals.command_palette_modal import CommandPaletteModal

        registry = self._keymap_registry  # type: ignore[attr-defined]
        ctx = extract_command_context(self)  # type: ignore[arg-type]
        catalog = build_command_catalog(registry)
        applicable = [s for s in catalog if is_command_available(s, ctx)]
        catalog_by_id = {s.id: s for s in catalog}

        def _on_dismiss(result: CommandPaletteResult | None) -> None:
            if result is None or result.selected_id is None:
                return
            spec = catalog_by_id.get(result.selected_id)
            if spec is None:
                return
            execute_command(self, spec)  # type: ignore[arg-type]

        self.push_screen(  # type: ignore[attr-defined]
            CommandPaletteModal(specs=applicable, tab=cast("CommandTab", ctx.tab)),
            callback=_on_dismiss,
        )

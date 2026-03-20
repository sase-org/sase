"""Base action methods for the ace TUI app."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from ...query import QueryParseError, parse_query, to_canonical_string
from ...saved_queries import (
    delete_query,
    find_slot_for_query,
    get_next_available_slot,
    load_saved_queries,
    save_query,
)
from ..modals import (
    QueryEditModal,
    WorkflowSelectModal,
)

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

# Type alias for tab names (used in type hints)
TabName = Literal["changespecs", "agents", "axe"]


class BaseActionsMixin:
    """Mixin providing workflow, tool, and query actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    query_string: str
    parsed_query: Any

    # --- Workflow Actions ---

    def action_run_workflow(self) -> None:
        """Run a workflow on the current ChangeSpec."""
        # On agents tab, dispatch to resume action
        if self.current_tab == "agents":
            self.action_resume_agent()  # type: ignore[attr-defined]
            return

        # Only run on changespecs tab
        if self.current_tab != "changespecs":
            return

        from ...operations import get_available_workflows

        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]
        workflows = get_available_workflows(changespec)

        if not workflows:
            self.notify("No workflows available", severity="warning")  # type: ignore[attr-defined]
            return

        if len(workflows) == 1:
            # Single workflow, run directly
            self._run_workflow(changespec, 0)
        else:
            # Multiple workflows, show selection modal

            def on_dismiss(workflow_idx: int | None) -> None:
                if workflow_idx is not None:
                    self._run_workflow(changespec, workflow_idx)

            self.push_screen(WorkflowSelectModal(workflows), on_dismiss)  # type: ignore[attr-defined]

    def _run_workflow(self, changespec: ChangeSpec, workflow_index: int) -> None:
        """Run a specific workflow."""
        from ...handlers import handle_run_workflow
        from .._workflow_context import WorkflowContext

        def run_handler() -> tuple[list[ChangeSpec], int]:
            ctx = WorkflowContext()
            return handle_run_workflow(
                ctx,  # type: ignore[arg-type]
                changespec,
                self.changespecs,
                self.current_idx,
                workflow_index,
            )

        with self.suspend():  # type: ignore[attr-defined]
            try:
                new_changespecs, new_idx = run_handler()
            except Exception as e:
                self.notify(f"Workflow error: {e}", severity="error")  # type: ignore[attr-defined]
                self._reload_and_reposition()  # type: ignore[attr-defined]
                return

        self._reload_and_reposition()  # type: ignore[attr-defined]

    # --- Tool Actions ---

    def action_show_diff(self) -> None:
        """Show diff for the current ChangeSpec."""
        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        from ...handlers import handle_show_diff
        from .._workflow_context import WorkflowContext

        def run_handler() -> None:
            ctx = WorkflowContext()
            handle_show_diff(ctx, changespec)  # type: ignore[arg-type]

        with self.suspend():  # type: ignore[attr-defined]
            run_handler()

    def action_reword(self) -> None:
        """Reword (change CL description) for the current ChangeSpec."""
        from ...changespec import get_base_status

        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        # Validate CL is set
        if changespec.cl is None:
            self.notify("CL is not set", severity="warning")  # type: ignore[attr-defined]
            return

        # Validate status is WIP, Draft, Ready, or Mailed
        base_status = get_base_status(changespec.status)
        if base_status not in ("WIP", "Draft", "Ready", "Mailed"):
            self.notify(  # type: ignore[attr-defined]
                "Reword is only available for WIP, Draft, Ready, or Mailed ChangeSpecs",
                severity="warning",
            )
            return

        from ...handlers import handle_reword
        from .._workflow_context import WorkflowContext

        def run_handler() -> None:
            ctx = WorkflowContext()
            handle_reword(ctx, changespec)  # type: ignore[arg-type]

        with self.suspend():  # type: ignore[attr-defined]
            run_handler()

        self._reload_and_reposition()  # type: ignore[attr-defined]

    def action_add_tag(self) -> None:
        """Add a tag to the current ChangeSpec's CL description in the background.

        This action:
        1. Validates CL is set and STATUS is editable
        2. Shows TagInputModal for tag name/value input
        3. Submits background task that claims workspace, checks out CL, adds tag
        4. Shows toast notifications for start/completion/failure
        """
        # On agents tab, dispatch to wait-for action
        if self.current_tab == "agents":
            self.action_wait_for_agent()  # type: ignore[attr-defined]
            return

        from ...changespec import get_base_status
        from ...saved_tag_names import load_saved_tags, save_tag
        from ..modals import TagInputModal

        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        # Validate CL is set
        if changespec.cl is None:
            self.notify("CL is not set", severity="warning")  # type: ignore[attr-defined]
            return

        # Validate status is WIP, Draft, Ready, or Mailed
        base_status = get_base_status(changespec.status)
        if base_status not in ("WIP", "Draft", "Ready", "Mailed"):
            self.notify(  # type: ignore[attr-defined]
                "Add tag is only available for WIP, Draft, Ready, or Mailed ChangeSpecs",
                severity="warning",
            )
            return

        saved_tags = load_saved_tags()

        def on_dismiss(result: tuple[str, str] | None) -> None:
            if result is None:
                return

            tag_name, tag_value = result
            save_tag(tag_name, tag_value)

            from ...handlers.reword import add_tag_task

            cl_name = changespec.name
            project_file = changespec.file_path

            def task_callable() -> tuple[bool, str]:
                return add_tag_task(
                    cl_name,
                    project_file,
                    changespec.project_basename,
                    tag_name,
                    tag_value,
                )

            def on_success() -> None:
                from ...hooks import reset_dollar_hooks

                reset_dollar_hooks(project_file, cl_name)

            submitted = self._submit_background_task(  # type: ignore[attr-defined]
                "add_tag", cl_name, project_file, task_callable, on_success=on_success
            )

            if submitted:
                self.notify(  # type: ignore[attr-defined]
                    f"Adding tag {tag_name}={tag_value} to {cl_name}..."
                )

        self.push_screen(TagInputModal(saved_tags), on_dismiss)  # type: ignore[attr-defined]

    def action_mail(self) -> None:
        """Mail the current ChangeSpec in the background (post-confirmation).

        This action:
        1. Validates STATUS is "Ready"
        2. Claims workspace and gets workspace directory
        3. Runs interactive prepare_mail in suspend() (y/n prompt)
        4. If confirmed, submits execute_mail + status transition as background task
        5. Shows toast notifications for start/completion/failure
        """
        import os

        from ...changespec import get_base_status

        if not self.changespecs:
            return

        changespec = self.changespecs[self.current_idx]

        if get_base_status(changespec.status) != "Ready":
            self.notify("ChangeSpec must be Ready to mail", severity="warning")  # type: ignore[attr-defined]
            return

        from sase.running_field import (
            claim_workspace,
            get_first_available_axe_workspace,
            get_workspace_directory_for_num,
            release_workspace,
        )

        from ...handlers import handle_mail_prepare
        from ...handlers.mail import mail_execute_task
        from .._workflow_context import WorkflowContext

        cl_name = changespec.name
        project_file = changespec.file_path

        # Claim workspace before suspend (needed for both prepare and execute)
        workspace_num = get_first_available_axe_workspace(project_file)

        if not claim_workspace(
            project_file, workspace_num, "mail", os.getpid(), cl_name
        ):
            self.notify("Failed to claim workspace", severity="error")  # type: ignore[attr-defined]
            return

        try:
            workspace_dir, _ = get_workspace_directory_for_num(
                workspace_num, changespec.project_basename
            )
        except RuntimeError as e:
            release_workspace(project_file, workspace_num, "mail", cl_name)
            self.notify(f"Failed to get workspace directory: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # Interactive phase: checkout + prepare_mail (y/n prompt) in suspend()
        prep_result = None
        with self.suspend():  # type: ignore[attr-defined]
            ctx = WorkflowContext()
            prep_result = handle_mail_prepare(ctx, changespec, workspace_dir)

        # If user declined or prepare failed, release workspace and return
        if prep_result is None or not prep_result.should_mail:
            release_workspace(project_file, workspace_num, "mail", cl_name)
            return

        # Non-interactive phase: submit execute_mail as background task
        # The background task owns the workspace from here and releases in finally
        def task_callable() -> tuple[bool, str]:
            return mail_execute_task(changespec, workspace_dir, workspace_num)

        submitted = self._submit_background_task(  # type: ignore[attr-defined]
            "mail", cl_name, project_file, task_callable
        )

        if submitted:
            self.notify(f"Mailing {cl_name}...")  # type: ignore[attr-defined]
        else:
            # Dedup rejected — release workspace since task won't run
            release_workspace(project_file, workspace_num, "mail", cl_name)

    # --- Refresh & Query Actions ---

    def action_refresh(self) -> None:
        """Refresh the current tab's content."""
        if self.current_tab == "agents":
            self._load_agents()  # type: ignore[attr-defined]
            self._refresh_agent_file()  # type: ignore[attr-defined]
        else:
            self._reload_and_reposition()  # type: ignore[attr-defined]
        self.notify("Refreshed")  # type: ignore[attr-defined]

    def action_edit_query(self) -> None:
        """Edit the search query.

        On the agents tab, delegates to the agent search filter.

        Supports saving queries with # prefix:
        - #<N> <query> - Save query to slot N (0-9)
        - # <query> - Save query to next available slot
        - #<N> (no query) - Delete query from slot N
        """
        if self.current_tab == "agents":
            self._edit_agent_search_query()  # type: ignore[attr-defined]
            return

        current_canonical = self.canonical_query_string  # type: ignore[attr-defined]

        def on_dismiss(new_query: str | None) -> None:
            if not new_query:
                return

            # Check for save prefix: #<N> or just #
            save_match = re.match(r"^#(\d)?(.*)$", new_query.strip())

            if save_match:
                slot_specified = save_match.group(1)
                query_part = save_match.group(2).strip()

                if not query_part:
                    # Delete mode: #<N> with no query
                    if slot_specified:
                        if delete_query(slot_specified):
                            self.notify(f"Deleted query from slot {slot_specified}")  # type: ignore[attr-defined]
                        else:
                            self.notify("Failed to delete query", severity="error")  # type: ignore[attr-defined]
                    else:
                        self.notify("No slot specified to delete", severity="warning")  # type: ignore[attr-defined]
                    return

                # Save mode: parse and save the query
                try:
                    parsed = parse_query(query_part)
                    canonical = to_canonical_string(parsed)
                except QueryParseError as e:
                    self.notify(f"Invalid query: {e}", severity="error")  # type: ignore[attr-defined]
                    return

                # Determine slot
                existing_slot = find_slot_for_query(canonical)
                if slot_specified:
                    slot = slot_specified
                else:
                    if existing_slot is not None:
                        self.notify(f"Query already saved in slot {existing_slot}")  # type: ignore[attr-defined]
                        return
                    queries = load_saved_queries()
                    slot = get_next_available_slot(queries)
                    if slot is None:
                        self.notify("All 10 slots are full", severity="warning")  # type: ignore[attr-defined]
                        return

                if save_query(slot, canonical):
                    if existing_slot is not None and existing_slot != slot:
                        self.notify(  # type: ignore[attr-defined]
                            f"Moved query from slot {existing_slot} to slot {slot}: {canonical}"
                        )
                    else:
                        self.notify(f"Saved to slot {slot}: {canonical}")  # type: ignore[attr-defined]
                else:
                    self.notify("Failed to save query", severity="error")  # type: ignore[attr-defined]
            else:
                # Normal query update (existing logic)
                from ...query_history import push_to_prev_stack, save_query_history

                try:
                    new_parsed = parse_query(new_query)
                    new_canonical = to_canonical_string(new_parsed)
                    # Only update if the canonical form changed
                    if new_canonical != current_canonical:
                        self._save_selection_for_current_query()  # type: ignore[attr-defined]
                        # Push current query to prev stack before changing
                        push_to_prev_stack(current_canonical, self._query_history)  # type: ignore[attr-defined]
                        save_query_history(self._query_history)  # type: ignore[attr-defined]

                        self.query_string = new_query
                        self.parsed_query = new_parsed
                        self._load_changespecs()  # type: ignore[attr-defined]
                        self._restore_selection_for_current_query()  # type: ignore[attr-defined]
                        self._save_current_query()  # type: ignore[attr-defined]
                        self.notify("Query updated")  # type: ignore[attr-defined]
                except QueryParseError as e:
                    self.notify(f"Invalid query: {e}", severity="error")  # type: ignore[attr-defined]

        self.push_screen(QueryEditModal(current_canonical), on_dismiss)  # type: ignore[attr-defined]

    def action_browse_xprompts(self) -> None:
        """Open the XPrompt browser modal."""
        from ..modals import XPromptBrowserModal

        self.push_screen(XPromptBrowserModal())  # type: ignore[attr-defined]

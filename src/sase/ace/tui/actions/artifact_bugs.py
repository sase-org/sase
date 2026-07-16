"""Actions for the tracker-backed Artifacts Bugs pane."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.artifacts_bugs import (
    BugSnapshot,
    collect_bug_snapshot,
    create_project_issue,
    issue_url,
    update_project_issue,
)
from sase.vcs_provider import IssueWire

from ..tab_order import ARTIFACTS_TAB
from ..util.pump_tasks import spawn_pump_free_task
from ..widgets.artifacts import ArtifactsBugsPane
from .task_actions import TrackedTaskCompletion, TrackedTaskResult

if TYPE_CHECKING:
    from ..modals.issue_edit_modal import IssueEditResult

BugLinkKind = Literal["epic", "pr"]

BUG_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "next_bug",
        "prev_bug",
        "cycle_bug_filter",
        "create_bug",
        "edit_bug",
        "toggle_bug_state",
        "open_bug",
        "copy_bug",
        "start_agent_from_bug",
        "focus_bug_links",
        "activate_bug_link",
        "refresh_bugs",
    }
)


class ArtifactBugsMixin:
    """App-level bindings and tracked tasks for the Bugs sub-tab."""

    current_tab: Any
    current_artifacts_subtab: str
    artifacts_project_scope: str | None
    artifacts_plan_target_bead_id: str | None
    changespecs: list[Any]
    current_idx: int

    if TYPE_CHECKING:

        def notify(
            self,
            message: str,
            *,
            title: str = "",
            severity: Literal["information", "warning", "error"] = "information",
            timeout: float | None = None,
            markup: bool = True,
        ) -> None: ...

    def _bugs_pane(self) -> ArtifactsBugsPane | None:
        try:
            return self.query_one("#artifacts-bugs-pane", ArtifactsBugsPane)  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None

    def _bugs_active(self) -> bool:
        return (
            self.current_tab == ARTIFACTS_TAB
            and self.current_artifacts_subtab == "bugs"
        )

    def action_next_bug(self) -> None:
        pane = self._bugs_pane()
        if self._bugs_active() and pane is not None:
            self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
            try:
                pane.move_selection(1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_prev_bug(self) -> None:
        pane = self._bugs_pane()
        if self._bugs_active() and pane is not None:
            self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
            try:
                pane.move_selection(-1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_cycle_bug_filter(self) -> None:
        pane = self._bugs_pane()
        if self._bugs_active() and pane is not None:
            pane.cycle_filter()

    def action_focus_bug_links(self) -> None:
        pane = self._bugs_pane()
        if self._bugs_active() and pane is not None:
            pane.focus_links()

    def action_activate_bug_link(self) -> None:
        pane = self._bugs_pane()
        if not self._bugs_active() or pane is None:
            return
        from ..widgets.artifacts import BugLinkList

        if isinstance(getattr(self, "focused", None), BugLinkList):
            pane.open_highlighted_link()
        else:
            pane.focus_links()

    def action_refresh_bugs(self) -> None:
        pane = self._bugs_pane()
        if not self._bugs_active() or pane is None:
            return
        project = pane.project_scope
        if project is None:
            self.notify("Pick a project before refreshing Bugs", severity="warning")  # type: ignore[attr-defined]
            return
        state_filter = pane.state_filter
        changespecs = tuple(self.changespecs)

        def _task() -> TrackedTaskResult[BugSnapshot]:
            snapshot = collect_bug_snapshot(project, state_filter, changespecs)
            if snapshot.error:
                return TrackedTaskResult(
                    False,
                    f"Unable to refresh issues: {snapshot.error}",
                    payload=snapshot,
                    error=snapshot.error,
                )
            return TrackedTaskResult(
                True,
                f"Refreshed {len(snapshot.issues)} issues",
                payload=snapshot,
            )

        def _complete(completion: TrackedTaskCompletion[BugSnapshot]) -> None:
            if completion.payload is not None and pane.project_scope == project:
                pane.accept_snapshot(completion.payload)

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "bugs-refresh",
            f"bugs-{project}",
            pane.project_file,
            _task,
            display_name=f"Refresh Bugs · {project}",
            dedup_key=f"bugs:{project}:refresh",
            duplicate_message="A Bugs refresh is already running",
            on_complete=_complete,
            reload_on_complete=False,
        )

    def action_create_bug(self) -> None:
        pane = self._bugs_pane()
        if not self._bugs_active() or pane is None:
            return
        if pane.project_scope is None:
            self.notify("Pick a project before creating an issue", severity="warning")  # type: ignore[attr-defined]
            return
        if not pane.snapshot.supported:
            self.notify(
                "This project does not have a tracker-capable provider",
                severity="warning",
            )  # type: ignore[attr-defined]
            return
        from ..modals import IssueEditModal

        self.push_screen(  # type: ignore[attr-defined]
            IssueEditModal(),
            lambda result: self._submit_bug_create(result) if result else None,
        )

    def _submit_bug_create(self, result: IssueEditResult) -> None:
        pane = self._bugs_pane()
        if pane is None or pane.project_scope is None:
            return
        project = pane.project_scope

        def _task() -> TrackedTaskResult[IssueWire]:
            issue = create_project_issue(
                project,
                title=result.title,
                body=result.body,
                labels=result.labels,
            )
            return TrackedTaskResult(
                True,
                f"Created issue #{issue.number}",
                payload=issue,
            )

        self._submit_bug_mutation(
            pane,
            task_type="bug-create",
            label="Create issue",
            dedup_key=f"bugs:{project}:create",
            task=_task,
        )

    def action_edit_bug(self) -> None:
        pane = self._bugs_pane()
        issue = pane.selected_issue if pane is not None else None
        if not self._bugs_active() or pane is None or issue is None:
            return
        from ..modals import IssueEditModal

        self.push_screen(  # type: ignore[attr-defined]
            IssueEditModal(issue),
            lambda result: self._submit_bug_edit(issue, result) if result else None,
        )

    def _submit_bug_edit(self, original: IssueWire, result: IssueEditResult) -> None:
        pane = self._bugs_pane()
        if pane is None or pane.project_scope is None:
            return
        project = pane.project_scope
        optimistic = replace(
            original,
            title=result.title,
            body=result.body,
            labels=result.labels,
        )
        pane.apply_issue(optimistic)

        def _task() -> TrackedTaskResult[IssueWire]:
            issue = update_project_issue(
                project,
                original.number,
                title=result.title,
                body=result.body,
                labels=result.labels,
            )
            return TrackedTaskResult(
                True,
                f"Updated issue #{issue.number}",
                payload=issue,
            )

        self._submit_bug_mutation(
            pane,
            task_type="bug-edit",
            label=f"Edit issue #{original.number}",
            dedup_key=f"bugs:{project}:{original.number}:update",
            task=_task,
            rollback=original,
        )

    def action_toggle_bug_state(self) -> None:
        pane = self._bugs_pane()
        issue = pane.selected_issue if pane is not None else None
        if not self._bugs_active() or pane is None or issue is None:
            return
        from ..modals import ConfirmActionModal, ConfirmKind

        target: Literal["open", "closed"] = (
            "closed" if issue.state == "open" else "open"
        )
        verb = "Close" if target == "closed" else "Reopen"

        def _confirmed(confirmed: bool) -> None:
            if confirmed:
                self._submit_bug_state_toggle(issue, target)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                f"{verb} Issue",
                f"{verb} issue #{issue.number}?",
                subject=issue.title,
                kind=ConfirmKind.DANGER if target == "closed" else ConfirmKind.NEUTRAL,
                confirm_label=verb,
            ),
            _confirmed,
        )

    def _submit_bug_state_toggle(
        self,
        original: IssueWire,
        target: Literal["open", "closed"],
    ) -> None:
        pane = self._bugs_pane()
        if pane is None or pane.project_scope is None:
            return
        project = pane.project_scope
        pane.apply_issue(replace(original, state=target))

        def _task() -> TrackedTaskResult[IssueWire]:
            issue = update_project_issue(
                project,
                original.number,
                state=target,
            )
            verb = "Closed" if target == "closed" else "Reopened"
            return TrackedTaskResult(
                True,
                f"{verb} issue #{issue.number}",
                payload=issue,
            )

        self._submit_bug_mutation(
            pane,
            task_type=f"bug-{target}",
            label=f"{target.title()} issue #{original.number}",
            dedup_key=f"bugs:{project}:{original.number}:update",
            task=_task,
            rollback=original,
        )

    def _submit_bug_mutation(
        self,
        pane: ArtifactsBugsPane,
        *,
        task_type: str,
        label: str,
        dedup_key: str,
        task: Any,
        rollback: IssueWire | None = None,
    ) -> None:
        project = pane.project_scope or "bugs"

        def _complete(completion: TrackedTaskCompletion[IssueWire]) -> None:
            if pane.project_scope != project:
                return
            if completion.success and completion.payload is not None:
                pane.apply_issue(completion.payload)
            elif rollback is not None:
                pane.apply_issue(rollback)

        submitted = self._submit_tracked_task(  # type: ignore[attr-defined]
            task_type,
            f"bug-{project}",
            pane.project_file,
            task,
            display_name=label,
            dedup_key=dedup_key,
            on_complete=_complete,
            reload_on_complete=False,
        )
        if submitted is None and rollback is not None:
            pane.apply_issue(rollback)

    def action_open_bug(self) -> None:
        pane = self._bugs_pane()
        issue = pane.selected_issue if pane is not None else None
        project = pane.project_scope if pane is not None else None
        if not self._bugs_active() or issue is None or project is None:
            return

        async def _open() -> None:
            import webbrowser

            try:
                url = await asyncio.to_thread(issue_url, project, issue)
                opened = await asyncio.to_thread(webbrowser.open, url)
            except Exception as exc:
                self.notify(f"Unable to open issue: {exc}", severity="error")  # type: ignore[attr-defined]
                return
            if not opened:
                self.notify("Browser did not accept the issue URL", severity="warning")  # type: ignore[attr-defined]

        spawn_pump_free_task(
            self,
            _open(),
            name="sase-bug-open",
            registry_attr="_pump_free_async_tasks",
        )

    def action_copy_bug(self) -> None:
        pane = self._bugs_pane()
        issue = pane.selected_issue if pane is not None else None
        project = pane.project_scope if pane is not None else None
        if not self._bugs_active() or issue is None or project is None:
            return

        async def _copy() -> None:
            from .clipboard import copy_to_system_clipboard

            try:
                url = await asyncio.to_thread(issue_url, project, issue)
                copied = await asyncio.to_thread(
                    copy_to_system_clipboard,
                    f"#{issue.number} {url}",
                )
            except Exception as exc:
                self.notify(f"Unable to copy issue: {exc}", severity="error")  # type: ignore[attr-defined]
                return
            self.notify(  # type: ignore[attr-defined]
                f"Copied issue #{issue.number}"
                if copied
                else "Copy failed — clipboard tool not available",
                severity="information" if copied else "error",
            )

        spawn_pump_free_task(
            self,
            _copy(),
            name="sase-bug-copy",
            registry_attr="_pump_free_async_tasks",
        )

    def action_start_agent_from_bug(self) -> None:
        pane = self._bugs_pane()
        issue = pane.selected_issue if pane is not None else None
        project = pane.project_scope if pane is not None else None
        if not self._bugs_active() or pane is None or issue is None or project is None:
            return
        project_file = pane.project_file
        if not project_file:
            self.notify(
                "The scoped project has no launchable ProjectSpec", severity="error"
            )  # type: ignore[attr-defined]
            return
        display_name = pane.snapshot.display_name or project

        async def _seed_prompt() -> None:
            from sase.workspace_provider import detect_workflow_type

            try:
                workflow_type = await asyncio.to_thread(
                    detect_workflow_type,
                    project_file,
                )
            except Exception as exc:
                self.notify(
                    f"Cannot start agent for issue #{issue.number}: {exc}",
                    severity="error",
                )  # type: ignore[attr-defined]
                return
            prefix = f"#{workflow_type}:{display_name} "
            prompt = _bug_agent_prompt(prefix, issue)
            self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                initial_text=prompt,
                display_name=f"{display_name} #{issue.number}",
                history_sort_key=project,
            )

        spawn_pump_free_task(
            self,
            _seed_prompt(),
            name="sase-bug-seed-agent-prompt",
            registry_attr="_pump_free_async_tasks",
        )

    def _open_bug_link(self, kind: BugLinkKind, target: str) -> None:
        if kind == "epic":
            self.artifacts_plan_target_bead_id = target
            self._switch_artifacts_subtab("plans")  # type: ignore[attr-defined]
            return
        index = next(
            (
                i
                for i, changespec in enumerate(self.changespecs)
                if changespec.name == target
            ),
            None,
        )
        if index is None:
            self.notify(
                f"Linked PR {target!r} is outside the current query", severity="warning"
            )  # type: ignore[attr-defined]
            return
        self.current_idx = index
        self._switch_artifacts_subtab("prs")  # type: ignore[attr-defined]


def _bug_agent_prompt(prefix: str, issue: IssueWire) -> str:
    body = issue.body.strip() or "(No issue body.)"
    return (
        f"{prefix}Work on external bug #{issue.number}: {issue.title}\n\n"
        f"Issue context:\n{body}\n\n"
        f"Keep bug_id: {issue.number} on any epic plan you create so its beads "
        "and resulting ChangeSpecs remain linked to this issue."
    )


__all__ = ["ArtifactBugsMixin", "BUG_ARTIFACT_ACTIONS"]

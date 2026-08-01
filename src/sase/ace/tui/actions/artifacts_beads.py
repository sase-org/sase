"""App actions and tracked mutations for the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from sase.bead.model import Issue, IssueType, Status

from ..widgets.artifacts.beads_data import BeadsSnapshot
from ..widgets.artifacts.beads_list import BeadRow
from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane

if TYPE_CHECKING:
    from ..modals.bead_close_modal import BeadCloseResult
    from ..modals.bead_create_modal import BeadCreateResult
    from ..modals.bead_editor_modal import BeadEditorResult


BEADS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "beads_next",
        "beads_prev",
        "beads_view_selected",
        "beads_filters",
        "beads_expand",
        "beads_collapse",
        "beads_cycle_status",
        "beads_edit",
        "beads_add_note",
        "beads_create",
        "beads_close",
        "beads_launch_work",
        "beads_open_bug",
        "beads_open_plan",
        "beads_refresh",
    }
)

T = TypeVar("T")


class ArtifactsBeadsActionsMixin:
    """Browse and mutate bead work items without blocking Textual's pump."""

    def _beads_pane(self) -> ArtifactsBeadsPane | None:
        try:
            return self.query_one(  # type: ignore[attr-defined]
                "#artifacts-beads-pane", ArtifactsBeadsPane
            )
        except Exception:
            return None

    def action_beads_next(self) -> None:
        pane = self._beads_pane()
        if pane is None:
            return
        self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
        try:
            pane.move_selection(1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_beads_prev(self) -> None:
        pane = self._beads_pane()
        if pane is None:
            return
        self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
        try:
            pane.move_selection(-1)
        finally:
            self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_beads_view_selected(self) -> None:
        pane = self._beads_pane()
        payload = None if pane is None else pane.selected_preview()
        if payload is None:
            return
        from ..modals.preview_panel_modal import PreviewPanelModal

        self.push_screen(PreviewPanelModal(payload))  # type: ignore[attr-defined]

    def action_beads_filters(self) -> None:
        if (pane := self._beads_pane()) is not None:
            show_filters = getattr(pane, "show_filters", None)
            if callable(show_filters):
                show_filters()

    def action_beads_expand(self) -> None:
        if (pane := self._beads_pane()) is not None:
            pane.set_selected_epic_expanded(True)

    def action_beads_collapse(self) -> None:
        if (pane := self._beads_pane()) is not None:
            pane.set_selected_epic_expanded(False)

    def action_beads_cycle_status(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        target = _next_bead_status(row.issue)
        settle_triage = (
            row.issue.issue_type is IssueType.TASK and target is Status.CLOSED
        )

        def mutate(project: Any) -> Issue:
            return project.update(row.issue.id, status=target.value)

        self._submit_bead_mutation(
            pane,
            row,
            operation="status",
            display_name=f"Set status · {row.issue.id}",
            success_message=f"Set {row.issue.id} to {target.value}",
            mutation=mutate,
            commit_operation="update",
            settle_triage_reason="closed_from_ace" if settle_triage else None,
        )

    def action_beads_edit(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        from ..modals.bead_editor_modal import BeadEditorModal, BeadEditorResult

        def dismissed(result: BeadEditorResult | None) -> None:
            if result is None:
                return
            fields = result.changed_fields(row.issue)
            if not fields:
                self.notify("No bead changes to save")  # type: ignore[attr-defined]
                return

            def mutate(project: Any) -> Issue:
                return project.update(row.issue.id, **fields)

            self._submit_bead_mutation(
                pane,
                row,
                operation="edit",
                display_name=f"Edit bead · {row.issue.id}",
                success_message=f"Updated {row.issue.id}",
                mutation=mutate,
                commit_operation="update",
                settle_triage_reason=(
                    "closed_from_ace"
                    if row.issue.issue_type is IssueType.TASK
                    and fields.get("status") == Status.CLOSED.value
                    else None
                ),
            )

        self.push_screen(BeadEditorModal(row.issue), dismissed)  # type: ignore[attr-defined]

    def action_beads_add_note(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        from ..modals.bead_note_modal import BeadNoteModal

        def dismissed(note: str | None) -> None:
            if note is None:
                return

            def mutate(project: Any) -> Issue:
                return project.append_note(
                    row.issue.id,
                    note,
                    author=_bead_note_author(project),
                )

            self._submit_bead_mutation(
                pane,
                row,
                operation="note",
                display_name=f"Add note · {row.issue.id}",
                success_message=f"Added note to {row.issue.id}",
                mutation=mutate,
                commit_operation="note",
            )

        self.push_screen(BeadNoteModal(row.issue.id), dismissed)  # type: ignore[attr-defined]

    def action_beads_create(self) -> None:
        pane = self._beads_pane()
        if pane is None:
            return
        project = pane.project_scope
        if project is None:
            self.notify(  # type: ignore[attr-defined]
                "Pick a project before creating a task bead", severity="warning"
            )
            return
        snapshot = pane.snapshot
        if snapshot is None or not snapshot.workspace_dirs.get(project):
            self.notify("The project workspace is unavailable", severity="warning")  # type: ignore[attr-defined]
            return
        from ..modals.bead_create_modal import BeadCreateModal, BeadCreateResult

        project_name = snapshot.display_names.get(project, project)

        def dismissed(result: BeadCreateResult | None) -> None:
            if result is not None:
                self._submit_bead_create(pane, project, result)

        self.push_screen(BeadCreateModal(project_name), dismissed)  # type: ignore[attr-defined]

    def _submit_bead_create(
        self,
        pane: ArtifactsBeadsPane,
        project: str,
        result: BeadCreateResult,
    ) -> None:
        snapshot = pane.snapshot
        workspace = None if snapshot is None else snapshot.workspace_dirs.get(project)
        if not workspace:
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[Issue]:
            from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
            from sase.bead.mutation_commit import require_mutation_commit_message

            with bead_store_mutation(
                auto_commit_bead_store, cwd=Path(workspace)
            ) as mutation:
                issue = mutation.project.create(
                    result.title,
                    IssueType.TASK,
                    description=result.description,
                    size=result.size,
                )
                if result.ready:
                    issue = mutation.project.update(issue.id, status=Status.READY.value)
                mutation.commit(require_mutation_commit_message("create", [issue.id]))
            return TrackedTaskResult(True, f"Created task bead {issue.id}", issue)

        self._submit_beads_task(  # type: ignore[attr-defined]
            pane,
            project=project,
            bead_id="new",
            operation="create",
            display_name="Create task bead",
            workspace=workspace,
            task=task,
        )

    def action_beads_close(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        if row.issue.status is Status.CLOSED:
            self._confirm_bead_reopen(pane, row)
            return
        from ..modals.bead_close_modal import BeadCloseModal, BeadCloseResult

        descendants = _unclosed_descendant_ids(row, pane.snapshot)

        def dismissed(result: BeadCloseResult | None) -> None:
            if result is not None:
                self._submit_bead_close(pane, row, result)

        self.push_screen(  # type: ignore[attr-defined]
            BeadCloseModal(row.issue, unclosed_descendants=descendants), dismissed
        )

    def _confirm_bead_reopen(self, pane: ArtifactsBeadsPane, row: BeadRow) -> None:
        from ..modals.confirm_action_modal import ConfirmActionModal

        def confirmed(value: bool) -> None:
            if not value:
                return

            def mutate(project: Any) -> Issue:
                issue, _ancestors = project.open(row.issue.id)
                return issue

            self._submit_bead_mutation(
                pane,
                row,
                operation="open",
                display_name=f"Reopen bead · {row.issue.id}",
                success_message=f"Reopened {row.issue.id} and any closed ancestors",
                mutation=mutate,
                commit_operation="open",
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Reopen bead",
                "Reopen this bead? Any closed ancestors above it will also reopen.",
                subject=f"{row.issue.id} · {row.issue.title}",
                confirm_label="Reopen",
            ),
            confirmed,
        )

    def _submit_bead_close(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        result: BeadCloseResult,
    ) -> None:
        def mutate(project: Any) -> Issue:
            project.close(
                [row.issue.id],
                reason=result.reason,
                resolution=result.resolution,
                force=result.force,
                note=result.note,
                author=_bead_note_author(project) if result.note else None,
            )
            return project.show(row.issue.id)

        self._submit_bead_mutation(
            pane,
            row,
            operation="close",
            display_name=f"Close bead · {row.issue.id}",
            success_message=f"Closed {row.issue.id}",
            mutation=mutate,
            commit_operation="close",
            settle_triage_reason=(
                "closed_from_ace" if row.issue.issue_type is IssueType.TASK else None
            ),
        )

    def action_beads_launch_work(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        issue = row.issue
        if issue.issue_type is IssueType.PHASE:
            self.notify("Phases launch with their epic", severity="warning")  # type: ignore[attr-defined]
            return
        if issue.status is Status.CLOSED:
            self.notify("Closed beads cannot be launched", severity="warning")  # type: ignore[attr-defined]
            return
        if issue.issue_type is IssueType.TASK:
            if issue.status not in {Status.OPEN, Status.READY}:
                self.notify(  # type: ignore[attr-defined]
                    "Only open or ready task beads can be launched",
                    severity="warning",
                )
                return
            self._submit_task_bead_launch(pane, row)
            return
        snapshot = pane.snapshot
        key = (row.project, issue.id)
        if snapshot is None or not snapshot.phases_by_epic.get(key):
            self.notify("This epic has no phase beads to launch", severity="warning")  # type: ignore[attr-defined]
            return
        if key in snapshot.blocked_ids:
            self._notify_beads(
                "This epic is blocked by an unresolved dependency", severity="warning"
            )
            return
        from ..modals.confirm_action_modal import ConfirmActionModal

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Launch epic work",
                "Launch all ready phase agents through the bead-work workflow?",
                subject=f"{issue.id} · {issue.title}",
                confirm_label="Launch",
            ),
            lambda confirmed: (
                self._submit_epic_bead_launch(pane, row) if confirmed else None
            ),
        )

    def _submit_task_bead_launch(self, pane: ArtifactsBeadsPane, row: BeadRow) -> None:
        snapshot = pane.snapshot
        workspace = (
            None if snapshot is None else snapshot.workspace_dirs.get(row.project)
        )
        if not workspace:
            self.notify("The project workspace is unavailable", severity="warning")  # type: ignore[attr-defined]
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[str]:
            from sase.bead.task_gate import cancel_task_triage
            from sase.bead.task_launch import submit_task_launch_for_project

            launched = submit_task_launch_for_project(
                row.project, row.issue.id, origin="ace"
            )
            cancel_task_triage(
                row.project,
                row.issue.id,
                reason="launched_from_ace",
            )
            return TrackedTaskResult(
                True,
                f"Submitted work for {row.issue.id}",
                str(launched.task_id),
            )

        self._submit_beads_task(  # type: ignore[attr-defined]
            pane,
            project=row.project,
            bead_id=row.issue.id,
            operation="launch",
            display_name=f"Launch task · {row.issue.id}",
            workspace=workspace,
            task=task,
            refresh_notifications=True,
        )

    def _submit_epic_bead_launch(self, pane: ArtifactsBeadsPane, row: BeadRow) -> None:
        snapshot = pane.snapshot
        workspace = (
            None if snapshot is None else snapshot.workspace_dirs.get(row.project)
        )
        beads_dir = None if snapshot is None else snapshot.beads_dirs.get(row.project)
        if not workspace or not beads_dir:
            self.notify("The project bead store is unavailable", severity="warning")  # type: ignore[attr-defined]
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[bool]:
            launched = _launch_scoped_epic(Path(beads_dir), row.issue.id)
            return TrackedTaskResult(
                True,
                (
                    f"Launched phase agents for {row.issue.id}"
                    if launched
                    else f"No phase agents needed launching for {row.issue.id}"
                ),
                launched,
            )

        self._submit_beads_task(  # type: ignore[attr-defined]
            pane,
            project=row.project,
            bead_id=row.issue.id,
            operation="launch",
            display_name=f"Launch epic · {row.issue.id}",
            workspace=workspace,
            task=task,
        )

    def action_beads_open_bug(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        snapshot = pane.snapshot
        issue = _epic_for_bead_row(row, snapshot)
        if issue is None or not issue.changespec_bug_id:
            self.notify("The selected epic has no external bug", severity="warning")  # type: ignore[attr-defined]
            return
        workspace = (
            None if snapshot is None else snapshot.workspace_dirs.get(row.project)
        )
        if not workspace:
            self._notify_beads(
                "The selected project workspace is unavailable", severity="warning"
            )
            return
        bug_id = issue.changespec_bug_id.lstrip("#")
        if not bug_id.isdigit():
            self._notify_beads(
                f"Bug id is not a numeric tracker issue: {bug_id}", severity="warning"
            )
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[str]:
            url = _resolve_issue_url(workspace, int(bug_id))
            return TrackedTaskResult(True, f"Resolved bug #{bug_id}", url)

        def completed(completion: Any) -> None:
            if completion.success and completion.payload:
                self.open_url(completion.payload)  # type: ignore[attr-defined]

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "open bug",
            issue.id,
            workspace,
            task,
            display_name=f"Open bug #{bug_id}",
            dedup_key=f"beads:bug:{row.project}:{bug_id}",
            on_complete=completed,
            reload_on_complete=False,
        )

    def action_beads_open_plan(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        snapshot = pane.snapshot
        plan_path = (
            ""
            if snapshot is None
            else snapshot.plan_links.get((row.project, row.issue.id), "")
        )
        if not plan_path:
            self.notify("This bead links no plan file", severity="warning")  # type: ignore[attr-defined]
            return
        plan_kind = "archive" if row.issue.status is Status.CLOSED else "active"
        self._request_artifacts_entry(  # type: ignore[attr-defined]
            "plans",
            ("plan", row.project, plan_kind, plan_path),
        )

    def action_beads_refresh(self) -> None:
        if (pane := self._beads_pane()) is not None:
            pane.request_refresh()

    def _selected_bead(self) -> tuple[ArtifactsBeadsPane, BeadRow] | None:
        pane = self._beads_pane()
        row = None if pane is None else pane.selected_row()
        if pane is None or row is None:
            self.notify("Select a bead first", severity="warning")  # type: ignore[attr-defined]
            return None
        return pane, row

    def _notify_beads(self, message: str, *, severity: str = "information") -> None:
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify(message, severity=severity)

    def _submit_bead_mutation(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        *,
        operation: str,
        display_name: str,
        success_message: str,
        mutation: Callable[[Any], T],
        commit_operation: str,
        settle_triage_reason: str | None = None,
    ) -> None:
        snapshot = pane.snapshot
        workspace = (
            None if snapshot is None else snapshot.workspace_dirs.get(row.project)
        )
        if not workspace:
            self.notify("The project workspace is unavailable", severity="warning")  # type: ignore[attr-defined]
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[T]:
            from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
            from sase.bead.mutation_commit import (
                close_mutation_commit_message,
                require_mutation_commit_message,
            )

            with bead_store_mutation(
                auto_commit_bead_store, cwd=Path(workspace)
            ) as store_mutation:
                payload = mutation(store_mutation.project)
                outcome = store_mutation.project.last_mutation_outcome
                if commit_operation == "close":
                    commit_message = close_mutation_commit_message(
                        closed_ids=_outcome_ids(outcome, "closed_ids"),
                        cascade_closed_ids=_outcome_ids(outcome, "cascade_closed_ids"),
                        noted_ids=_outcome_ids(outcome, "noted_ids"),
                    )
                    if commit_message is not None:
                        store_mutation.commit(commit_message)
                else:
                    changed_ids = _outcome_ids(outcome, "issue_ids")
                    if not changed_ids and store_mutation.project.mutation_changed:
                        changed_ids = [row.issue.id]
                    if changed_ids:
                        store_mutation.commit(
                            require_mutation_commit_message(
                                commit_operation, changed_ids
                            )
                        )
            if settle_triage_reason is not None:
                from sase.bead.task_gate import cancel_task_triage

                cancel_task_triage(
                    row.project,
                    row.issue.id,
                    reason=settle_triage_reason,
                )
            return TrackedTaskResult(True, success_message, payload)

        self._submit_beads_task(  # type: ignore[attr-defined]
            pane,
            project=row.project,
            bead_id=row.issue.id,
            operation=operation,
            display_name=display_name,
            workspace=workspace,
            task=task,
            refresh_notifications=settle_triage_reason is not None,
        )

    def _submit_beads_task(
        self,
        pane: ArtifactsBeadsPane,
        *,
        project: str,
        bead_id: str,
        operation: str,
        display_name: str,
        workspace: str,
        task: Callable[..., Any],
        refresh_notifications: bool = False,
    ) -> None:
        def completed(_completion: Any) -> None:
            pane.request_refresh()
            if refresh_notifications:
                refresh = getattr(self, "_refresh_notification_count", None)
                if callable(refresh):
                    refresh()

        self._submit_tracked_task(  # type: ignore[attr-defined]
            f"bead-{operation}",
            bead_id,
            workspace,
            task,
            display_name=display_name,
            dedup_key=f"beads:{operation}:{project}:{bead_id}",
            duplicate_message=f"A {operation} task is already running for {bead_id}",
            on_complete=completed,
            reload_on_complete=False,
        )


def _next_bead_status(issue: Issue) -> Status:
    """Return the type-aware status cycle used by the Beads pane."""
    if issue.issue_type is IssueType.TASK:
        return {
            Status.OPEN: Status.READY,
            Status.CLAIMED: Status.READY,
            Status.READY: Status.IN_PROGRESS,
            Status.IN_PROGRESS: Status.CLOSED,
            Status.CLOSED: Status.OPEN,
        }[issue.status]
    return {
        Status.OPEN: Status.IN_PROGRESS,
        Status.CLAIMED: Status.IN_PROGRESS,
        Status.READY: Status.IN_PROGRESS,
        Status.IN_PROGRESS: Status.CLOSED,
        Status.CLOSED: Status.OPEN,
    }[issue.status]


def _outcome_ids(outcome: Mapping[str, object], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]


def _bead_note_author(project: Any) -> str:
    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity()
    return identity.name if identity is not None else project.owner


def _unclosed_descendant_ids(
    row: BeadRow,
    snapshot: BeadsSnapshot | None,
) -> tuple[str, ...]:
    if snapshot is None:
        return ()
    issues = [item.issue for item in (*snapshot.tasks, *snapshot.epics)]
    issues.extend(
        item.issue for phases in snapshot.phases_by_epic.values() for item in phases
    )
    children: dict[str, list[Issue]] = {}
    for issue in issues:
        if issue.parent_id:
            children.setdefault(issue.parent_id, []).append(issue)
    result: list[str] = []
    pending = list(children.get(row.issue.id, ()))
    while pending:
        issue = pending.pop(0)
        if issue.status is not Status.CLOSED:
            result.append(issue.id)
        pending.extend(children.get(issue.id, ()))
    return tuple(result)


def _epic_for_bead_row(
    row: BeadRow,
    snapshot: BeadsSnapshot | None,
) -> Issue | None:
    if row.kind == "epic":
        return row.issue
    if row.issue.parent_id is None or snapshot is None:
        return None
    return next(
        (
            epic.issue
            for epic in snapshot.epics
            if epic.project == row.project and epic.issue.id == row.issue.parent_id
        ),
        None,
    )


def _launch_scoped_epic(beads_dir: Path, epic_id: str) -> bool:
    from sase.bead.cli_work_from_plan_store import epic_plan_launch_lock
    from sase.bead.cli_work_handler import launch_epic_bead_work
    from sase.bead.project import BeadProject

    with epic_plan_launch_lock(beads_dir.parent):
        with BeadProject(beads_dir.parent, beads_dirname=beads_dir.name) as project:
            return launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                no_push=False,
                yes_to_all=True,
            )


def _resolve_issue_url(workspace_dir: str, bug_id: int) -> str:
    from sase.vcs_provider import get_vcs_provider, supports_issues

    if not supports_issues(workspace_dir):
        raise NotImplementedError(
            "The scoped project's VCS provider does not support issues"
        )
    return get_vcs_provider(workspace_dir).get_issue_url(bug_id, workspace_dir)


__all__ = [
    "ArtifactsBeadsActionsMixin",
    "BEADS_ARTIFACT_ACTIONS",
    "_next_bead_status",
    "_resolve_issue_url",
    "_unclosed_descendant_ids",
]

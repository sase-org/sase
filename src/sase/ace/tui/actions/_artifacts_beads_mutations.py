"""Mutation actions for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.model import Issue, IssueType, Status

from ..widgets.artifacts.beads_list import BeadRow
from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane
from ._artifacts_beads_common import (
    ArtifactsBeadsCommonMixin,
    bead_note_author,
    next_bead_status,
    unclosed_descendant_ids,
)

if TYPE_CHECKING:
    from ..modals.bead_close_modal import BeadCloseResult
    from ..modals.bead_create_modal import BeadCreateResult
    from ..modals.bead_snooze_modal import BeadSnoozeChoice


# Only a task bead has a snooze, and the store accepts one only from these
# statuses. Checking here keeps the refusal in the modal-less fast path: a
# claimed or in-progress task never opens a picker it cannot act on.
_SNOOZABLE_STATUSES = frozenset({Status.OPEN, Status.READY, Status.SNOOZED})


class ArtifactsBeadsMutationActionsMixin(ArtifactsBeadsCommonMixin):
    def action_beads_cycle_status(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        target = next_bead_status(row.issue)
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
                    author=bead_note_author(project),
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

    def action_beads_snooze(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        issue = row.issue
        if issue.issue_type is not IssueType.TASK:
            self._notify_beads("Only task beads can be snoozed", severity="warning")
            return
        if issue.status not in _SNOOZABLE_STATUSES:
            self._notify_beads(
                "Only open, ready, and already snoozed task beads can be snoozed",
                severity="warning",
            )
            return
        from ..modals.bead_snooze_modal import BeadSnoozeModal

        def dismissed(choice: BeadSnoozeChoice | None) -> None:
            if choice is not None:
                self._submit_bead_snooze(pane, row, choice)

        self.push_screen(BeadSnoozeModal(issue), dismissed)  # type: ignore[attr-defined]

    def _submit_bead_snooze(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        choice: BeadSnoozeChoice,
    ) -> None:
        from ..modals.bead_snooze_modal import BeadSnoozeRequest

        if not isinstance(choice, BeadSnoozeRequest):
            self._submit_bead_cancel_snooze(pane, row)
            return
        request = choice

        def mutate(project: Any) -> Issue:
            return project.snooze(
                row.issue.id,
                until=request.until,
                actor=bead_note_author(project),
                plus_ones=request.plus_ones,
                reason=request.reason,
            )

        self._submit_bead_mutation(
            pane,
            row,
            operation="snooze",
            display_name=f"Snooze bead · {row.issue.id}",
            success_message=f"Snoozed {row.issue.id}",
            mutation=mutate,
            commit_operation="snooze",
            # A ready task carries a pending TaskTriage gate, and the point of
            # snoozing is to stop being asked. Settling it here rather than
            # waiting for the reconciler's next tick means the answer is
            # immediate; the reconciler still owns raising the snooze gate.
            settle_triage_reason="bead_status_changed",
        )

    def _submit_bead_cancel_snooze(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
    ) -> None:
        def mutate(project: Any) -> Issue:
            return project.cancel_snooze(row.issue.id, actor=bead_note_author(project))

        self._submit_bead_mutation(
            pane,
            row,
            operation="snooze-cancel",
            display_name=f"Wake bead · {row.issue.id}",
            success_message=f"Woke {row.issue.id} and returned it to triage",
            mutation=mutate,
            commit_operation="snooze_cancel",
        )

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
            self.notify(  # type: ignore[attr-defined]
                "The project workspace is unavailable", severity="warning"
            )
            return
        from ..modals.bead_create_modal import BeadCreateModal, BeadCreateResult

        project_name = snapshot.display_names.get(project, project)

        def dismissed(result: BeadCreateResult | None) -> None:
            if result is not None:
                self._submit_bead_create(pane, project, result)

        self.push_screen(  # type: ignore[attr-defined]
            BeadCreateModal(project_name), dismissed
        )

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

        self._submit_beads_task(
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

        descendants = unclosed_descendant_ids(row, pane.snapshot)

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
                author=bead_note_author(project) if result.note else None,
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

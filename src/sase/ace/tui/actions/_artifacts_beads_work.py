"""Work-launch and external-link actions for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import IssueType, Status

from ..widgets.artifacts.beads_list import BeadRow
from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane
from ._artifacts_beads_common import (
    ArtifactsBeadsCommonMixin,
    epic_for_bead_row,
)


class ArtifactsBeadsWorkActionsMixin(ArtifactsBeadsCommonMixin):
    def action_beads_launch_work(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        issue = row.issue
        if issue.issue_type is IssueType.PHASE:
            self.notify(  # type: ignore[attr-defined]
                "Phases launch with their epic", severity="warning"
            )
            return
        if issue.status is Status.CLOSED:
            self.notify(  # type: ignore[attr-defined]
                "Closed beads cannot be launched", severity="warning"
            )
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
            self.notify(  # type: ignore[attr-defined]
                "This epic has no phase beads to launch", severity="warning"
            )
            return
        if key in snapshot.blocked_ids:
            self._notify_beads(
                "This epic is blocked by an unresolved dependency",
                severity="warning",
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
            self.notify(  # type: ignore[attr-defined]
                "The project workspace is unavailable", severity="warning"
            )
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

        self._submit_beads_task(
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
            self.notify(  # type: ignore[attr-defined]
                "The project bead store is unavailable", severity="warning"
            )
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[bool]:
            from .artifacts_beads import _launch_scoped_epic

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

        self._submit_beads_task(
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
        issue = epic_for_bead_row(row, snapshot)
        if issue is None or not issue.patch_bug_id:
            self.notify(  # type: ignore[attr-defined]
                "The selected epic has no external bug", severity="warning"
            )
            return
        workspace = (
            None if snapshot is None else snapshot.workspace_dirs.get(row.project)
        )
        if not workspace:
            self._notify_beads(
                "The selected project workspace is unavailable", severity="warning"
            )
            return
        bug_id = issue.patch_bug_id.lstrip("#")
        if not bug_id.isdigit():
            self._notify_beads(
                f"Bug id is not a numeric tracker issue: {bug_id}",
                severity="warning",
            )
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[str]:
            from .artifacts_beads import _resolve_issue_url

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

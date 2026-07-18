"""App actions and tracked tasks for the Artifacts Plans pane."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.model import Issue, Status
from sase.bead.project import BeadProject

from ..widgets.artifacts.plans_pane import ArtifactsPlansPane, PlanRow

if TYPE_CHECKING:
    from ..modals.bead_edit_modal import BeadEditResult


PLANS_ARTIFACT_ACTIONS: frozenset[str] = frozenset(
    {
        "plans_next",
        "plans_prev",
        "plans_view_selected",
        "plans_filters",
        "plans_expand",
        "plans_collapse",
        "plans_cycle_status",
        "plans_edit_bead",
        "plans_launch_epic",
        "plans_approve",
        "plans_reject",
        "plans_open_bug",
        "plans_refresh",
    }
)


class ArtifactsPlansActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` without expanding app.py."""

    def _plans_pane(self) -> ArtifactsPlansPane | None:
        try:
            return self.query_one("#artifacts-plans-pane", ArtifactsPlansPane)  # type: ignore[attr-defined]
        except Exception:
            return None

    def action_plans_next(self) -> None:
        pane = self._plans_pane()
        if pane is not None:
            self._begin_artifacts_navigation("next")  # type: ignore[attr-defined]
            try:
                pane.move_selection(1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_plans_prev(self) -> None:
        pane = self._plans_pane()
        if pane is not None:
            self._begin_artifacts_navigation("prev")  # type: ignore[attr-defined]
            try:
                pane.move_selection(-1)
            finally:
                self._finish_artifacts_navigation()  # type: ignore[attr-defined]

    def action_plans_filters(self) -> None:
        pane = self._plans_pane()
        if pane is not None:
            pane.show_filters()

    def action_plans_expand(self) -> None:
        pane = self._plans_pane()
        if pane is not None:
            pane.set_selected_epic_expanded(True)

    def action_plans_collapse(self) -> None:
        pane = self._plans_pane()
        if pane is not None:
            pane.set_selected_epic_expanded(False)

    def action_plans_view_selected(self) -> None:
        pane = self._plans_pane()
        payload = None if pane is None else pane.selected_preview()
        if payload is None:
            return
        from ..modals.preview_panel_modal import PreviewPanelModal

        self.push_screen(PreviewPanelModal(payload))  # type: ignore[attr-defined]

    def action_plans_refresh(self) -> None:
        pane = self._plans_pane()
        if pane is not None:
            pane.request_refresh()

    def action_plans_approve(self) -> None:
        self._open_selected_plan_approval(intent="approve")

    def action_plans_reject(self) -> None:
        self._open_selected_plan_approval(intent="reject")

    def _open_selected_plan_approval(self, *, intent: str) -> None:
        pane = self._plans_pane()
        row = None if pane is None else pane.selected_row()
        if row is None or row.proposal is None:
            self.notify("Select a pending plan proposal first", severity="warning")  # type: ignore[attr-defined]
            return
        from .agents._notification_modals import handle_plan_approval

        opened = handle_plan_approval(self, row.proposal.notification)
        if opened and intent == "reject":
            self.notify("Review the plan, then press r to confirm rejection")  # type: ignore[attr-defined]

    def action_plans_cycle_status(self) -> None:
        pane, row = self._selected_bead_row()
        if pane is None or row is None or row.issue is None:
            return
        issue = row.issue
        next_status = {
            Status.OPEN: Status.IN_PROGRESS,
            Status.IN_PROGRESS: Status.CLOSED,
            Status.CLOSED: Status.OPEN,
        }[issue.status]
        self._submit_plans_bead_update(
            pane,
            row.project,
            issue,
            fields={"status": next_status.value},
            task_type="bead status",
            message=f"Set {issue.id} to {next_status.value}",
        )

    def action_plans_edit_bead(self) -> None:
        pane, row = self._selected_bead_row()
        if pane is None or row is None or row.issue is None:
            return
        issue = row.issue
        from ..modals.bead_edit_modal import BeadEditModal, BeadEditResult

        def on_dismiss(result: BeadEditResult | None) -> None:
            if result is None:
                return
            fields: dict[str, str] = {}
            if result.title != issue.title:
                fields["title"] = result.title
            if result.description != issue.description:
                fields["description"] = result.description
            if not fields:
                self.notify("No bead changes to save")  # type: ignore[attr-defined]
                return
            self._submit_plans_bead_update(
                pane,
                row.project,
                issue,
                fields=fields,
                task_type="edit bead",
                message=f"Updated {issue.id}",
            )

        self.push_screen(  # type: ignore[attr-defined]
            BeadEditModal(issue.id, issue.title, issue.description),
            on_dismiss,
        )

    def action_plans_launch_epic(self) -> None:
        pane = self._plans_pane()
        row = None if pane is None else pane.selected_row()
        if pane is None or row is None or row.kind != "epic" or row.issue is None:
            self.notify("Select an epic bead to launch work", severity="warning")  # type: ignore[attr-defined]
            return
        snapshot = pane.snapshot
        issue = row.issue
        if snapshot is None or issue.status == Status.CLOSED:
            self.notify("Closed epics cannot be launched", severity="warning")  # type: ignore[attr-defined]
            return
        issue_key = (row.project, issue.id)
        if issue_key in snapshot.blocked_ids:
            self.notify(  # type: ignore[attr-defined]
                "This epic is blocked by an unresolved dependency", severity="warning"
            )
            return
        if not snapshot.phases_by_epic.get(issue_key):
            self.notify("This epic has no phase beads to launch", severity="warning")  # type: ignore[attr-defined]
            return

        from ..modals.confirm_action_modal import ConfirmActionModal

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            self._submit_plans_epic_launch(pane, row.project, issue)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Launch epic work",
                "Launch all ready phase agents through the existing bead-work workflow?",
                subject=f"{issue.id} · {issue.title}",
                confirm_label="Launch",
                cancel_label="Cancel",
            ),
            on_confirm,
        )

    def action_plans_open_bug(self) -> None:
        pane = self._plans_pane()
        row = None if pane is None else pane.selected_row()
        snapshot = None if pane is None else pane.snapshot
        issue = _epic_for_row(row, snapshot)
        if issue is None or not issue.changespec_bug_id:
            self.notify("The selected epic has no external bug", severity="warning")  # type: ignore[attr-defined]
            return
        project = None if row is None else row.project
        workspace_dir = (
            None
            if snapshot is None or project is None
            else snapshot.workspace_dirs.get(project)
        )
        if project is None or not workspace_dir:
            self.notify(  # type: ignore[attr-defined]
                "The selected row's project workspace is unavailable",
                severity="warning",
            )
            return
        bug_id = issue.changespec_bug_id.lstrip("#")
        if not bug_id.isdigit():
            self.notify(  # type: ignore[attr-defined]
                f"Bug id is not a numeric tracker issue: {bug_id}", severity="warning"
            )
            return

        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[str]:
            url = _resolve_issue_url(workspace_dir, int(bug_id))
            return TrackedTaskResult(
                success=True,
                message=f"Resolved bug #{bug_id}",
                payload=url,
            )

        def on_complete(completion: Any) -> None:
            if completion.success and completion.payload:
                self.open_url(completion.payload)  # type: ignore[attr-defined]

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "open bug",
            issue.id,
            workspace_dir,
            task,
            display_name=f"Open bug #{bug_id}",
            dedup_key=f"plans:bug:{project}:{bug_id}",
            on_complete=on_complete,
            reload_on_complete=False,
        )

    def _selected_bead_row(
        self,
    ) -> tuple[ArtifactsPlansPane | None, PlanRow | None]:
        pane = self._plans_pane()
        row = None if pane is None else pane.selected_row()
        if row is None or row.issue is None:
            self.notify("Select an epic or phase bead first", severity="warning")  # type: ignore[attr-defined]
            return pane, None
        return pane, row

    def _submit_plans_bead_update(
        self,
        pane: ArtifactsPlansPane,
        project: str,
        issue: Issue,
        *,
        fields: dict[str, str],
        task_type: str,
        message: str,
    ) -> None:
        snapshot = pane.snapshot
        if snapshot is None:
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[Issue]:
            updated = _update_scoped_bead(project, issue.id, fields)
            return TrackedTaskResult(
                success=True,
                message=message,
                payload=updated,
            )

        self._submit_tracked_task(  # type: ignore[attr-defined]
            task_type,
            issue.id,
            snapshot.workspace_dirs.get(project) or project,
            task,
            display_name=f"{task_type.title()} · {issue.id}",
            dedup_key=f"plans:bead:{project}:{issue.id}",
            duplicate_message=f"A bead task is already running for {issue.id}",
            on_complete=lambda completion: self._refresh_plans_after_task(
                completion.success
            ),
            reload_on_complete=False,
        )

    def _submit_plans_epic_launch(
        self,
        pane: ArtifactsPlansPane,
        project: str,
        issue: Issue,
    ) -> None:
        snapshot = pane.snapshot
        if snapshot is None:
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[bool]:
            launched = _launch_scoped_epic(project, issue.id)
            return TrackedTaskResult(
                success=True,
                message=(
                    f"Launched phase agents for {issue.id}"
                    if launched
                    else f"No phase agents needed launching for {issue.id}"
                ),
                payload=launched,
            )

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "launch epic",
            issue.id,
            snapshot.workspace_dirs.get(project) or project,
            task,
            display_name=f"Launch epic · {issue.id}",
            dedup_key=f"plans:launch:{project}:{issue.id}",
            duplicate_message=f"Epic work is already launching for {issue.id}",
            on_complete=lambda completion: self._refresh_plans_after_task(
                completion.success
            ),
            reload_on_complete=False,
        )

    def _refresh_plans_after_task(self, succeeded: bool) -> None:
        if not succeeded:
            return
        pane = self._plans_pane()
        if pane is not None:
            pane.request_refresh()


def _project_beads_dir(project: str) -> Path:
    from sase.bead.workspace import get_project_beads_dirs_for_project

    directories = get_project_beads_dirs_for_project(project)
    if not directories:
        raise FileNotFoundError(f"No bead store is available for project {project}")
    return directories[0]


def _update_scoped_bead(
    project: str,
    issue_id: str,
    fields: dict[str, str],
) -> Issue:
    beads_dir = _project_beads_dir(project)
    with BeadProject(beads_dir.parent, beads_dirname=beads_dir.name) as bead_project:
        updated = bead_project.update(issue_id, **fields)
    _commit_scoped_bead_store(beads_dir, f"chore(beads): update {issue_id}")
    return updated


def _commit_scoped_bead_store(beads_dir: Path, message: str) -> None:
    root = beads_dir.parent
    if not (root / ".git").exists():
        # In-tree stores are committed with their owning code change, matching
        # the existing bead CLI behavior.
        return
    from sase.sdd.files import commit_sdd_store_files
    from sase.sdd.store import SDD_STORAGE_SEPARATE_REPO, SddStore

    store = SddStore(
        storage=SDD_STORAGE_SEPARATE_REPO,
        sdd_dir=root,
        repo_root=root,
    )
    commit_sdd_store_files(
        store,
        message,
        auto_commit_type="beads",
        paths=[beads_dir],
    )


def _launch_scoped_epic(project: str, epic_id: str) -> bool:
    from sase.bead.cli_work_handler import launch_epic_bead_work

    beads_dir = _project_beads_dir(project)
    with BeadProject(beads_dir.parent, beads_dirname=beads_dir.name) as bead_project:
        return launch_epic_bead_work(
            bead_project,
            epic_id,
            dry_run=False,
            yes=True,
            no_push=False,
        )


def _resolve_issue_url(workspace_dir: str, bug_id: int) -> str:
    from sase.vcs_provider import get_vcs_provider, supports_issues

    if not supports_issues(workspace_dir):
        raise NotImplementedError(
            "The scoped project's VCS provider does not support issues"
        )
    provider = get_vcs_provider(workspace_dir)
    return provider.get_issue_url(bug_id, workspace_dir)


def _epic_for_row(
    row: PlanRow | None,
    snapshot: Any,
) -> Issue | None:
    if row is None or row.issue is None:
        return None
    if row.kind == "epic":
        return row.issue
    parent_id = row.issue.parent_id
    if parent_id is None or snapshot is None:
        return None
    return next(
        (
            epic.issue
            for epic in snapshot.epics
            if epic.project == row.project and epic.issue.id == parent_id
        ),
        None,
    )


__all__ = [
    "ArtifactsPlansActionsMixin",
    "PLANS_ARTIFACT_ACTIONS",
    "_launch_scoped_epic",
    "_resolve_issue_url",
    "_update_scoped_bead",
]

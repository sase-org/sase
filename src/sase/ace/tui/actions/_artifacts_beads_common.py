"""Shared helpers for Artifacts Beads pane actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from sase.bead.model import Issue, IssueType, Status

from ..widgets.artifacts.beads_data import BeadsSnapshot
from ..widgets.artifacts.beads_list import BeadRow
from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane


T = TypeVar("T")

#: Placements whose wires register a post-commit upload through the shared
#: outbox helper. ``public`` is included alongside the CLI's set so a
#: pure-public note still queues instead of stranding bytes locally.
_QUEUEABLE_PLACEMENTS = frozenset({"git", "large", "mixed", "public", "public_pending"})


class _NoteUploadPlan:
    """Placement outcome for one TUI-authored note's attachment wires."""

    def __init__(
        self,
        placement: str = "skip",
        stores: Any = None,
        project_key: str | None = None,
        require_upload: bool = False,
    ) -> None:
        self.placement = placement
        self.stores = stores if stores is not None else {}
        self.project_key = project_key
        self.require_upload = require_upload


def _plan_note_attachment_upload(
    wires: list[dict[str, Any]],
    echo_rows: list[str] | None,
    *,
    project_key: str,
) -> _NoteUploadPlan:
    """Run the pre-write half of the upload protocol for a TUI note.

    Returns a ``skip`` plan when there is nothing to queue. Uses the same
    :func:`pre_write_upload` helper as the CLI note verbs so TUI-authored
    attachments drain through the bead sync worker instead of staying
    local to this machine.
    """
    if not wires or echo_rows is None:
        return _NoteUploadPlan()
    from types import SimpleNamespace

    from sase.bead.attachments.upload import pre_write_upload

    bead_context = SimpleNamespace(project_key=project_key)
    placement, stores, resolved_key, require_upload = pre_write_upload(
        wires,
        echo_rows,
        local_only=False,
        bead_context=bead_context,
    )
    return _NoteUploadPlan(
        placement=placement,
        stores=stores,
        project_key=resolved_key,
        require_upload=require_upload,
    )


def _queue_note_attachment_upload(
    store_mutation: Any,
    wires: list[dict[str, Any]],
    echo_rows: list[str] | None,
    plan: _NoteUploadPlan,
) -> None:
    """Register the post-write half of the upload protocol for a TUI note.

    A no-op unless :func:`_plan_note_attachment_upload` chose a queueable
    placement. The bead store's own ``run_pending_uploads`` hook drains or
    queues the registered rows after commit, exactly as for CLI writes.
    """
    if not wires or echo_rows is None:
        return
    if plan.placement not in _QUEUEABLE_PLACEMENTS:
        return
    from sase.bead.attachments.upload import post_write_queue

    post_write_queue(
        store_mutation,
        wires,
        echo_rows,
        placement=plan.placement,
        stores=plan.stores,
        project_key=plan.project_key,
        require_upload=plan.require_upload,
    )


class ArtifactsBeadsCommonMixin:
    """Selection and tracked-task helpers shared by bead action groups."""

    def _beads_pane(self) -> ArtifactsBeadsPane | None:
        try:
            return self.query_one(  # type: ignore[attr-defined]
                "#artifacts-beads-pane", ArtifactsBeadsPane
            )
        except Exception:
            return None

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
        attachment_wires: list[dict[str, Any]] | None = None,
        attachment_echo_rows: list[str] | None = None,
    ) -> None:
        snapshot = pane.snapshot
        workspace = (
            None if snapshot is None else snapshot.workspace_dirs.get(row.project)
        )
        if not workspace:
            self.notify(  # type: ignore[attr-defined]
                "The project workspace is unavailable", severity="warning"
            )
            return
        from .proc_actions import TrackedProcResult

        def task() -> TrackedProcResult[T]:
            from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
            from sase.bead.mutation_commit import (
                close_mutation_commit_message,
                require_mutation_commit_message,
            )

            with bead_store_mutation(
                auto_commit_bead_store, cwd=Path(workspace)
            ) as store_mutation:
                queued_wires = list(attachment_wires or [])
                queue_state = _plan_note_attachment_upload(
                    queued_wires,
                    attachment_echo_rows,
                    project_key=row.project,
                )
                payload = mutation(store_mutation.project)
                _queue_note_attachment_upload(
                    store_mutation,
                    queued_wires,
                    attachment_echo_rows,
                    queue_state,
                )
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
            return TrackedProcResult(True, success_message, payload)

        self._submit_beads_task(
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
            pane.request_explicit_refresh()
            if refresh_notifications:
                refresh = getattr(self, "_refresh_notification_count", None)
                if callable(refresh):
                    refresh()

        self._submit_session_worker(  # type: ignore[attr-defined]
            f"bead-{operation}",
            task,
            display_name=display_name,
            cl_name=bead_id,
            project_file=workspace,
            dedup_key=f"beads:{operation}:{project}:{bead_id}",
            on_complete=completed,
        )


def next_bead_status(issue: Issue) -> Status:
    """Return the type-aware status cycle used by the Beads pane."""
    if issue.issue_type is IssueType.TASK:
        # Nothing cycles *into* snoozed: a snooze needs a wake time, so it is
        # only reachable through `sase bead snooze`. Cycling out of it clears
        # the record and returns the bead to triage.
        return {
            Status.OPEN: Status.READY,
            Status.CLAIMED: Status.READY,
            Status.READY: Status.IN_PROGRESS,
            Status.SNOOZED: Status.READY,
            Status.IN_PROGRESS: Status.CLOSED,
            Status.CLOSED: Status.OPEN,
        }[issue.status]
    return {
        Status.OPEN: Status.IN_PROGRESS,
        Status.CLAIMED: Status.IN_PROGRESS,
        Status.READY: Status.IN_PROGRESS,
        Status.SNOOZED: Status.IN_PROGRESS,
        Status.IN_PROGRESS: Status.CLOSED,
        Status.CLOSED: Status.OPEN,
    }[issue.status]


def _outcome_ids(outcome: Mapping[str, object], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]


def bead_note_author(project: Any) -> str:
    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity()
    return identity.name if identity is not None else project.owner


def unclosed_descendant_ids(
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


def launch_scoped_epic(beads_dir: Path, epic_id: str) -> bool:
    from sase.bead.cli_work_from_plan_store import epic_plan_launch_lock
    from sase.bead.cli_work_handler import launch_epic_bead_work
    from sase.bead.project import BeadProject

    with epic_plan_launch_lock(beads_dir.parent):
        with BeadProject(beads_dir.parent, beads_dirname=beads_dir.name) as project:
            return bool(
                launch_epic_bead_work(
                    project,
                    epic_id,
                    dry_run=False,
                    yes=True,
                    no_push=False,
                    yes_to_all=True,
                )
            )


def resolve_issue_url(workspace_dir: str, bug_id: int) -> str:
    from sase.vcs_provider import get_vcs_provider, supports_issues

    if not supports_issues(workspace_dir):
        raise NotImplementedError(
            "The scoped project's VCS provider does not support issues"
        )
    return get_vcs_provider(workspace_dir).get_issue_url(bug_id, workspace_dir)

"""External-issue mutations for the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

from sase.bead.model import Issue
from sase.bug_links import normalize_external_ref
from sase.vcs_provider import IssueWire

from ..widgets.artifacts.beads_data_models import ExternalIssueLink
from ..widgets.artifacts.beads_list import BeadRow
from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane
from ._artifacts_beads_common import ArtifactsBeadsCommonMixin


class ArtifactsBeadsIssueMutationActionsMixin(ArtifactsBeadsCommonMixin):
    """Submit edits to linked issues and bead issue references."""

    def _submit_bead_issue_edit(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        link: ExternalIssueLink,
        result: Any,
    ) -> None:
        if link.issue is None:
            return
        self._submit_bead_issue_mutation(
            pane,
            row,
            link,
            operation="edit",
            display_name=f"Edit issue #{link.issue_id}",
            task=lambda: _update_issue_task(
                link,
                title=result.title,
                body=result.body,
                labels=result.labels,
                success_message=f"Updated issue #{link.issue_id}",
            ),
        )

    def _submit_bead_issue_state_toggle(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        link: ExternalIssueLink,
        target: Literal["open", "closed"],
    ) -> None:
        if link.issue is None:
            return
        verb = "Closed" if target == "closed" else "Reopened"
        self._submit_bead_issue_mutation(
            pane,
            row,
            link,
            operation=target,
            display_name=f"{verb} issue #{link.issue_id}",
            task=lambda: _update_issue_task(
                link,
                state=target,
                success_message=f"{verb} issue #{link.issue_id}",
            ),
        )

    def _submit_bead_issue_mutation(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        link: ExternalIssueLink,
        *,
        operation: str,
        display_name: str,
        task: Callable[[], Any],
    ) -> None:
        workspace = issue_task_workspace(pane, row, link)
        if not workspace:
            self._notify_beads(
                "The issue project workspace is unavailable",
                severity="warning",
            )
            return

        def completed(_completion: Any) -> None:
            pane.request_refresh()

        self._submit_session_worker(  # type: ignore[attr-defined]
            f"bead-issue-{operation}",
            task,
            display_name=display_name,
            cl_name=row.issue.id,
            project_file=workspace,
            on_complete=completed,
        )

    def _submit_bead_issue_attach(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        raw_number: str,
    ) -> None:
        number = raw_number.strip().removeprefix("#")
        if not number.isdigit():
            self._notify_beads(
                f"Issue number must be numeric: {raw_number}",
                severity="warning",
            )
            return
        canonical = normalize_external_ref(number, project=row.project)
        if not canonical:
            self._notify_beads("Unable to normalize issue reference", severity="error")
            return

        def mutate(project: Any) -> Issue:
            return _attach_external_ref(project, row.issue, canonical, row.project)

        self._submit_bead_mutation(
            pane,
            row,
            operation="issue-attach",
            display_name=f"Attach issue #{number} · {row.issue.id}",
            success_message=f"Attached issue #{number} to {row.issue.id}",
            mutation=mutate,
            commit_operation="update",
        )

    def _submit_bead_issue_create(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        result: Any,
    ) -> None:
        snapshot = pane.snapshot
        workspace = (
            None if snapshot is None else snapshot.workspace_dirs.get(row.project)
        )
        if not workspace:
            self._notify_beads(
                "The selected project workspace is unavailable",
                severity="warning",
            )
            return
        from .proc_actions import TrackedProcResult

        def task() -> TrackedProcResult[IssueWire]:
            from sase.ace.tui.external_issues import create_project_issue
            from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
            from sase.bead.mutation_commit import require_mutation_commit_message

            created = create_project_issue(
                row.project,
                title=result.title,
                body=result.body,
                labels=result.labels,
            )
            canonical = normalize_external_ref(created.number, project=row.project)
            with bead_store_mutation(
                auto_commit_bead_store,
                cwd=Path(workspace),
            ) as mutation:
                _attach_external_ref(
                    mutation.project, row.issue, canonical, row.project
                )
                mutation.commit(
                    require_mutation_commit_message("update", [row.issue.id])
                )
            return TrackedProcResult(
                True,
                f"Created issue #{created.number} and linked {row.issue.id}",
                created,
            )

        self._submit_beads_task(
            pane,
            project=row.project,
            bead_id=row.issue.id,
            operation="issue-create",
            display_name=f"Create issue · {row.issue.id}",
            workspace=workspace,
            task=task,
        )


def issue_task_workspace(
    pane: ArtifactsBeadsPane,
    row: BeadRow,
    link: ExternalIssueLink,
) -> str:
    cache = pane.external_project_cache(link.project)
    if cache is not None and cache.cwd:
        return cache.cwd
    snapshot = pane.snapshot
    if snapshot is None:
        return ""
    return snapshot.workspace_dirs.get(row.project) or ""


def _update_issue_task(
    link: ExternalIssueLink,
    *,
    success_message: str,
    title: str | None = None,
    body: str | None = None,
    state: Literal["open", "closed"] | None = None,
    labels: tuple[str, ...] | None = None,
) -> Any:
    from sase.ace.tui.actions.proc_actions import TrackedProcResult
    from sase.ace.tui.external_issues import update_project_issue

    if not link.issue_id.isdigit():
        raise ValueError(f"issue id is not numeric: {link.issue_id}")
    issue = update_project_issue(
        link.project,
        int(link.issue_id),
        title=title,
        body=body,
        state=state,
        labels=labels,
    )
    return TrackedProcResult(True, success_message, issue)


def _attach_external_ref(
    project: Any,
    issue: Issue,
    canonical: str,
    project_key: str,
) -> Issue:
    refs = _refs_with_canonical_bug_ref(issue.refs, canonical, project_key)
    fields: dict[str, Any] = {}
    if tuple(refs) != tuple(issue.refs):
        fields["refs"] = list(refs)
    if not normalize_external_ref(issue.external_ref, project=project_key):
        fields["external_ref"] = canonical
    if not fields:
        return issue
    return project.update(issue.id, **fields)


def _refs_with_canonical_bug_ref(
    refs: Iterable[str],
    canonical: str,
    project_key: str,
) -> tuple[str, ...]:
    existing_refs = tuple(refs)
    if any(
        ref.strip().casefold().startswith("bug:")
        and normalize_external_ref(ref, project=project_key) == canonical
        for ref in existing_refs
    ):
        return existing_refs
    return (*existing_refs, canonical)

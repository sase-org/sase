"""Work-launch and external-link actions for the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.bead.model import Issue, IssueType, Status
from sase.bug_links import normalize_external_ref
from sase.vcs_provider import IssueWire

from ..widgets._prompt_preview_target import PreviewPayload
from ..widgets.artifacts.beads_data_models import ExternalIssueLink
from ..widgets.artifacts.beads_list import BeadRow
from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane
from ._artifacts_beads_common import ArtifactsBeadsCommonMixin


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
        self._with_selected_issue_link(
            pane,
            row,
            lambda link: self._submit_beads_issue_open(pane, row, link),
        )

    def action_beads_copy_bug(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        self._with_selected_issue_link(pane, row, self._copy_issue_ref)

    def action_start_bead_issue_mode(self) -> None:
        if getattr(self, "current_artifacts_pane_key", None) != "beads":
            return
        if self._selected_bead() is None:
            return
        self._bead_issue_mode_active = True  # type: ignore[attr-defined]
        sync = getattr(self, "_sync_active_artifacts_entry_state", None)
        if callable(sync):
            sync()

    def _handle_bead_issue_key(self, key: str) -> bool:
        if not getattr(self, "_bead_issue_mode_active", False):
            return False
        self._bead_issue_mode_active = False  # type: ignore[attr-defined]
        if key == "escape":
            self._restore_bead_issue_footer()
            return True
        keys = self._keymap_registry.bead_issue_mode.keys  # type: ignore[attr-defined]
        handled = True
        if key == keys["view"]:
            self._beads_issue_view_cached_body()
        elif key == keys["edit"]:
            self._beads_issue_edit()
        elif key == keys["toggle_state"]:
            self._beads_issue_toggle_state()
        elif key == keys["copy_url"]:
            self._beads_issue_copy_url()
        elif key == keys["attach"]:
            self._beads_issue_attach()
        elif key == keys["create"]:
            self._beads_issue_create()
        else:
            self._notify_beads(f"Unknown issue action: {key}", severity="warning")
        self._restore_bead_issue_footer()
        return handled

    def _restore_bead_issue_footer(self) -> None:
        sync = getattr(self, "_sync_active_artifacts_entry_state", None)
        if callable(sync):
            sync()
        else:
            self._refresh_current_tab()  # type: ignore[attr-defined]

    def _beads_issue_view_cached_body(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        self._with_selected_issue_link(
            pane,
            row,
            lambda link: self._open_cached_issue_body(row, link),
        )

    def _beads_issue_edit(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        self._with_selected_issue_link(
            pane,
            row,
            lambda link: self._open_issue_edit_modal(pane, row, link),
        )

    def _beads_issue_toggle_state(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        self._with_selected_issue_link(
            pane,
            row,
            lambda link: self._confirm_issue_state_toggle(pane, row, link),
        )

    def _beads_issue_copy_url(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        self._with_selected_issue_link(
            pane,
            row,
            lambda link: self._copy_issue_url(pane, row, link),
        )

    def _beads_issue_attach(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        from ..modals import CustomModelInputModal

        self.push_screen(  # type: ignore[attr-defined]
            CustomModelInputModal(
                title="Attach Existing Issue",
                hint="Enter a numeric tracker issue number.",
                placeholder="e.g. 42",
            ),
            lambda value: (
                self._submit_bead_issue_attach(pane, row, value) if value else None
            ),
        )

    def _beads_issue_create(self) -> None:
        selected = self._selected_bead()
        if selected is None:
            return
        pane, row = selected
        if pane.external_links_for_row(row):
            self._notify_beads(
                "This bead already has an external issue link",
                severity="warning",
            )
            return
        cache = pane.external_project_cache(row.project)
        if cache is None or not cache.capabilities.mutations:
            self._notify_beads(
                "This project cannot create tracker issues",
                severity="warning",
            )
            return
        from ..modals import IssueEditModal, IssueEditResult

        seed = IssueWire(
            number=0,
            title=row.issue.title,
            state="open",
            body=row.issue.description,
        )

        def dismissed(result: IssueEditResult | None) -> None:
            if result is not None:
                self._submit_bead_issue_create(pane, row, result)

        self.push_screen(  # type: ignore[attr-defined]
            IssueEditModal(seed, heading="Create Issue"),
            dismissed,
        )

    def _with_selected_issue_link(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        callback: Callable[[ExternalIssueLink], None],
    ) -> None:
        links = pane.external_links_for_row(row)
        if not links:
            self._notify_beads(
                "The selected bead has no external issue link",
                severity="warning",
            )
            return
        if len(links) == 1:
            callback(links[0])
            return
        from ..modals.bead_issue_modal import BeadIssueSelectModal

        self.push_screen(  # type: ignore[attr-defined]
            BeadIssueSelectModal(links),
            lambda link: callback(link) if link is not None else None,
        )

    def _submit_beads_issue_open(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        link: ExternalIssueLink,
    ) -> None:
        workspace = _issue_task_workspace(pane, row, link)
        if not workspace:
            self._notify_beads(
                "The issue project workspace is unavailable",
                severity="warning",
            )
            return
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[str]:
            import webbrowser

            url = _resolved_issue_url(link)
            opened = webbrowser.open(url)
            return TrackedTaskResult(
                opened,
                (
                    f"Opened issue #{link.issue_id}"
                    if opened
                    else "Browser did not accept the issue URL"
                ),
                url,
                None if opened else "browser rejected URL",
            )

        def completed(_completion: Any) -> None:
            return

        self._submit_tracked_task(  # type: ignore[attr-defined]
            "bead-issue-open",
            row.issue.id,
            workspace,
            task,
            display_name=f"Open issue #{link.issue_id}",
            dedup_key=f"beads:issue-open:{link.project}:{link.issue_id}",
            on_complete=completed,
            reload_on_complete=False,
        )

    def _copy_issue_ref(self, link: ExternalIssueLink) -> None:
        schedule_copy_delivery(
            self,
            _display_issue_ref(link),
            copied_label=f"issue ref #{link.issue_id}",
            task_name="sase-bead-copy-issue-ref",
        )

    def _copy_issue_url(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        link: ExternalIssueLink,
    ) -> None:
        del pane, row
        schedule_copy_delivery(
            self,
            lambda: _resolved_issue_url(link),
            copied_label=f"issue URL #{link.issue_id}",
            task_name="sase-bead-copy-issue-url",
        )

    def _open_cached_issue_body(self, row: BeadRow, link: ExternalIssueLink) -> None:
        del row
        if link.issue is None or not link.issue.body.strip():
            self._notify_beads("The cached issue body is empty", severity="warning")
            return
        from ..modals.preview_panel_modal import PreviewPanelModal

        self.push_screen(  # type: ignore[attr-defined]
            PreviewPanelModal(
                PreviewPayload(
                    content=link.issue.body,
                    lexer="markdown",
                    title=f"{link.display_project} #{link.issue_id}",
                    kind_label="external issue",
                    icon="○",
                    reference=_display_issue_ref(link),
                    source_path=None,
                    default_view="rendered",
                )
            )
        )

    def _open_issue_edit_modal(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        link: ExternalIssueLink,
    ) -> None:
        if link.issue is None:
            self._notify_beads(
                "This issue is not in the cached list", severity="warning"
            )
            return
        if not _link_mutations_supported(pane, link):
            self._notify_beads(
                "This project cannot mutate tracker issues",
                severity="warning",
            )
            return
        from ..modals import IssueEditModal, IssueEditResult

        def dismissed(result: IssueEditResult | None) -> None:
            if result is not None:
                self._submit_bead_issue_edit(pane, row, link, result)

        self.push_screen(  # type: ignore[attr-defined]
            IssueEditModal(link.issue),
            dismissed,
        )

    def _confirm_issue_state_toggle(
        self,
        pane: ArtifactsBeadsPane,
        row: BeadRow,
        link: ExternalIssueLink,
    ) -> None:
        if link.issue is None:
            self._notify_beads(
                "This issue is not in the cached list", severity="warning"
            )
            return
        if not _link_mutations_supported(pane, link):
            self._notify_beads(
                "This project cannot mutate tracker issues",
                severity="warning",
            )
            return
        from ..modals import ConfirmActionModal, ConfirmKind

        target: Literal["open", "closed"] = (
            "closed" if link.issue.state == "open" else "open"
        )
        verb = "Close" if target == "closed" else "Reopen"

        def confirmed(value: bool) -> None:
            if value:
                self._submit_bead_issue_state_toggle(pane, row, link, target)

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                f"{verb} Issue",
                f"{verb} issue #{link.issue_id}?",
                subject=link.issue.title,
                kind=ConfirmKind.DANGER if target == "closed" else ConfirmKind.NEUTRAL,
                confirm_label=verb,
            ),
            confirmed,
        )

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
        workspace = _issue_task_workspace(pane, row, link)
        if not workspace:
            self._notify_beads(
                "The issue project workspace is unavailable",
                severity="warning",
            )
            return

        def completed(_completion: Any) -> None:
            pane.request_refresh()

        self._submit_tracked_task(  # type: ignore[attr-defined]
            f"bead-issue-{operation}",
            row.issue.id,
            workspace,
            task,
            display_name=display_name,
            dedup_key=f"beads:issue:{operation}:{link.project}:{link.issue_id}",
            on_complete=completed,
            reload_on_complete=False,
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
        from .task_actions import TrackedTaskResult

        def task() -> TrackedTaskResult[IssueWire]:
            from sase.ace.tui.artifacts_bugs import create_project_issue
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
            return TrackedTaskResult(
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


def _display_issue_ref(link: ExternalIssueLink) -> str:
    return f"bug:{link.display_project}#{link.issue_id}"


def _resolved_issue_url(link: ExternalIssueLink) -> str:
    if link.issue is not None and link.issue.url:
        return link.issue.url
    if not link.issue_id.isdigit():
        raise ValueError(f"issue id is not numeric: {link.issue_id}")
    from sase.ace.tui.artifacts_bugs import issue_url_for_number

    return issue_url_for_number(link.project, int(link.issue_id))


def _issue_task_workspace(
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


def _link_mutations_supported(
    pane: ArtifactsBeadsPane,
    link: ExternalIssueLink,
) -> bool:
    cache = pane.external_project_cache(link.project)
    return bool(cache is not None and cache.capabilities.mutations)


def _update_issue_task(
    link: ExternalIssueLink,
    *,
    success_message: str,
    title: str | None = None,
    body: str | None = None,
    state: Literal["open", "closed"] | None = None,
    labels: tuple[str, ...] | None = None,
) -> Any:
    from sase.ace.tui.actions.task_actions import TrackedTaskResult
    from sase.ace.tui.artifacts_bugs import update_project_issue

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
    return TrackedTaskResult(True, success_message, issue)


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

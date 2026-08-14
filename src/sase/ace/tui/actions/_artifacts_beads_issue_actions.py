"""External-issue interactions for the Artifacts Beads pane."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.vcs_provider import IssueWire

from ..widgets._prompt_preview_target import PreviewPayload
from ..widgets.artifacts.beads_data_models import ExternalIssueLink
from ..widgets.artifacts.beads_list import BeadRow
from ..widgets.artifacts.beads_pane import ArtifactsBeadsPane
from ._artifacts_beads_issue_mutations import (
    ArtifactsBeadsIssueMutationActionsMixin,
    issue_task_workspace,
)


class ArtifactsBeadsIssueActionsMixin(ArtifactsBeadsIssueMutationActionsMixin):
    """Interact with tracker issues linked to the selected bead."""

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
        workspace = issue_task_workspace(pane, row, link)
        if not workspace:
            self._notify_beads(
                "The issue project workspace is unavailable",
                severity="warning",
            )
            return
        from .proc_actions import TrackedProcResult

        def task() -> TrackedProcResult[str]:
            import webbrowser

            url = _resolved_issue_url(link)
            opened = webbrowser.open(url)
            return TrackedProcResult(
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

        self._submit_tracked_proc(  # type: ignore[attr-defined]
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


def _display_issue_ref(link: ExternalIssueLink) -> str:
    return f"bug:{link.display_project}#{link.issue_id}"


def _resolved_issue_url(link: ExternalIssueLink) -> str:
    if link.issue is not None and link.issue.url:
        return link.issue.url
    if not link.issue_id.isdigit():
        raise ValueError(f"issue id is not numeric: {link.issue_id}")
    from sase.ace.tui.external_issues import issue_url_for_number

    return issue_url_for_number(link.project, int(link.issue_id))


def _link_mutations_supported(
    pane: ArtifactsBeadsPane,
    link: ExternalIssueLink,
) -> bool:
    cache = pane.external_project_cache(link.project)
    return bool(cache is not None and cache.capabilities.mutations)

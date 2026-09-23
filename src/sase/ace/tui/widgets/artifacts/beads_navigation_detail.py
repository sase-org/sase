"""Detail preview, conditional footer, and snooze/launch rules for Beads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Markdown, Static

from sase.ace.tui.keymaps import KeymapRegistry
from sase.bead.model import IssueType, Status
from sase.core.artifact_relation_layout import RelationKeymap

from .._prompt_preview_target import PreviewPayload
from .beads_data import BeadsSnapshot
from .beads_detail import (
    bead_body_markdown,
    bead_preview_markdown,
    bead_properties_header,
    resolved_plan_path,
)
from .beads_list import BeadRow

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .beads_data_models import ExternalIssueLink
else:
    _MixinBase = object


class BeadsNavigationDetailMixin(_MixinBase):
    """Own bead detail content, preview payloads, and footer entries."""

    _snapshot: BeadsSnapshot | None
    _registry: KeymapRegistry
    _conditional_footer_signature: tuple[tuple[str, str], ...] | None

    if TYPE_CHECKING:

        def selected_row(self) -> BeadRow | None: ...

        def _empty_detail(self) -> str: ...

        def refresh_relation_panel(self, *, refresh_footer: bool = True) -> Any: ...

        def relation_footer_entries(
            self, keymap: Any = None
        ) -> tuple[tuple[str, str], ...]: ...

        def external_links_for_row(
            self,
            row: BeadRow,
        ) -> tuple[ExternalIssueLink, ...]: ...

    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        row = self.selected_row()
        refresh_relation_panel = getattr(self, "refresh_relation_panel", None)
        keymap = getattr(
            getattr(self, "app", None),
            "_relation_footer_keymap_override",
            None,
        )
        if row is None:
            if keymap is None and callable(refresh_relation_panel):
                refresh_relation_panel(refresh_footer=False)
            return ()
        if keymap is None:
            keymap = (
                refresh_relation_panel(refresh_footer=False)
                if callable(refresh_relation_panel)
                else None
            )
        return BeadsNavigationDetailMixin._conditional_footer_entries(self, keymap)

    def _conditional_footer_entries(
        self,
        keymap: Any = None,
    ) -> tuple[tuple[str, str], ...]:
        row = self.selected_row()
        if row is None:
            return ()
        entries: list[tuple[str, str]] = []
        snapshot = self._snapshot
        if _can_launch_bead_row(row, snapshot):
            entries.append(("beads_launch_work", "launch"))
        entries.append(
            (
                "beads_close",
                "reopen" if row.issue.status is Status.CLOSED else "close",
            )
        )
        if _bead_row_is_snoozable(row):
            entries.append(
                (
                    "beads_snooze",
                    "re-snooze" if row.issue.status is Status.SNOOZED else "snooze",
                )
            )
        external_links_for_row = getattr(self, "external_links_for_row", None)
        if callable(external_links_for_row) and external_links_for_row(row):
            entries.append(("beads_open_bug", "open issue"))
        entries.append(("start_bead_issue_mode", "issue"))
        relation_footer_entries = getattr(self, "relation_footer_entries", None)
        if callable(relation_footer_entries):
            entries.extend(relation_footer_entries(keymap))
        return tuple(entries)

    def _sync_artifacts_footer_if_changed(
        self,
        footer_entries: tuple[tuple[str, str], ...],
        keymap: RelationKeymap,
    ) -> None:
        if self._conditional_footer_signature == footer_entries:
            return
        self._conditional_footer_signature = footer_entries
        if not getattr(self, "artifacts_active", False):
            return
        app = getattr(self, "app", None)
        sync = getattr(app, "_sync_active_artifacts_entry_state", None)
        if app is None or not callable(sync):
            return
        attr = "_relation_footer_keymap_override"
        had_previous = hasattr(app, attr)
        previous = getattr(app, attr, None)
        setattr(app, attr, keymap)
        try:
            sync()
        finally:
            if had_previous:
                setattr(app, attr, previous)
            else:
                delattr(app, attr)

    def preview_for_row(self, row: BeadRow) -> PreviewPayload:
        issue = row.issue
        return PreviewPayload(
            content=bead_preview_markdown(
                issue,
                self._snapshot,
                project=row.project,
                registry=self._registry,
                external_links=self.external_links_for_row(row),
            ),
            lexer="markdown",
            title=f"{issue.id} · {issue.title}",
            kind_label=f"{row.kind} bead",
            icon="◈",
            source_path=resolved_plan_path(
                issue,
                self._snapshot,
                project=row.project,
            ),
            reference=issue.design.strip() or None,
            default_view="rendered",
        )

    def selected_preview(self) -> PreviewPayload | None:
        row = self.selected_row()
        return None if row is None else self.preview_for_row(row)

    def _update_detail(self) -> None:
        try:
            properties = self.query_one("#beads-detail-properties", Static)
            body = self.query_one("#beads-detail", Markdown)
        except Exception:
            return
        row = self.selected_row()
        if row is None:
            properties.display = False
            properties.update("")
            body.update(self._empty_detail())
            self.refresh_relation_panel()
            return
        properties.display = True
        properties.update(
            bead_properties_header(
                row.issue,
                self._snapshot,
                project=row.project,
                project_name=self._project_name(row.project),
                external_links=self.external_links_for_row(row),
            )
        )
        triage = (
            None
            if self._snapshot is None
            else self._snapshot.triage_gates.get((row.project, row.issue.id))
        )
        body.update(
            bead_body_markdown(
                row.issue,
                triage,
                registry=self._registry,
                external_links=self.external_links_for_row(row),
            )
        )
        self.refresh_relation_panel()

    def _project_name(self, project: str) -> str:
        if self._snapshot is None:
            return project
        return self._snapshot.display_names.get(project, project)


def _can_launch_bead_row(
    row: BeadRow,
    snapshot: BeadsSnapshot | None,
) -> bool:
    issue = row.issue
    if issue.status is Status.CLOSED:
        return False
    if issue.issue_type is IssueType.PHASE:
        return False
    if issue.issue_type is IssueType.TASK:
        return issue.status in {Status.OPEN, Status.READY}
    if snapshot is None:
        return False
    key = (row.project, issue.id)
    return bool(snapshot.phases_by_epic.get(key)) and key not in snapshot.blocked_ids


def _bead_row_is_snoozable(row: BeadRow) -> bool:
    """Return whether *row* is a task bead the store would let us snooze."""
    return row.issue.issue_type is IssueType.TASK and row.issue.status in {
        Status.OPEN,
        Status.READY,
        Status.SNOOZED,
    }


__all__ = ["BeadsNavigationDetailMixin"]

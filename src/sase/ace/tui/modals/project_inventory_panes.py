"""Async repository and workspace inventory panes for the Admin Center."""

from __future__ import annotations

import time

from rich.text import Text

from sase._linked_repo_identity import reset_repo_identity_caches
from sase.repo_inventory import (
    RepoInventoryIssue,
    RepoRecord,
    collect_repo_inventory,
)
from sase.workspace_provider.inventory import (
    WorkspaceInventoryIssue,
    WorkspaceInventoryRecord,
    collect_workspace_inventory,
)

from .project_inventory_pane_base import InventoryPaneBase
from .project_inventory_rendering import (
    repo_column_header_text,
    repo_detail_text,
    repo_hints_text,
    repo_record_label,
    repo_summary_text,
    workspace_column_header_text,
    workspace_detail_text,
    workspace_hints_text,
    workspace_record_label,
    workspace_summary_text,
)
from .project_inventory_types import InventoryLoadResult


class RepoInventoryPane(InventoryPaneBase[RepoRecord, RepoInventoryIssue]):
    """Cached repository inventory view."""

    _prefix = "repos"
    _option_list_id = "repos-list"
    _reset_caches_on_next_load = False

    def action_reload_inventory(self) -> None:
        self._reset_caches_on_next_load = True
        super().action_reload_inventory()

    def _prepare_inventory_load(self) -> None:
        if not self._reset_caches_on_next_load:
            return
        reset_repo_identity_caches()
        self._reset_caches_on_next_load = False

    def _load_inventory(
        self,
    ) -> InventoryLoadResult[RepoRecord, RepoInventoryIssue]:
        inventory = collect_repo_inventory(
            self._projects_root,
            include_disabled=True,
        )
        return InventoryLoadResult(
            inventory.records,
            inventory.issues,
            time.time(),
        )

    def _column_header_text(self) -> Text:
        return repo_column_header_text()

    def _record_label(self, record: RepoRecord) -> Text:
        return repo_record_label(record)

    def _summary_text(self) -> Text:
        return repo_summary_text(
            self._scoped_records,
            project=self._project_label(),
            text_filter=self._text_filter,
            issue_count=len(self._issues),
            loading=self._loading,
            error=self._load_error,
        )

    def _detail_text(self, record: RepoRecord | None) -> Text:
        return repo_detail_text(record, issues=self._issues_for(record))

    def _hints_text(self) -> str:
        return repo_hints_text(
            project_filtered=self._project_filter is not None,
            jump_active=self.jump_mode_active,
            jump_back=bool(self.jump_back_stack),
        )

    def _record_id(self, record: RepoRecord) -> str:
        return f"{record.project_key}:{record.kind}:{record.name}:{record.path}"

    def _record_haystack(self, record: RepoRecord) -> str:
        return " ".join(
            (
                record.name,
                record.kind,
                record.project,
                record.project_key,
                record.path,
                record.description or "",
                record.source,
                record.env_name or "",
                "cloned" if record.exists else "missing",
            )
        )

    def _record_project(self, record: RepoRecord) -> str:
        return record.project

    def _record_project_key(self, record: RepoRecord) -> str:
        return record.project_key

    def _enabled_by_default(self, record: RepoRecord) -> bool:
        # Home is intentionally represented only by linked repositories and is
        # absent from the true-project state map; it remains part of the default
        # all-enabled repository inventory.
        return self._project_states.get(record.project_key, "enabled") == "enabled"


class WorkspaceInventoryPane(
    InventoryPaneBase[WorkspaceInventoryRecord, WorkspaceInventoryIssue]
):
    """Cached workspace inventory view."""

    _prefix = "workspaces"
    _option_list_id = "workspaces-list"

    def _load_inventory(
        self,
    ) -> InventoryLoadResult[WorkspaceInventoryRecord, WorkspaceInventoryIssue]:
        inventory = collect_workspace_inventory(
            self._projects_root,
            include_disabled=True,
        )
        return InventoryLoadResult(
            inventory.records,
            inventory.issues,
            time.time(),
        )

    def _column_header_text(self) -> Text:
        return workspace_column_header_text()

    def _record_label(self, record: WorkspaceInventoryRecord) -> Text:
        return workspace_record_label(record, now=self._loaded_at)

    def _summary_text(self) -> Text:
        return workspace_summary_text(
            self._scoped_records,
            project=self._project_label(),
            text_filter=self._text_filter,
            issue_count=len(self._issues),
            loading=self._loading,
            error=self._load_error,
        )

    def _detail_text(self, record: WorkspaceInventoryRecord | None) -> Text:
        return workspace_detail_text(
            record,
            now=self._loaded_at,
            issues=self._issues_for(record),
        )

    def _hints_text(self) -> str:
        return workspace_hints_text(
            project_filtered=self._project_filter is not None,
            jump_active=self.jump_mode_active,
            jump_back=bool(self.jump_back_stack),
        )

    def _record_id(self, record: WorkspaceInventoryRecord) -> str:
        return f"{record.project_key}:{record.workspace_num}:{record.checkout_dir}"

    def _record_haystack(self, record: WorkspaceInventoryRecord) -> str:
        return " ".join(
            (
                str(record.workspace_num),
                record.project,
                record.project_key,
                record.checkout_dir,
                record.role,
                record.materialization,
                record.claim_agent or "",
                record.claim_cl_name or "",
                "claimed" if record.claimed else "free",
                "pinned" if record.pinned else "",
                "stale" if record.stale else "",
                "missing" if not record.exists else "",
                "dead" if record.claim_pid_alive is False else "",
            )
        )

    def _record_project(self, record: WorkspaceInventoryRecord) -> str:
        return record.project

    def _record_project_key(self, record: WorkspaceInventoryRecord) -> str:
        return record.project_key

    def _enabled_by_default(self, record: WorkspaceInventoryRecord) -> bool:
        return record.project_state == "enabled"


__all__ = [
    "RepoInventoryPane",
    "WorkspaceInventoryPane",
]

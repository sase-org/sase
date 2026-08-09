"""Shared test helpers for Artifacts copy-mode coverage."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.clipboard import ClipboardMixin
from sase.ace.tui.keymaps import load_keymap_registry


class CopyHarness(ClipboardMixin):
    """Small synchronous harness around the copy dispatch mixins."""

    def __init__(self) -> None:
        self.current_tab = "patches"
        self.current_artifacts_subtab = "commits"
        self.patches: list[Any] = []
        self._keymap_registry = load_keymap_registry({})
        self._copy_mode_active = False
        self.copies: list[tuple[str, str]] = []
        self.notifications: list[tuple[str, str]] = []
        self.copy_footer_updates = 0
        self.artifacts_footer_restores = 0
        self.tab_footer_restores = 0
        self.snapshot_copies = 0
        self.commits_pane: Any = None
        self.plans_pane: Any = None
        self.chats_pane: Any = None
        self.bugs_pane: Any = None
        self.files_pane: Any = None

    def notify(
        self,
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        self.notifications.append((message, severity))

    def _update_copy_footer(self) -> None:
        self.copy_footer_updates += 1

    def _sync_active_artifacts_entry_state(self) -> None:
        self.artifacts_footer_restores += 1

    def _refresh_current_tab(self) -> None:
        self.tab_footer_restores += 1

    def _copy_snapshot(self) -> None:
        self.snapshot_copies += 1

    def _schedule_artifacts_copy(
        self,
        content: str | Any,
        *,
        copied_message: str | Any,
        task_name: str = "sase-artifacts-copy",
        content_shaped: bool = False,
    ) -> None:
        del task_name, content_shaped
        value = content() if callable(content) else content
        message = copied_message() if callable(copied_message) else copied_message
        self.copies.append((value, message))

    def _commits_pane(self) -> Any:
        return self.commits_pane

    def action_commits_copy_sha(self) -> None:
        entry = self.commits_pane._selected_entry()
        self.copies.append((entry.commit.full_id, "Copied commit SHA"))

    def _plans_pane(self) -> Any:
        return self.plans_pane

    def _chats_pane(self) -> Any:
        return self.chats_pane

    def action_chats_copy_path(self) -> None:
        self.copies.append(
            (self.chats_pane.selected_entry.absolute_path, "Copied chat path")
        )

    def _bugs_pane(self) -> Any:
        return self.bugs_pane

    def _files_pane(self) -> Any:
        return self.files_pane

    def _selected_bug_copy_context(self) -> Any:
        pane = self.bugs_pane
        if pane is None or pane.selected_issue is None or pane.project_scope is None:
            return None
        return pane, pane.selected_issue, pane.project_scope

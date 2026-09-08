"""Commit hint modal and clipboard helpers for hint input processing."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from ...widgets.prompt_panel._agent_display_state import CommitViewSpec
from ..clipboard import schedule_copy_delivery
from ._types import HintMixinBase


class CommitHintProcessingMixin(HintMixinBase):
    """Mixin providing commit hint modal and clipboard helpers."""

    def _prepend_commit_diff_paths(
        self,
        commit_hint_nums: list[int],
        files: list[str],
    ) -> list[str]:
        commit_views = getattr(self, "_hint_commit_views", {})
        selected_files: list[str] = []
        missing: list[str] = []
        for hint_num in commit_hint_nums:
            spec = commit_views[hint_num]
            if spec.diff_path:
                path = os.path.expanduser(spec.diff_path)
                if path not in selected_files:
                    selected_files.append(path)
            else:
                missing.append(spec.short_sha or spec.sha or str(hint_num))
        if missing:
            self.notify(  # type: ignore[attr-defined]
                f"No raw diff path for commit(s): {', '.join(missing)}",
                severity="warning",
            )
        for file_path in files:
            if file_path not in selected_files:
                selected_files.append(file_path)
        return selected_files

    def _open_commit_hint(self, commit_hint_nums: list[int]) -> None:
        commit_views = getattr(self, "_hint_commit_views", {})
        self._open_commit_view(tuple(commit_views[hint] for hint in commit_hint_nums))

    def _open_commit_view(self, specs: Sequence[CommitViewSpec]) -> None:
        from ...modals.commit_view_modal import CommitViewModal

        self.app.push_screen(CommitViewModal(specs))  # type: ignore[attr-defined]

    def _copy_commit_selection_to_clipboard(
        self,
        commit_hint_nums: list[int],
        files: list[str],
    ) -> None:
        commit_views = getattr(self, "_hint_commit_views", {})
        self._copy_commit_specs_to_clipboard(
            tuple(commit_views[hint_num] for hint_num in commit_hint_nums),
            files,
        )

    def _copy_commit_specs_to_clipboard(
        self,
        commit_specs: Sequence[CommitViewSpec],
        files: list[str],
    ) -> None:
        shas = [spec.short_sha or spec.sha for spec in commit_specs]
        shas = [sha for sha in shas if sha]
        if not files:
            content = " ".join(shas)
            schedule_copy_delivery(
                self,
                content,
                copied_label=f"{len(shas)} commit SHA(s)",
                task_name="sase-copy-hinted-commits",
            )
            return

        home = str(Path.home())
        shortened_files = [
            f.replace(home, "~", 1) if f.startswith(home) else f for f in files
        ]
        content = " ".join([*shas, *shortened_files])
        schedule_copy_delivery(
            self,
            content,
            copied_label="commit SHA(s) and path(s)",
            task_name="sase-copy-hinted-commit-paths",
        )

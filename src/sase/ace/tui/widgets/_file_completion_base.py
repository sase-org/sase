"""Shared state and panel helpers for prompt file completion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._file_completion_context import FileCompletionContextMixin
from sase.ace.tui.widgets.file_completion import MAX_VISIBLE, CompletionCandidate
from sase.xprompt.vcs_project_completion import build_vcs_project_completion_entries

if TYPE_CHECKING:
    from sase.ace.tui.widgets.xprompt_arg_assist import (
        ActiveXPromptArgHint,
        XPromptAssistEntry,
    )


class FileCompletionBaseMixin(FileCompletionContextMixin):
    """Mixin providing shared completion state helpers."""

    if TYPE_CHECKING:
        _file_completion_candidates: list[CompletionCandidate]
        _file_completion_index: int
        _file_completion_active: bool
        _completion_kind: str
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None

        def _find_prompt_bar(self) -> Any: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _note_optional_xprompt_spacer(self, entry: XPromptAssistEntry) -> None: ...
        def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None: ...
        def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _get_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...
        def _build_warm_xprompt_completion_candidates(
            self,
            token: str,
        ) -> tuple[list[CompletionCandidate], str] | None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _expand_snippet_template_at_range(
            self,
            template: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> bool: ...

    def _update_file_completion_panel(self, token: str) -> None:
        """Sync completion UI with the current completion state."""
        bar = self._find_prompt_bar()
        if bar is None:
            return

        if not self._file_completion_active or not self._file_completion_candidates:
            bar.hide_file_completions()
            return

        rows = self._file_completion_candidates
        total = len(rows)
        if total <= MAX_VISIBLE:
            scroll_offset = 0
        else:
            half = MAX_VISIBLE // 2
            scroll_offset = max(
                0, min(self._file_completion_index - half, total - MAX_VISIBLE)
            )
        bar.show_file_completions(
            token,
            rows,
            self._file_completion_index,
            scroll_offset,
            completion_kind=self._completion_kind,
        )

    def _clear_file_completion(self, *, clear_xprompt_arg_hint: bool = True) -> None:
        """Reset path completion state and hide panel."""
        self._file_completion_active = False
        self._file_completion_candidates = []
        self._file_completion_index = 0
        self._completion_kind = "file"
        self._update_file_completion_panel("")
        if clear_xprompt_arg_hint:
            self._clear_xprompt_arg_hint()

    def _warm_vcs_project_completion_catalog(self) -> None:
        """Warm the ``#+`` project catalog off the keystroke path.

        The catalog build touches disk (project enumeration + provider
        detection), so it must never run synchronously inside key handling
        (``memory/tui_perf.md``). Building once in a background thread populates
        the module-level cache in :mod:`sase.xprompt.vcs_project_completion`, so
        the first ``#+`` opens the menu instantly. Gated on the real app's
        completion-settings capability so lightweight test harnesses skip it.
        """
        if getattr(self, "_vcs_project_catalog_warmed", False):
            return
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return
        self._vcs_project_catalog_warmed = True
        self.run_worker(
            build_vcs_project_completion_entries,
            name="prompt-vcs-project-catalog",
            thread=True,
        )

"""Accept, move, and delete behavior for prompt file completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_base import FileCompletionBaseMixin
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_skeleton,
)
from sase.xprompt.vcs_project_completion import (
    VcsProjectEntry,
    apply_vcs_project_selection,
)


class FileCompletionAcceptMixin(FileCompletionBaseMixin):
    """Mixin providing completion navigation and acceptance behavior."""

    if TYPE_CHECKING:

        def _try_file_completion_tab(self) -> bool: ...

    def _accept_vcs_project_completion(self, selected: CompletionCandidate) -> bool:
        """Apply the canonical expansion for the selected project candidate."""
        entry = selected.metadata
        if not isinstance(entry, VcsProjectEntry):
            # The empty project/PR placeholder is not selectable.
            self._clear_file_completion()
            return False
        trigger = self._get_vcs_project_trigger()
        if trigger is None:
            self._clear_file_completion()
            return False
        old_text = self.text
        new_text = apply_vcs_project_selection(
            old_text, trigger.span, entry.display_tag
        )
        self._replace_absolute_range(0, len(old_text), new_text)
        self._clear_file_completion()
        return True

    def _accept_xprompt_completion_candidate(
        self,
        selected: CompletionCandidate,
        row: int,
        start: int,
        end: int,
    ) -> bool:
        """Accept an xprompt candidate using its completion skeleton when eligible."""
        if not isinstance(selected.metadata, XPromptAssistEntry):
            return False
        if not selected.insertion.startswith("#"):
            return False

        expanded = self._expand_snippet_template_at_range(
            xprompt_completion_skeleton(selected.metadata),
            (row, start),
            (row, end),
        )
        if expanded:
            self._note_optional_xprompt_spacer(selected.metadata)
        return expanded

    def _refresh_xprompt_completion_skeleton_hint(
        self,
        selected: CompletionCandidate,
    ) -> None:
        """Refresh argument hints from the just-accepted xprompt metadata."""
        if not isinstance(selected.metadata, XPromptAssistEntry):
            self._clear_xprompt_arg_hint()
            return
        cursor_offset = self._absolute_offset(self.cursor_location)
        hint = detect_xprompt_arg_hint_at_cursor(
            self.text,
            cursor_offset,
            [selected.metadata],
        )
        if hint is None:
            self._clear_xprompt_arg_hint()
            return
        self._active_xprompt_arg_hint = hint
        self._show_xprompt_arg_hint(hint)

    def _move_file_completion(self, delta: int) -> bool:
        """Move highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        size = len(self._file_completion_candidates)
        self._file_completion_index = (self._file_completion_index + delta) % size
        if self._completion_kind == "jinja":
            result = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            self._update_file_completion_panel("" if result is None else result.prefix)
            return True
        if self._completion_kind == VCS_PROJECT_COMPLETION_KIND:
            trigger = self._get_vcs_project_trigger()
            self._update_file_completion_panel("" if trigger is None else trigger.query)
            return True
        ctx = self._get_token_context()
        self._update_file_completion_panel("" if ctx is None else ctx[3])
        return True

    def _accept_file_completion(self) -> bool:
        """Accept currently highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        selected = self._file_completion_candidates[self._file_completion_index]
        if self._completion_kind == VCS_PROJECT_COMPLETION_KIND:
            return self._accept_vcs_project_completion(selected)
        if self._completion_kind == "jinja":
            result = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            if result is None:
                self._clear_file_completion()
                return False
            self._replace_absolute_range(
                result.replacement_start,
                result.replacement_end,
                selected.insertion,
            )
            self._clear_file_completion()
            return True
        if self._completion_kind == "file_history":
            row, col = self.cursor_location
            self._replace_via_keyboard(selected.insertion, (row, col), (row, col))
            self.cursor_location = (row, col + len(selected.insertion))
            self._clear_file_completion()
            return True
        ctx = self._get_token_context()
        if ctx is None:
            self._clear_file_completion()
            return False
        row, start, end, _token = ctx
        accepted_kind = self._completion_kind
        used_xprompt_skeleton = (
            accepted_kind == "xprompt"
            and self._accept_xprompt_completion_candidate(selected, row, start, end)
        )
        if not used_xprompt_skeleton:
            self._replace_token_text(row, start, end, selected.insertion)
        # Directory drill-down: open completion for the accepted directory.
        if selected.is_dir and self._completion_kind in ("file", "xprompt_arg_path"):
            self._file_completion_active = False
            self._file_completion_candidates = []
            self._file_completion_index = 0
            if not self._try_file_completion_tab():
                self._clear_file_completion()
        else:
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            if accepted_kind == "xprompt":
                if used_xprompt_skeleton:
                    self._refresh_xprompt_completion_skeleton_hint(selected)
                else:
                    self._clear_xprompt_arg_hint()
            elif accepted_kind.startswith("xprompt_arg_"):
                self._refresh_xprompt_arg_hint_from_cursor()
            else:
                self._clear_xprompt_arg_hint()
        return True

    def _delete_selected_file_completion(self) -> bool:
        """Delete the highlighted entry from file-history completion."""
        if not self._file_completion_active:
            return False
        if self._completion_kind != "file_history":
            return False
        if not self._file_completion_candidates:
            return False

        from sase.history.file_references import remove_file_reference

        idx = self._file_completion_index
        if idx >= len(self._file_completion_candidates):
            return False

        victim = self._file_completion_candidates[idx].insertion
        remove_file_reference(victim)

        del self._file_completion_candidates[idx]
        if not self._file_completion_candidates:
            self._clear_file_completion()
            return True

        self._file_completion_index = min(
            idx, len(self._file_completion_candidates) - 1
        )
        self._update_file_completion_panel("")
        return True

"""Accept and move behavior for manual prompt completion.

Kind-specific accept helpers and delete handlers live in sibling modules.
This module keeps completion navigation and the accept dispatcher, and
preserves the original import surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_accept_delete import (
    FileCompletionAcceptDeleteMixin,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    artifact_ref_next_selectable_index,
)
from sase.ace.tui.widgets.directive_completion import (
    is_directive_catalog_placeholder,
)
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionPlaceholder,
)
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.ace.tui.widgets.model_alias_completion import (
    MODEL_ALIAS_COMPLETION_KIND,
)
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_COMPLETION_KIND,
)
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
)
from sase.ace.tui.widgets.prompt_word_completion import (
    PROMPT_WORD_COMPLETION_KIND,
    word_range_at_cursor,
)
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_ref_completion import VCS_REF_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_repo_completion import VCS_REPO_COMPLETION_KIND


class FileCompletionAcceptMixin(FileCompletionAcceptDeleteMixin):
    """Mixin providing completion navigation and acceptance behavior."""

    if TYPE_CHECKING:

        def _try_file_completion_tab(self) -> bool: ...
        def _try_auto_directive_arg_completion(self) -> bool: ...

    def _move_file_completion(self, delta: int) -> bool:
        """Move highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        self._completion_selection_moved = True
        self._artifact_ref_completion_force = False
        if self._completion_kind == ARTIFACT_REF_COMPLETION_KIND:
            self._file_completion_index = artifact_ref_next_selectable_index(
                self._file_completion_candidates,
                self._file_completion_index,
                delta,
            )
        else:
            size = len(self._file_completion_candidates)
            self._file_completion_index = (self._file_completion_index + delta) % size
        if self._completion_kind == "jinja":
            jinja_result = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            self._update_file_completion_panel(
                "" if jinja_result is None else jinja_result.prefix
            )
            return True
        if self._completion_kind == PLACEHOLDER_COMPLETION_KIND:
            placeholder_result = self._placeholder_completion_at_cursor(
                include_common_when_prefix_empty=(
                    self._placeholder_completion_includes_common_at_empty_prefix()
                ),
            )
            self._update_file_completion_panel(
                "" if placeholder_result is None else placeholder_result.prefix
            )
            return True
        if self._completion_kind == PROMPT_WORD_COMPLETION_KIND:
            result = self._prompt_word_completion_result(
                self._absolute_offset(self.cursor_location),
            )
            self._update_file_completion_panel("" if result is None else result.prefix)
            return True
        if self._completion_kind == HISTORY_WORD_COMPLETION_KIND:
            result = (
                None
                if self._history_word_cache_is_cold()
                else self._build_history_word_result(
                    self._absolute_offset(self.cursor_location),
                )
            )
            if result is not None:
                prefix = result.prefix
            else:
                cursor_offset = self._absolute_offset(self.cursor_location)
                word_range = word_range_at_cursor(self.text, cursor_offset)
                prefix = (
                    ""
                    if word_range is None
                    else self.text[word_range[0] : cursor_offset]
                )
            self._update_file_completion_panel(prefix)
            return True
        if self._completion_kind == VCS_PROJECT_COMPLETION_KIND:
            project_trigger = self._get_vcs_project_trigger()
            self._update_file_completion_panel(
                "" if project_trigger is None else project_trigger.query
            )
            return True
        if self._completion_kind == VCS_REF_COMPLETION_KIND:
            ref_trigger = self._get_vcs_ref_trigger()
            self._update_file_completion_panel(
                "" if ref_trigger is None else ref_trigger.query
            )
            return True
        if self._completion_kind == VCS_REPO_COMPLETION_KIND:
            repo_trigger = self._get_vcs_repo_trigger()
            self._update_file_completion_panel(
                "" if repo_trigger is None else repo_trigger.query
            )
            return True
        if self._completion_kind == ARTIFACT_REF_COMPLETION_KIND:
            artifact_ctx = self._get_artifact_ref_completion_context()
            self._update_file_completion_panel(
                "" if artifact_ctx is None else artifact_ctx.prefix
            )
            return True
        if self._completion_kind == MODEL_ALIAS_COMPLETION_KIND:
            alias_context = self._get_model_alias_completion_context()
            self._update_file_completion_panel(
                "" if alias_context is None else alias_context.query
            )
            return True
        if self._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND:
            explicit_context = self._get_model_explicit_completion_context()
            self._update_file_completion_panel(
                "" if explicit_context is None else explicit_context.query
            )
            return True
        ctx = self._get_token_context()
        self._update_file_completion_panel("" if ctx is None else ctx[3])
        return True

    def _accept_file_completion(self) -> bool:
        """Accept currently highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        selected = self._file_completion_candidates[self._file_completion_index]
        if is_directive_catalog_placeholder(selected):
            return False
        if self._completion_kind == VCS_PROJECT_COMPLETION_KIND:
            return self._accept_vcs_project_completion(selected)
        if self._completion_kind == VCS_REF_COMPLETION_KIND:
            return self._accept_vcs_ref_completion(selected)
        if self._completion_kind == VCS_REPO_COMPLETION_KIND:
            return self._accept_vcs_repo_completion(selected)
        if self._completion_kind == ARTIFACT_REF_COMPLETION_KIND:
            return self._accept_artifact_ref_completion(selected)
        if self._completion_kind == MODEL_ALIAS_COMPLETION_KIND:
            return self._accept_model_alias_completion(selected)
        if self._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND:
            return self._accept_model_explicit_completion(selected)
        if self._completion_kind == "jinja":
            jinja_result = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            if jinja_result is None:
                self._clear_file_completion()
                return False
            self._replace_absolute_range(
                jinja_result.replacement_start,
                jinja_result.replacement_end,
                selected.insertion,
            )
            self._clear_file_completion()
            return True
        if self._completion_kind == PLACEHOLDER_COMPLETION_KIND:
            placeholder_result = self._placeholder_completion_at_cursor(
                include_common_when_prefix_empty=(
                    self._placeholder_completion_includes_common_at_empty_prefix()
                ),
            )
            if placeholder_result is None:
                self._clear_file_completion()
                return False
            replacement = selected.insertion
            if placeholder_result.append_closing_bracket:
                replacement += ">"
            self._replace_absolute_range(
                placeholder_result.replacement_start,
                placeholder_result.replacement_end,
                replacement,
            )
            self.cursor_location = self._location_from_absolute(
                placeholder_result.replacement_start + len(selected.insertion) + 1
            )
            self._clear_file_completion()
            return True
        if self._completion_kind == PROMPT_WORD_COMPLETION_KIND:
            result = self._prompt_word_completion_result(
                self._absolute_offset(self.cursor_location),
            )
            if result is None:
                self._clear_file_completion()
                return False
            if selected.insertion not in {
                candidate.insertion for candidate in result.candidates
            }:
                self._clear_file_completion()
                return False
            self._commit_word_completion(result, selected.insertion)
            self._clear_file_completion()
            return True
        if self._completion_kind == HISTORY_WORD_COMPLETION_KIND:
            if isinstance(selected.metadata, HistoryWordCompletionPlaceholder):
                self._clear_file_completion()
                return False
            if self._history_word_cache_is_cold():
                self._clear_file_completion()
                return False
            result = self._build_history_word_result(
                self._absolute_offset(self.cursor_location),
            )
            if result is None:
                self._clear_file_completion()
                return False
            self._commit_word_completion(result, selected.insertion)
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
        used_directive_template = (
            accepted_kind == "directive"
            and self._accept_directive_completion_candidate(selected, row, start, end)
        )
        if not (used_xprompt_skeleton or used_directive_template):
            self._replace_token_text(row, start, end, selected.insertion)
        # Directory drill-down: open completion for the accepted directory/provider.
        if selected.is_dir and self._completion_kind in (
            "file",
            "xprompt_arg_path",
            "directive_arg",
        ):
            self._file_completion_active = False
            self._file_completion_candidates = []
            self._file_completion_index = 0
            reopened = (
                self._try_auto_directive_arg_completion()
                if self._completion_kind == "directive_arg"
                else self._try_file_completion_tab()
            )
            if not reopened:
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

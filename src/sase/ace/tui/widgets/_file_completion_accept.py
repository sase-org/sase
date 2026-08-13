"""Accept, move, and delete behavior for manual prompt completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_base import FileCompletionBaseMixin
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionPlaceholder,
    build_history_word_completion_result,
)
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
)
from sase.ace.tui.widgets.prompt_word_completion import (
    PROMPT_WORD_COMPLETION_KIND,
    word_range_at_cursor,
)
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_ref_completion import VCS_REF_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_repo_completion import VCS_REPO_COMPLETION_KIND
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_skeleton,
)
from sase.workspace_provider import VcsNamespaceEntry, VcsRepoEntry
from sase.xprompt.vcs_project_completion import (
    VcsProjectEntry,
    apply_vcs_project_selection,
)
from sase.xprompt.vcs_ref_completion import apply_vcs_ref_selection
from sase.xprompt.vcs_repo_completion import apply_vcs_repo_selection


class FileCompletionAcceptMixin(FileCompletionBaseMixin):
    """Mixin providing completion navigation and acceptance behavior."""

    if TYPE_CHECKING:

        def _try_file_completion_tab(self) -> bool: ...
        def _try_vcs_repo_completion(self) -> bool: ...
        def _try_artifact_ref_completion(self, *, force: bool = False) -> bool: ...

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

    def _accept_vcs_repo_completion(self, selected: CompletionCandidate) -> bool:
        """Apply the canonical expansion for the selected repository."""
        entry = selected.metadata
        if not isinstance(entry, VcsRepoEntry):
            self._clear_file_completion()
            return False
        trigger = self._get_vcs_repo_trigger()
        if trigger is None:
            self._clear_file_completion()
            return False
        old_text = self.text
        new_text = apply_vcs_repo_selection(old_text, trigger, entry.ref)
        self._replace_absolute_range(0, len(old_text), new_text)
        self._clear_file_completion()
        return True

    def _accept_vcs_ref_completion(self, selected: CompletionCandidate) -> bool:
        """Apply the canonical token-local expansion for a VCS ref-root row."""
        metadata = selected.metadata
        if isinstance(metadata, VcsProjectEntry):
            selected_ref = metadata.name
            chain = False
        elif isinstance(metadata, VcsNamespaceEntry):
            selected_ref = metadata.name.rstrip("/") + "/"
            chain = True
        else:
            # The empty ref placeholder is not selectable.
            self._clear_file_completion()
            return False

        trigger = self._get_vcs_ref_trigger()
        if trigger is None:
            self._clear_file_completion()
            return False

        old_text = self.text
        new_text = apply_vcs_ref_selection(
            old_text,
            trigger,
            selected_ref,
            chain=chain,
        )
        cursor_offset = _vcs_ref_accept_cursor_offset(
            old_text,
            trigger.value_span[0],
            trigger.value_span[1],
            selected_ref,
            separator=trigger.separator,
            chain=chain,
        )
        self._replace_absolute_range(0, len(old_text), new_text)
        self.cursor_location = self._location_from_absolute(cursor_offset)

        self._clear_file_completion()
        if chain and not self._try_vcs_repo_completion():
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

        # A required-text ``::`` skeleton becomes ``:: `` only when the accepted
        # token ends the line; an inline accept keeps ``::`` so the following text
        # supplies the single delimiter instead of doubling the space.
        line = self.document.get_line(row)
        append_text_arg_space = end == len(line)
        next_char = line[end] if end < len(line) else None
        expanded = self._expand_snippet_template_at_range(
            xprompt_completion_skeleton(
                selected.metadata,
                append_text_arg_space=append_text_arg_space,
                next_char=next_char,
            ),
            (row, start),
            (row, end),
            session_policy="nest",
        )
        if expanded:
            self._note_xprompt_completion_spacer(selected.metadata)
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
        self._completion_selection_moved = True
        self._artifact_ref_completion_force = False
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
            words = self._history_prompt_words()
            result = (
                None
                if words is None
                else build_history_word_completion_result(
                    self.text,
                    self._absolute_offset(self.cursor_location),
                    words,
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
        if self._completion_kind == VCS_REF_COMPLETION_KIND:
            return self._accept_vcs_ref_completion(selected)
        if self._completion_kind == VCS_REPO_COMPLETION_KIND:
            return self._accept_vcs_repo_completion(selected)
        if self._completion_kind == ARTIFACT_REF_COMPLETION_KIND:
            return self._accept_artifact_ref_completion(selected)
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
            self._replace_absolute_range(
                result.replacement_start,
                result.replacement_end,
                selected.insertion,
            )
            self._clear_file_completion()
            return True
        if self._completion_kind == HISTORY_WORD_COMPLETION_KIND:
            if isinstance(selected.metadata, HistoryWordCompletionPlaceholder):
                self._clear_file_completion()
                return False
            words = self._history_prompt_words()
            if words is None:
                self._clear_file_completion()
                return False
            result = build_history_word_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
                words,
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

    def _accept_artifact_ref_completion(
        self,
        selected: CompletionCandidate,
    ) -> bool:
        """Accept a kind boundary or replace one complete payload context."""
        context = self._get_artifact_ref_completion_context()
        if context is None:
            self._clear_file_completion()
            return False
        if context.stage == "kind":
            metadata = selected.metadata
            if isinstance(metadata, AtReferenceFileCompletionMetadata):
                self._replace_absolute_range(
                    context.replacement_start,
                    context.replacement_end,
                    selected.insertion,
                )
                self._clear_file_completion()
                if metadata.is_dir:
                    self._try_artifact_ref_completion()
                return True
            if not isinstance(metadata, ArtifactRefKindCompletionMetadata):
                self._clear_file_completion()
                return False
            self._replace_absolute_range(
                context.replacement_start,
                context.replacement_end,
                selected.insertion,
            )
            self._clear_file_completion()
            self._try_artifact_ref_completion()
            return True

        metadata = selected.metadata
        if not isinstance(metadata, ArtifactRefPayloadCompletionMetadata):
            self._clear_file_completion()
            return False
        result = self._artifact_ref_completion_result()
        if result is None or selected.insertion not in {
            candidate.insertion for candidate in result.candidates
        }:
            self._clear_file_completion()
            return False
        self._replace_absolute_range(
            context.replacement_start,
            context.replacement_end,
            selected.insertion,
        )
        self._clear_file_completion()
        return True

    def _delete_selected_file_completion(self) -> bool:
        """Delete the highlighted durable completion entry."""
        if (
            not self._file_completion_active
            or not self._file_completion_candidates
            or not self._completion_supports_delete()
        ):
            return False

        idx = self._file_completion_index
        if idx >= len(self._file_completion_candidates):
            return False
        selected = self._file_completion_candidates[idx]

        if self._completion_kind == "file_history":
            return self._delete_selected_file_history_completion(idx, selected)
        if self._completion_kind == HISTORY_WORD_COMPLETION_KIND:
            return self._delete_selected_history_word_completion(idx, selected)
        if self._completion_kind == PLACEHOLDER_COMPLETION_KIND:
            return self._delete_selected_placeholder_completion(idx, selected)
        return False

    def _completion_supports_delete(self) -> bool:
        """Return whether the active completion kind handles ``Ctrl+D``."""
        return self._completion_kind in {
            "file_history",
            HISTORY_WORD_COMPLETION_KIND,
            PLACEHOLDER_COMPLETION_KIND,
        }

    def _delete_selected_file_history_completion(
        self,
        idx: int,
        selected: CompletionCandidate,
    ) -> bool:
        """Delete one recent-file completion synchronously."""
        from sase.history.file_references import remove_file_reference

        victim = selected.insertion
        remove_file_reference(victim)
        self._remove_completion_candidate_locally(idx)
        self._notify_completion_delete(f"Deleted recent file: {victim}")
        return True

    def _delete_selected_history_word_completion(
        self,
        idx: int,
        selected: CompletionCandidate,
    ) -> bool:
        """Optimistically suppress one prompt-history word."""
        if isinstance(selected.metadata, HistoryWordCompletionPlaceholder):
            return False

        from sase.ace.tui.util.io_async import schedule_persist
        from sase.history.prompt_word_deletions import delete_prompt_word

        word = selected.insertion
        forget = getattr(self.app, "forget_history_prompt_word", None)
        if callable(forget):
            forget(word)
        else:
            self._remove_completion_candidate_locally(idx)
        self._notify_completion_delete(f"Deleted history word: {word}")

        warm = getattr(self.app, "warm_history_prompt_words", None)
        schedule_persist(
            self.app,
            delete_prompt_word,
            word,
            error_label="Deleting history word",
            on_error=(lambda _exc: warm()) if callable(warm) else None,
        )
        return True

    def _delete_selected_placeholder_completion(
        self,
        idx: int,
        selected: CompletionCandidate,
    ) -> bool:
        """Optimistically remove one saved common placeholder."""
        metadata = selected.metadata
        if not (
            isinstance(metadata, PlaceholderCompletionMetadata)
            and metadata.source == "common"
        ):
            self._notify_completion_delete(
                "This placeholder comes from the current prompt, not the saved list"
            )
            return True

        from sase.ace.tui.util.io_async import schedule_persist
        from sase.history.prompt_placeholders import remove_common_placeholder

        text = selected.insertion
        forget = getattr(self.app, "forget_common_placeholder", None)
        if callable(forget):
            forget(text)
        else:
            self._remove_completion_candidate_locally(idx)
        self._notify_completion_delete(f"Deleted saved placeholder: <{text}>")

        warm = getattr(self.app, "warm_common_placeholders", None)
        schedule_persist(
            self.app,
            remove_common_placeholder,
            text,
            error_label="Deleting saved placeholder",
            on_error=(lambda _exc: warm()) if callable(warm) else None,
        )
        return True

    def _remove_completion_candidate_locally(self, idx: int) -> None:
        """Remove one row and repaint when no app-level cache hook exists."""
        del self._file_completion_candidates[idx]
        if not self._file_completion_candidates:
            self._clear_file_completion()
            return
        self._file_completion_index = min(
            idx, len(self._file_completion_candidates) - 1
        )
        self._update_file_completion_panel("")

    def _notify_completion_delete(self, message: str) -> None:
        """Show an informational deletion toast without risking the action."""
        try:
            self.app.notify(message, severity="information", markup=False)
        except Exception:
            pass


def _vcs_ref_accept_cursor_offset(
    prompt: str,
    value_start: int,
    value_end: int,
    selected_ref: str,
    *,
    separator: str,
    chain: bool,
) -> int:
    """Return cursor offset immediately after a VCS ref accept suffix."""
    if chain:
        return value_start + len(selected_ref)
    if separator == "(":
        return value_start + len(selected_ref) + 1
    suffix_length = 0 if prompt[value_end:].startswith(tuple(" \t\r\n")) else 1
    return value_start + len(selected_ref) + suffix_length

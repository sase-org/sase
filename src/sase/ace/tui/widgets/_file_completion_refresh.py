"""Refresh active manual completions after prompt cursor or text changes."""

from __future__ import annotations

from sase.ace.tui.widgets._file_completion_accept import FileCompletionAcceptMixin
from sase.ace.tui.widgets._file_completion_xprompt_args import (
    build_xprompt_arg_completion_candidates,
)
from sase.ace.tui.widgets.directive_completion import (
    build_directive_arg_completion_candidates,
    build_directive_completion_candidates,
    is_directive_like_token,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    at_reference_leading_match_count,
)
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    build_completion_candidates,
    is_path_like_token,
)
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionPlaceholder,
    build_history_word_completion_result,
    build_loading_history_words_placeholder,
)
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
)
from sase.ace.tui.widgets.prompt_word_completion import (
    PROMPT_WORD_COMPLETION_KIND,
    word_range_at_cursor,
)
from sase.ace.tui.widgets.vcs_project_completion import (
    VCS_PROJECT_COMPLETION_KIND,
    build_no_active_projects_placeholder,
    vcs_project_completion_candidates,
)
from sase.ace.tui.widgets.vcs_ref_completion import (
    VCS_REF_COMPLETION_KIND,
    build_no_known_refs_placeholder,
    vcs_ref_completion_candidates,
)
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    vcs_repo_completion_candidates,
)
from sase.ace.tui.widgets.xprompt_completion import is_xprompt_like_token


class FileCompletionRefreshMixin(FileCompletionAcceptMixin):
    """Mixin providing active completion refresh behavior."""

    def _refresh_file_completion_from_cursor(self) -> None:
        """Recompute active completions after edits or cursor movement."""
        if not self._file_completion_active:
            return

        if self._completion_kind == ARTIFACT_REF_COMPLETION_KIND:
            context = self._get_artifact_ref_completion_context()
            if context is None:
                self._clear_file_completion()
                return
            result = self._artifact_ref_completion_result()
            if result is None:
                self._warm_current_artifact_ref_completion_catalog()
                self._clear_file_completion()
                return
            if not result.candidates:
                self._clear_file_completion()
                return
            self._replace_completion_candidates_preserving_selection(result.candidates)
            self._artifact_ref_completion_stats = (
                result.payload_count,
                result.payload_total,
                result.truncated_payloads,
            )
            self._update_file_completion_panel(context.prefix)
            if self._artifact_ref_completion_force:
                if at_reference_leading_match_count(result.candidates) == 1:
                    self._accept_artifact_ref_completion(result.candidates[0])
                elif result.shared_extension:
                    self._replace_absolute_range(
                        context.query_start,
                        context.query_end,
                        f"{context.prefix}{result.shared_extension}",
                    )
                    self._try_artifact_ref_completion(force=True)
            return

        if self._completion_kind == PROMPT_WORD_COMPLETION_KIND:
            self._refresh_prompt_word_completion()
            return

        if self._completion_kind == HISTORY_WORD_COMPLETION_KIND:
            self._refresh_history_word_completion()
            return

        if self._completion_kind == PLACEHOLDER_COMPLETION_KIND:
            placeholder_result = self._placeholder_completion_at_cursor(
                include_common_when_prefix_empty=(
                    self._placeholder_completion_includes_common_at_empty_prefix()
                ),
            )
            if placeholder_result is None:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].insertion
            self._file_completion_candidates = placeholder_result.candidates
            self._file_completion_index = min(
                self._file_completion_index,
                len(placeholder_result.candidates) - 1,
            )
            if previous is not None:
                for index, candidate in enumerate(placeholder_result.candidates):
                    if candidate.insertion == previous:
                        self._file_completion_index = index
                        break
            self._update_file_completion_panel(placeholder_result.prefix)
            return

        if self._completion_kind == "jinja":
            jinja_result = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            if jinja_result is None or not jinja_result.candidates:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].insertion
            self._file_completion_candidates = jinja_result.candidates
            if previous is not None:
                for i, candidate in enumerate(jinja_result.candidates):
                    if candidate.insertion == previous:
                        self._file_completion_index = i
                        break
                else:
                    self._file_completion_index = min(
                        self._file_completion_index,
                        len(jinja_result.candidates) - 1,
                    )
            else:
                self._file_completion_index = min(
                    self._file_completion_index,
                    len(jinja_result.candidates) - 1,
                )
            self._update_file_completion_panel(jinja_result.prefix)
            return

        if self._completion_kind == VCS_PROJECT_COMPLETION_KIND:
            project_trigger = self._get_vcs_project_trigger()
            if project_trigger is None:
                self._clear_file_completion()
                return
            candidates, catalog_empty = vcs_project_completion_candidates(
                project_trigger.query
            )
            if catalog_empty:
                self._file_completion_candidates = [
                    build_no_active_projects_placeholder()
                ]
                self._file_completion_index = 0
                self._update_file_completion_panel(project_trigger.query)
                return
            if not candidates:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].name
            self._file_completion_candidates = candidates
            self._file_completion_index = 0
            if previous is not None:
                for i, candidate in enumerate(candidates):
                    if candidate.name == previous:
                        self._file_completion_index = i
                        break
            self._update_file_completion_panel(project_trigger.query)
            return

        if self._completion_kind == VCS_REF_COMPLETION_KIND:
            ref_trigger = self._get_vcs_ref_trigger()
            if ref_trigger is None:
                self._clear_file_completion()
                return
            candidates, source_empty, has_namespaces = vcs_ref_completion_candidates(
                ref_trigger.workflow,
                ref_trigger.query,
            )
            self._vcs_ref_completion_has_namespaces = has_namespaces
            if source_empty:
                self._file_completion_candidates = [build_no_known_refs_placeholder()]
                self._file_completion_index = 0
                self._update_file_completion_panel(ref_trigger.query)
                return
            if not candidates:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].name
            self._file_completion_candidates = candidates
            self._file_completion_index = 0
            if previous is not None:
                for i, candidate in enumerate(candidates):
                    if candidate.name == previous:
                        self._file_completion_index = i
                        break
            self._update_file_completion_panel(ref_trigger.query)
            return

        if self._completion_kind == VCS_REPO_COMPLETION_KIND:
            repo_trigger = self._get_vcs_repo_trigger()
            if repo_trigger is None:
                self._clear_file_completion()
                return
            repo_result = self._vcs_repo_completion_result
            if repo_result is None:
                self._update_file_completion_panel(repo_trigger.query)
                return
            candidates, used_placeholder = vcs_repo_completion_candidates(
                repo_result,
                repo_trigger.query,
                repo_trigger.namespace,
            )
            if not candidates and not used_placeholder:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].name
            self._file_completion_candidates = candidates
            self._file_completion_index = 0
            if previous is not None:
                for i, candidate in enumerate(candidates):
                    if candidate.name == previous:
                        self._file_completion_index = i
                        break
            self._update_file_completion_panel(repo_trigger.query)
            return

        # file_history mode has no active token - any edit that creates one
        # at the cursor dismisses. Cursor movement within whitespace is fine.
        if self._completion_kind == "file_history":
            if self._extract_token_around_cursor() is not None:
                self._clear_file_completion()
            return

        base_dir = self._prompt_completion_base_dir()
        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].insertion

        if self._completion_kind == "directive_arg":
            directive_arg_ctx = self._get_directive_arg_token_context()
            if directive_arg_ctx is None:
                self._clear_file_completion()
                return
            (
                _row,
                _start,
                _end,
                directive_name,
                token,
                selected_values,
            ) = directive_arg_ctx
            candidates, _shared = build_directive_arg_completion_candidates(
                directive_name,
                token,
                agent_candidates=(
                    self._snapshot_agent_completion_candidates()
                    if directive_name == "wait"
                    else None
                ),
                selected_values=selected_values,
            )
        elif self._completion_kind == "xprompt":
            xprompt_ctx = self._get_xprompt_token_context()
            if xprompt_ctx is None:
                self._clear_file_completion()
                return
            _row, span = xprompt_ctx
            token = span.token
            candidates, _shared = self._build_xprompt_completion_candidates(
                token,
                inline_reference_only=span.clamped,
            )
        else:
            ctx = self._get_token_context()
            if ctx is None:
                self._clear_file_completion()
                return

            _row, _start, _end, token = ctx
            if self._completion_kind == "directive":
                candidates, _shared = build_directive_completion_candidates(token)
            elif self._completion_kind.startswith("xprompt_arg_"):
                arg_ctx = self._get_xprompt_arg_completion_context()
                if arg_ctx is None:
                    self._clear_file_completion()
                    return
                candidates, _shared = build_xprompt_arg_completion_candidates(
                    arg_ctx,
                    base_dir=base_dir,
                    agent_candidates=(
                        self._snapshot_agent_completion_candidates()
                        if arg_ctx.completion_kind == "xprompt_arg_agent"
                        else None
                    ),
                )
            else:
                candidates, _shared = build_completion_candidates(
                    token,
                    base_dir=base_dir,
                )
        if not candidates:
            self._clear_file_completion()
            return

        self._file_completion_candidates = candidates
        if previous is not None:
            for i, candidate in enumerate(candidates):
                if candidate.insertion == previous:
                    self._file_completion_index = i
                    break
            else:
                self._file_completion_index = min(
                    self._file_completion_index, len(candidates) - 1
                )
        else:
            self._file_completion_index = min(
                self._file_completion_index, len(candidates) - 1
            )

        self._update_file_completion_panel(token)

    def _refresh_prompt_word_completion(self) -> None:
        """Refresh the active prompt-local word menu entirely in memory."""
        cursor_offset = self._absolute_offset(self.cursor_location)
        result = self._prompt_word_completion_result(cursor_offset)
        if result is None:
            settings = self._prompt_completion_settings()
            if settings.history_word_count <= 0 or not callable(
                getattr(self.app, "history_prompt_words", None)
            ):
                self._clear_file_completion()
                return
            history_words_cold = self._history_prompt_words() is None
            self._completion_kind = HISTORY_WORD_COMPLETION_KIND
            self._refresh_history_word_completion()
            if (
                history_words_cold
                and self._file_completion_active
                and self._completion_kind == HISTORY_WORD_COMPLETION_KIND
            ):
                self._schedule_history_word_completion_load()
            return
        if self._structured_completion_claims_cursor():
            self._clear_file_completion()
            return

        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].insertion

        self._file_completion_candidates = result.candidates
        self._file_completion_index = min(
            self._file_completion_index,
            len(result.candidates) - 1,
        )
        if previous is not None:
            for index, candidate in enumerate(result.candidates):
                if candidate.insertion == previous:
                    self._file_completion_index = index
                    break
        self._update_file_completion_panel(result.prefix)

    def _refresh_history_word_completion(
        self,
        words: list[str] | None = None,
    ) -> None:
        """Refresh history words, preserving structured and local precedence."""
        if self._structured_completion_claims_cursor():
            self._clear_file_completion()
            return

        cursor_offset = self._absolute_offset(self.cursor_location)
        local_result = self._prompt_word_completion_result(cursor_offset)
        if local_result is not None:
            self._completion_kind = PROMPT_WORD_COMPLETION_KIND
            self._replace_completion_candidates_preserving_selection(
                local_result.candidates
            )
            self._update_file_completion_panel(local_result.prefix)
            return

        if words is None:
            words = self._history_prompt_words()
        if words is None:
            word_range = word_range_at_cursor(self.text, cursor_offset)
            if word_range is None:
                self._clear_file_completion()
                return
            start, _end = word_range
            if not self._file_completion_candidates or not isinstance(
                self._file_completion_candidates[0].metadata,
                HistoryWordCompletionPlaceholder,
            ):
                self._file_completion_candidates = [
                    build_loading_history_words_placeholder()
                ]
                self._file_completion_index = 0
            self._update_file_completion_panel(self.text[start:cursor_offset])
            return

        result = build_history_word_completion_result(
            self.text,
            cursor_offset,
            words,
        )
        if result is None:
            self._clear_file_completion()
            return
        self._replace_completion_candidates_preserving_selection(result.candidates)
        self._update_file_completion_panel(result.prefix)

    def _replace_completion_candidates_preserving_selection(
        self,
        candidates: list[CompletionCandidate],
    ) -> None:
        """Replace completion rows while retaining the selected insertion."""
        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].insertion
        self._file_completion_candidates = candidates
        self._file_completion_index = min(
            self._file_completion_index,
            len(candidates) - 1,
        )
        if previous is not None:
            for index, candidate in enumerate(candidates):
                if candidate.insertion == previous:
                    self._file_completion_index = index
                    break

    def _structured_completion_claims_cursor(self) -> bool:
        """Return whether an existing provider shadows prompt-word fallback."""
        # Precedence only asks "is there a placeholder context here", so a bare
        # ``<`` backed by saved tags still shadows the prompt-word fallback.
        if (
            self._placeholder_completion_at_cursor(
                include_common_when_prefix_empty=True,
            )
            is not None
        ):
            return True
        if self._get_vcs_project_trigger() is not None:
            return True
        if self._get_vcs_repo_trigger() is not None:
            return True
        if self._get_vcs_ref_trigger() is not None:
            return True
        artifact_ctx = self._get_artifact_ref_completion_context()
        if artifact_ctx is not None:
            return True

        cursor_offset = self._absolute_offset(self.cursor_location)
        if build_jinja_completion_result(self.text, cursor_offset) is not None:
            return True
        if self._get_directive_arg_token_context() is not None:
            return True
        if self._get_xprompt_arg_completion_context() is not None:
            return True

        directive_ctx = self._get_directive_token_context()
        if directive_ctx is not None and is_directive_like_token(directive_ctx[3]):
            return True
        token_info = self._extract_token_around_cursor()
        if token_info is None:
            return False
        raw_token = token_info[2]
        return is_xprompt_like_token(raw_token) or is_path_like_token(raw_token)

"""Manual Ctrl+T prompt completion dispatch and handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_refresh import FileCompletionRefreshMixin
from sase.ace.tui.widgets._file_completion_xprompt_args import (
    build_xprompt_arg_completion_candidates,
    effective_xprompt_arg_token,
)
from sase.ace.tui.widgets.directive_completion import (
    build_directive_completion_candidates,
    is_directive_catalog_placeholder,
    is_directive_like_token,
)
from sase.ace.tui.widgets.file_completion import (
    build_completion_candidates,
    is_path_like_token,
)
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    build_loading_history_words_placeholder,
)
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.ace.tui.widgets.placeholder_completion import (
    placeholder_lone_leading_match,
)
from sase.ace.tui.widgets.prompt_word_completion import (
    PROMPT_WORD_COMPLETION_KIND,
    word_range_at_cursor,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets.jinja_completion import JinjaCompletionResult
    from sase.ace.tui.widgets.placeholder_completion import (
        PlaceholderCompletionResult,
    )
    from sase.ace.tui.widgets.xprompt_arg_assist import XPromptArgCompletionContext


class FileCompletionTabMixin(FileCompletionRefreshMixin):
    """Mixin providing manual Ctrl+T completion behavior."""

    if TYPE_CHECKING:

        def _placeholder_completion_at_cursor(
            self,
            *,
            include_common_when_prefix_empty: bool = False,
        ) -> PlaceholderCompletionResult | None: ...
        def _open_placeholder_completion(
            self,
            result: PlaceholderCompletionResult,
            *,
            trigger: str = "auto",
        ) -> None: ...
        def _try_vcs_project_completion(self) -> bool: ...
        def _try_vcs_repo_completion(self) -> bool: ...
        def _try_vcs_ref_completion(self, *, force: bool = False) -> bool: ...
        def _try_artifact_ref_completion(self, *, force: bool = False) -> bool: ...
        def _try_artifact_ref_completion_tab(self) -> bool: ...
        def _try_auto_directive_arg_completion(self) -> bool: ...
        def _try_file_history_completion(self) -> bool: ...

    def _try_file_completion_tab(self) -> bool:
        """Dispatch manual Ctrl+T completion for the current prompt context.

        An explicit request is exhaustive: a bare ``<`` shows the full saved
        list. A lone match in the highest-priority source group is inserted
        directly, so saved tags never suppress direct acceptance of a lone
        prompt-local match.
        """
        placeholder_result = self._placeholder_completion_at_cursor(
            include_common_when_prefix_empty=True,
        )
        if placeholder_result is not None:
            self._open_placeholder_completion(placeholder_result, trigger="manual")
            if placeholder_lone_leading_match(placeholder_result):
                self._accept_file_completion()
            return True
        if self._try_vcs_project_completion():
            return True
        if self._try_vcs_repo_completion():
            return True
        if self._try_vcs_ref_completion(force=True):
            return True

        cursor_offset = self._absolute_offset(self.cursor_location)
        jinja_result = build_jinja_completion_result(self.text, cursor_offset)
        if jinja_result is not None:
            return self._try_jinja_completion_tab(jinja_result)

        clause_ctx = self._directive_clause_at_cursor()
        if clause_ctx is not None and not clause_ctx[1].is_name:
            self._completion_kind = "directive_arg"
            row, clause = clause_ctx
            start, end, token = clause.start, clause.end, clause.token
            candidates, shared_extension = self._build_live_directive_arg_candidates(
                clause
            )
        else:
            arg_ctx = self._get_xprompt_arg_completion_context()
            if arg_ctx is not None:
                return self._try_xprompt_arg_completion_tab(arg_ctx)
            if self._try_artifact_ref_completion_tab():
                return True

            self._clear_xprompt_arg_hint()
            directive_ctx = self._get_directive_token_context()
            if directive_ctx is not None and is_directive_like_token(directive_ctx[3]):
                self._completion_kind = "directive"
                row, start, end, token = directive_ctx
                candidates, shared_extension = build_directive_completion_candidates(
                    token
                )
            else:
                xprompt_ctx = self._get_xprompt_token_context()
                if xprompt_ctx is not None:
                    self._completion_kind = "xprompt"
                    row, span = xprompt_ctx
                    start, end, token = span.start, span.end, span.token
                    candidates, shared_extension = (
                        self._build_xprompt_completion_candidates(
                            token,
                            inline_reference_only=span.clamped,
                        )
                    )
                else:
                    token_info = self._extract_token_around_cursor()
                    if token_info is None:
                        return self._try_file_history_completion()

                    _start, _end, raw_token = token_info
                    if is_path_like_token(raw_token):
                        self._completion_kind = "file"
                        ctx = self._get_path_token_context()
                        if ctx is None:
                            self._clear_file_completion()
                            return False
                        row, start, end, token = ctx
                        candidates, shared_extension = build_completion_candidates(
                            token,
                            base_dir=self._prompt_completion_base_dir(),
                        )
                    else:
                        return self._try_prompt_word_completion_tab(cursor_offset)

        if not candidates:
            self._clear_file_completion()
            return True

        if len(candidates) == 1 and not is_directive_catalog_placeholder(candidates[0]):
            selected = candidates[0]
            accepted_kind = self._completion_kind
            used_xprompt_skeleton = (
                accepted_kind == "xprompt"
                and self._accept_xprompt_completion_candidate(selected, row, start, end)
            )
            if not used_xprompt_skeleton:
                self._replace_token_text(row, start, end, selected.insertion)
            if selected.is_dir and accepted_kind == "directive_arg":
                self._file_completion_active = False
                self._file_completion_candidates = []
                self._file_completion_index = 0
                if not self._try_auto_directive_arg_completion():
                    self._clear_file_completion(clear_xprompt_arg_hint=False)
                return True
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            if accepted_kind == "xprompt":
                if used_xprompt_skeleton:
                    self._refresh_xprompt_completion_skeleton_hint(selected)
                else:
                    self._clear_xprompt_arg_hint()
            elif accepted_kind.startswith("xprompt_arg_"):
                self._refresh_xprompt_arg_hint_from_cursor()
            return True

        if shared_extension:
            next_token = f"{token}{shared_extension}"
            self._replace_token_text(row, start, end, next_token)
            if self._completion_kind == "xprompt":
                xprompt_ctx = self._get_xprompt_token_context()
                if xprompt_ctx is None:
                    self._clear_file_completion()
                    return True
                row, span = xprompt_ctx
                start, end, token = span.start, span.end, span.token
                candidates, _ = self._build_xprompt_completion_candidates(
                    token,
                    inline_reference_only=span.clamped,
                )
            else:
                ctx = self._get_token_context()
                if ctx is None:
                    self._clear_file_completion()
                    return True
                row, start, end, token = ctx
            if self._completion_kind != "xprompt":
                if self._completion_kind == "directive":
                    candidates, _ = build_directive_completion_candidates(token)
                elif self._completion_kind == "directive_arg":
                    clause_ctx = self._directive_clause_at_cursor()
                    if clause_ctx is None or clause_ctx[1].is_name:
                        self._clear_file_completion()
                        return True
                    row, clause = clause_ctx
                    start, end, token = clause.start, clause.end, clause.token
                    candidates, _ = self._build_live_directive_arg_candidates(clause)
                elif self._completion_kind.startswith("xprompt_arg_"):
                    arg_ctx = self._get_xprompt_arg_completion_context()
                    if arg_ctx is None:
                        self._clear_file_completion()
                        return True
                    candidates, _ = build_xprompt_arg_completion_candidates(
                        arg_ctx,
                        base_dir=self._prompt_completion_base_dir(),
                        agent_candidates=(
                            self._snapshot_agent_completion_candidates()
                            if arg_ctx.completion_kind == "xprompt_arg_agent"
                            else None
                        ),
                    )
                else:
                    candidates, _ = build_completion_candidates(
                        token,
                        base_dir=self._prompt_completion_base_dir(),
                    )
            if not candidates:
                self._clear_file_completion()
                return True

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
        return True

    def _try_prompt_word_completion_tab(self, cursor_offset: int) -> bool:
        """Handle prompt-local words before falling back to history."""
        result = self._prompt_word_completion_result(cursor_offset)
        if result is None:
            return self._try_history_word_completion_tab(cursor_offset)

        self._completion_kind = PROMPT_WORD_COMPLETION_KIND
        candidates = result.candidates
        if len(candidates) == 1:
            self._commit_word_completion(result, candidates[0].insertion)
            self._clear_file_completion()
            return True

        if result.shared_extension:
            self._replace_absolute_range(
                result.replacement_start,
                result.replacement_end,
                f"{result.prefix}{result.shared_extension}",
            )
            refreshed = self._prompt_word_completion_result(
                self._absolute_offset(self.cursor_location),
            )
            if refreshed is None:
                self._clear_file_completion()
                return True
            result = refreshed
            candidates = refreshed.candidates

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(result.prefix)
        return True

    def _try_history_word_completion_tab(self, cursor_offset: int) -> bool:
        """Handle the final plain-prose Ctrl+T completion fallback."""
        settings = self._prompt_completion_settings()
        if settings.history_word_count <= 0 or not self._history_word_source_ready():
            self._clear_file_completion()
            return False

        if self._history_word_cache_is_cold():
            word_range = word_range_at_cursor(self.text, cursor_offset)
            if word_range is None:
                self._clear_file_completion()
                return False
            start, _end = word_range
            prefix = self.text[start:cursor_offset]
            self._completion_kind = HISTORY_WORD_COMPLETION_KIND
            self._file_completion_active = True
            self._file_completion_candidates = [
                build_loading_history_words_placeholder()
            ]
            self._file_completion_index = 0
            self._update_file_completion_panel(prefix)
            self._schedule_history_word_completion_load()
            return True

        result = self._build_history_word_result(cursor_offset)
        if result is None:
            self._clear_file_completion()
            return False

        self._completion_kind = HISTORY_WORD_COMPLETION_KIND
        candidates = result.candidates
        if len(candidates) == 1:
            self._commit_word_completion(result, candidates[0].insertion)
            self._clear_file_completion()
            return True

        if result.shared_extension:
            self._replace_absolute_range(
                result.replacement_start,
                result.replacement_end,
                f"{result.prefix}{result.shared_extension}",
            )
            refreshed = self._build_history_word_result(
                self._absolute_offset(self.cursor_location),
            )
            if refreshed is None:
                self._clear_file_completion()
                return True
            result = refreshed
            candidates = refreshed.candidates

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(result.prefix)
        return True

    def _try_jinja_completion_tab(self, result: JinjaCompletionResult) -> bool:
        """Handle Ctrl+T completion inside a Jinja2 tag."""
        jinja_result = result
        candidates = jinja_result.candidates
        self._completion_kind = "jinja"

        if not candidates:
            self._clear_file_completion()
            return True

        if len(candidates) == 1:
            selected = candidates[0]
            self._replace_absolute_range(
                jinja_result.replacement_start,
                jinja_result.replacement_end,
                selected.insertion,
            )
            self._clear_file_completion()
            return True

        if jinja_result.shared_extension:
            next_token = f"{jinja_result.prefix}{jinja_result.shared_extension}"
            self._replace_absolute_range(
                jinja_result.replacement_start,
                jinja_result.replacement_end,
                next_token,
            )
            refreshed = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            if refreshed is None or not refreshed.candidates:
                self._clear_file_completion()
                return True
            jinja_result = refreshed
            candidates = refreshed.candidates

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(jinja_result.prefix)
        return True

    def _try_xprompt_arg_completion_tab(
        self,
        ctx: XPromptArgCompletionContext,
    ) -> bool:
        """Handle Ctrl+T-driven completion inside xprompt argument syntax."""
        base_dir = self._prompt_completion_base_dir()
        candidates, shared_extension = build_xprompt_arg_completion_candidates(
            ctx,
            base_dir=base_dir,
            agent_candidates=(
                self._snapshot_agent_completion_candidates()
                if ctx.completion_kind == "xprompt_arg_agent"
                else None
            ),
        )
        self._completion_kind = ctx.completion_kind

        if not candidates:
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            self._refresh_xprompt_arg_hint_from_cursor()
            return True

        if len(candidates) == 1:
            selected = candidates[0]
            self._replace_absolute_range(
                ctx.value_start, ctx.value_end, selected.insertion
            )
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            self._refresh_xprompt_arg_hint_from_cursor()
            return True

        token = effective_xprompt_arg_token(ctx)
        if shared_extension:
            next_token = f"{token}{shared_extension}"
            self._replace_absolute_range(ctx.value_start, ctx.value_end, next_token)
            next_ctx = self._get_xprompt_arg_completion_context()
            if next_ctx is None:
                self._clear_file_completion(clear_xprompt_arg_hint=False)
                self._refresh_xprompt_arg_hint_from_cursor()
                return True
            candidates, _ = build_xprompt_arg_completion_candidates(
                next_ctx,
                base_dir=base_dir,
                agent_candidates=(
                    self._snapshot_agent_completion_candidates()
                    if next_ctx.completion_kind == "xprompt_arg_agent"
                    else None
                ),
            )
            ctx = next_ctx
            token = effective_xprompt_arg_token(ctx)
            self._completion_kind = ctx.completion_kind
            if not candidates:
                self._clear_file_completion(clear_xprompt_arg_hint=False)
                self._refresh_xprompt_arg_hint_from_cursor()
                return True

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
        return True

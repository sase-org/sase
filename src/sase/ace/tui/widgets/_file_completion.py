"""File path completion mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._file_completion_context import FileCompletionContextMixin
from sase.ace.tui.widgets._file_completion_xprompt_args import (
    build_xprompt_arg_completion_candidates,
    effective_xprompt_arg_token,
)
from sase.ace.tui.widgets.directive_completion import (
    build_directive_completion_candidates,
    is_directive_like_token,
)
from sase.ace.tui.widgets.file_completion import (
    MAX_VISIBLE,
    CompletionCandidate,
    build_completion_candidates,
    build_file_history_completion_candidates,
    is_path_like_token,
)
from sase.ace.tui.widgets.jinja_completion import (
    JinjaCompletionResult,
    build_jinja_completion_result,
)
from sase.ace.tui.widgets.xprompt_completion import (
    is_xprompt_like_token,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    XPromptArgCompletionContext,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_skeleton,
)
from sase.ace.tui.widgets.vcs_project_completion import (
    VCS_PROJECT_COMPLETION_KIND,
    build_no_active_projects_placeholder,
    vcs_project_completion_candidates,
)
from sase.xprompt.vcs_project_completion import (
    VcsProjectEntry,
    apply_vcs_project_selection,
    build_vcs_project_completion_entries,
)


class FileCompletionMixin(FileCompletionContextMixin):
    """Mixin providing file path completion for PromptTextArea.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    # -- Attributes and method stubs for type checking --
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
        def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None: ...
        def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _get_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _expand_snippet_template_at_range(
            self,
            template: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> bool: ...

    # -- Mixin implementation --

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

    def _try_vcs_project_completion(self) -> bool:
        """Open the ``#+`` project completion menu at a ``#+token``.

        Returns ``True`` when a ``#+`` trigger is present (menu opened,
        empty-state row shown, or query matched nothing and the menu was
        dismissed), so the caller stops dispatching other completion kinds.
        Returns ``False`` only when there is no ``#+`` trigger or the bar is not
        in prompt mode.
        """
        bar = self._find_prompt_bar()
        if bar is not None and getattr(bar, "_mode", "prompt") != "prompt":
            return False
        trigger = self._get_vcs_project_trigger()
        if trigger is None:
            return False

        candidates, catalog_empty = vcs_project_completion_candidates(trigger.query)
        if catalog_empty:
            candidates = [build_no_active_projects_placeholder()]
        elif not candidates:
            self._clear_file_completion()
            return True

        self._completion_kind = VCS_PROJECT_COMPLETION_KIND
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(trigger.query)
        return True

    def _accept_vcs_project_completion(self, selected: CompletionCandidate) -> bool:
        """Apply the canonical expansion for the selected project candidate."""
        entry = selected.metadata
        if not isinstance(entry, VcsProjectEntry):
            # The "no active projects" placeholder is not selectable.
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

        return self._expand_snippet_template_at_range(
            xprompt_completion_skeleton(selected.metadata),
            (row, start),
            (row, end),
        )

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

    def _refresh_file_completion_from_cursor(self) -> None:
        """Recompute active completions after edits or cursor movement."""
        if not self._file_completion_active:
            return

        if self._completion_kind == "jinja":
            result = build_jinja_completion_result(
                self.text,
                self._absolute_offset(self.cursor_location),
            )
            if result is None or not result.candidates:
                self._clear_file_completion()
                return
            previous = None
            if self._file_completion_candidates:
                previous = self._file_completion_candidates[
                    self._file_completion_index
                ].insertion
            self._file_completion_candidates = result.candidates
            if previous is not None:
                for i, candidate in enumerate(result.candidates):
                    if candidate.insertion == previous:
                        self._file_completion_index = i
                        break
                else:
                    self._file_completion_index = min(
                        self._file_completion_index,
                        len(result.candidates) - 1,
                    )
            else:
                self._file_completion_index = min(
                    self._file_completion_index,
                    len(result.candidates) - 1,
                )
            self._update_file_completion_panel(result.prefix)
            return

        if self._completion_kind == VCS_PROJECT_COMPLETION_KIND:
            trigger = self._get_vcs_project_trigger()
            if trigger is None:
                self._clear_file_completion()
                return
            candidates, catalog_empty = vcs_project_completion_candidates(trigger.query)
            if catalog_empty:
                self._file_completion_candidates = [
                    build_no_active_projects_placeholder()
                ]
                self._file_completion_index = 0
                self._update_file_completion_panel(trigger.query)
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
            self._update_file_completion_panel(trigger.query)
            return

        # file_history mode has no active token — any edit that creates one
        # at the cursor dismisses. Cursor movement within whitespace is fine.
        if self._completion_kind == "file_history":
            if self._extract_token_around_cursor() is not None:
                self._clear_file_completion()
            return

        ctx = self._get_token_context()
        if ctx is None:
            self._clear_file_completion()
            return

        _row, _start, _end, token = ctx
        base_dir = self._prompt_completion_base_dir()
        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].insertion
        if self._completion_kind == "xprompt":
            candidates, _shared = self._build_xprompt_completion_candidates(token)
        elif self._completion_kind == "directive":
            candidates, _shared = build_directive_completion_candidates(token)
        elif self._completion_kind.startswith("xprompt_arg_"):
            arg_ctx = self._get_xprompt_arg_completion_context()
            if arg_ctx is None:
                self._clear_file_completion()
                return
            candidates, _shared = build_xprompt_arg_completion_candidates(
                arg_ctx,
                base_dir=base_dir,
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

    def _try_file_completion_tab(self) -> bool:
        """Handle Ctrl+T-driven completion for path, xprompt, or history."""
        if self._try_vcs_project_completion():
            return True

        cursor_offset = self._absolute_offset(self.cursor_location)
        jinja_result = build_jinja_completion_result(self.text, cursor_offset)
        if jinja_result is not None:
            return self._try_jinja_completion_tab(jinja_result)

        base_dir = self._prompt_completion_base_dir()
        arg_ctx = self._get_xprompt_arg_completion_context()
        if arg_ctx is not None:
            return self._try_xprompt_arg_completion_tab(arg_ctx)

        self._clear_xprompt_arg_hint()
        directive_ctx = self._get_directive_token_context()
        if directive_ctx is not None and is_directive_like_token(directive_ctx[3]):
            self._completion_kind = "directive"
            row, start, end, token = directive_ctx
            candidates, shared_extension = build_directive_completion_candidates(token)
        else:
            token_info = self._extract_token_around_cursor()
            if token_info is None:
                return self._try_file_history_completion()

            _start, _end, raw_token = token_info

            # Determine completion kind from the raw token.
            if is_xprompt_like_token(raw_token):
                self._completion_kind = "xprompt"
                ctx = self._get_xprompt_token_context()
                if ctx is None:
                    self._clear_file_completion()
                    return False
                row, start, end, token = ctx
                candidates, shared_extension = (
                    self._build_xprompt_completion_candidates(token)
                )
            elif is_path_like_token(raw_token):
                self._completion_kind = "file"
                ctx = self._get_path_token_context()
                if ctx is None:
                    self._clear_file_completion()
                    return False
                row, start, end, token = ctx
                candidates, shared_extension = build_completion_candidates(
                    token,
                    base_dir=base_dir,
                )
            else:
                self._clear_file_completion()
                return False

        if not candidates:
            self._clear_file_completion()
            return True

        if len(candidates) == 1:
            selected = candidates[0]
            accepted_kind = self._completion_kind
            used_xprompt_skeleton = (
                accepted_kind == "xprompt"
                and self._accept_xprompt_completion_candidate(selected, row, start, end)
            )
            if not used_xprompt_skeleton:
                self._replace_token_text(row, start, end, selected.insertion)
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
            ctx = self._get_token_context()
            if ctx is None:
                self._clear_file_completion()
                return True
            row, start, end, token = ctx
            if self._completion_kind == "xprompt":
                candidates, _ = self._build_xprompt_completion_candidates(token)
            elif self._completion_kind == "directive":
                candidates, _ = build_directive_completion_candidates(token)
            elif self._completion_kind.startswith("xprompt_arg_"):
                arg_ctx = self._get_xprompt_arg_completion_context()
                if arg_ctx is None:
                    self._clear_file_completion()
                    return True
                candidates, _ = build_xprompt_arg_completion_candidates(
                    arg_ctx,
                    base_dir=base_dir,
                )
            else:
                candidates, _ = build_completion_candidates(
                    token,
                    base_dir=base_dir,
                )
            if not candidates:
                self._clear_file_completion()
                return True

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
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

    def _try_file_history_completion(self) -> bool:
        """Show the file-reference history panel at an empty cursor prefix."""
        candidates, _shared = build_file_history_completion_candidates()
        if not candidates:
            self._clear_file_completion()
            return True

        self._completion_kind = "file_history"
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel("")
        return True

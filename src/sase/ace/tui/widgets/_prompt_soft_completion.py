"""Soft prompt completion mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    extract_token_around_cursor,
)
from sase.ace.tui.widgets.prompt_completion import (
    DEFAULT_PROMPT_COMPLETION_SETTINGS,
    PromptCompletionSettings,
    PromptSoftCompletion,
    build_prompt_soft_completion,
)
from sase.ace.tui.widgets.prompt_completion_root import (
    resolve_prompt_completion_base_dir,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    merge_local_xprompt_entries,
    xprompt_completion_skeleton,
)
from sase.ace.tui.widgets.xprompt_completion import is_xprompt_like_token

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PromptSoftCompletionMixin(_MixinBase):
    """Mixin providing live soft completion for PromptTextArea.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    if TYPE_CHECKING:
        _file_completion_active: bool
        _prompt_completion_generation: int
        _prompt_completion_timer: Any | None
        _snippet_tabstops: list[int]
        _soft_completion: PromptSoftCompletion | None
        _vim_mode: str

        def _find_prompt_bar(self) -> Any: ...
        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _xprompt_arg_assist_project_from_text(self) -> str | None: ...
        def _schedule_xprompt_assist_warm(self, project: str | None) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _note_xprompt_completion_spacer(
            self,
            entry: XPromptAssistEntry,
        ) -> None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _refresh_xprompt_completion_skeleton_hint(
            self,
            selected: CompletionCandidate,
        ) -> None: ...
        def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _get_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...
        def _local_xprompt_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _expand_snippet_template_at_range(
            self,
            template: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> bool: ...
        def _replace_absolute_range(
            self,
            start_offset: int,
            end_offset: int,
            replacement: str,
        ) -> None: ...

    def _soft_completion_xprompt_entries(
        self,
        warm: list[XPromptAssistEntry] | None,
    ) -> list[XPromptAssistEntry] | None:
        """Merge live local xprompts into the *warm* catalog for soft completion.

        Returns the local helpers alone when the global catalog is still cold so
        a ``#_helper`` declared in the Frontmatter Panel soft-completes (``<ctrl+l>``)
        immediately, without waiting for the global warm pass.  Returns ``None``
        only when there is neither a warm catalog nor any local helper, so the
        existing warm-scheduling deferral is preserved untouched.
        """
        local = self._local_xprompt_assist_entries()
        if warm is None:
            return local or None
        return merge_local_xprompt_entries(warm, local)

    def _prompt_completion_settings(self) -> PromptCompletionSettings:
        """Return prompt completion settings with a default for minimal apps."""
        getter = getattr(self.app, "get_prompt_completion_settings", None)
        if callable(getter):
            value = getter()
            if isinstance(value, PromptCompletionSettings):
                return value
        return DEFAULT_PROMPT_COMPLETION_SETTINGS

    def _on_prompt_completion_context_changed(self) -> None:
        """Debounce live prompt completion after text or cursor changes."""
        self._prompt_completion_generation += 1
        self._clear_stale_soft_completion()
        self._schedule_prompt_completion_refresh()

    def _schedule_prompt_completion_refresh(self) -> None:
        settings = self._prompt_completion_settings()
        if settings.auto != "soft" or self._soft_completion_blocked():
            self._clear_soft_completion(cancel_timer=True)
            return

        if self._prompt_completion_timer is not None:
            self._prompt_completion_timer.stop()
        generation = self._prompt_completion_generation
        text = self.text
        cursor_offset = self._absolute_offset(self.cursor_location)
        self._prompt_completion_timer = self.set_timer(
            settings.debounce_ms / 1000,
            lambda: self._fire_prompt_completion_timer(
                generation,
                text,
                cursor_offset,
            ),
        )

    def _fire_prompt_completion_timer(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
    ) -> None:
        self._prompt_completion_timer = None
        if generation != self._prompt_completion_generation:
            return
        if text != self.text or cursor_offset != self._absolute_offset(
            self.cursor_location
        ):
            return
        if self._soft_completion_blocked():
            self._clear_soft_completion()
            return

        project = self._xprompt_arg_assist_project_from_text()
        entries = self._get_warm_xprompt_arg_assist_entries()
        if entries is None and self._soft_completion_may_need_xprompt_entries(
            text, cursor_offset
        ):
            self._schedule_xprompt_assist_warm(project)

        suggestion = build_prompt_soft_completion(
            text=text,
            cursor_offset=cursor_offset,
            settings=self._prompt_completion_settings(),
            xprompt_entries=self._soft_completion_xprompt_entries(entries),
            base_dir=resolve_prompt_completion_base_dir(text),
        )
        if generation != self._prompt_completion_generation:
            return
        self._set_soft_completion(suggestion)

    def _soft_completion_blocked(self) -> bool:
        if self._vim_mode != "insert":
            return True
        if self._file_completion_active or self._snippet_tabstops:
            return True
        bar = self._find_prompt_bar()
        if bar and getattr(bar, "_completion_panel_kind", None) == "jinja":
            return True
        return bool(bar and bar._mode == "feedback")

    def _soft_completion_may_need_xprompt_entries(
        self,
        text: str,
        cursor_offset: int,
    ) -> bool:
        if "#" in text:
            return True
        line_start = text.rfind("\n", 0, cursor_offset) + 1
        line_end = text.find("\n", cursor_offset)
        if line_end == -1:
            line_end = len(text)
        token_ctx = extract_token_around_cursor(
            text[line_start:line_end],
            cursor_offset - line_start,
        )
        return token_ctx is not None and is_xprompt_like_token(token_ctx[2])

    def _build_current_soft_completion(
        self,
        *,
        allow_sync_xprompt_entries: bool = False,
    ) -> PromptSoftCompletion | None:
        """Build the best soft completion for the current prompt state."""
        del allow_sync_xprompt_entries
        text = self.text
        cursor_offset = self._absolute_offset(self.cursor_location)
        settings = self._prompt_completion_settings()
        if settings.auto != "soft":
            return None

        entries: list[XPromptAssistEntry] | None = None
        may_need_xprompt_entries = self._soft_completion_may_need_xprompt_entries(
            text,
            cursor_offset,
        )
        warm_entries: list[XPromptAssistEntry] | None = None
        if may_need_xprompt_entries:
            project = self._xprompt_arg_assist_project_from_text()
            warm_entries = self._get_warm_xprompt_arg_assist_entries()
            if warm_entries is None:
                self._schedule_xprompt_assist_warm(project)
            entries = self._soft_completion_xprompt_entries(warm_entries)

        suggestion = build_prompt_soft_completion(
            text=text,
            cursor_offset=cursor_offset,
            settings=settings,
            xprompt_entries=entries,
            base_dir=resolve_prompt_completion_base_dir(text),
        )
        return suggestion

    def _set_soft_completion(self, suggestion: PromptSoftCompletion | None) -> None:
        self._soft_completion = suggestion
        bar = self._find_prompt_bar()
        if bar is None:
            return
        if suggestion is None:
            bar.hide_soft_completion()
        else:
            bar.show_soft_completion(suggestion)

    def _clear_stale_soft_completion(self) -> None:
        if self._soft_completion is not None and not self._soft_completion_is_current():
            self._clear_soft_completion()

    def _clear_soft_completion(self, *, cancel_timer: bool = False) -> None:
        if cancel_timer and self._prompt_completion_timer is not None:
            self._prompt_completion_timer.stop()
            self._prompt_completion_timer = None
        if self._soft_completion is None:
            return
        self._soft_completion = None
        bar = self._find_prompt_bar()
        if bar:
            bar.hide_soft_completion()

    def _soft_completion_is_current(self) -> bool:
        suggestion = self._soft_completion
        if suggestion is None or self._soft_completion_blocked():
            return False
        cursor_offset = self._absolute_offset(self.cursor_location)
        return (
            cursor_offset == suggestion.replacement_end
            and 0 <= suggestion.replacement_start <= suggestion.replacement_end
            and suggestion.replacement_end <= len(self.text)
            and self.text[suggestion.replacement_start : suggestion.replacement_end]
            == suggestion.replacement_token
        )

    def _accept_soft_completion(self) -> bool:
        suggestion = self._soft_completion
        if suggestion is None:
            return False
        if not self._soft_completion_is_current():
            self._clear_soft_completion(cancel_timer=True)
            return False

        selected = suggestion.candidate
        accepted_kind = suggestion.completion_kind
        start = self._location_from_absolute(suggestion.replacement_start)
        end = self._location_from_absolute(suggestion.replacement_end)
        used_xprompt_skeleton = False
        if (
            accepted_kind == "xprompt"
            and isinstance(selected.metadata, XPromptAssistEntry)
            and selected.insertion.startswith("#")
        ):
            # ``:: `` only when the replacement ends its line; an accept before
            # existing text keeps ``::`` so that text provides the delimiter.
            line = self.document.get_line(end[0])
            append_text_arg_space = end[1] == len(line)
            next_char = line[end[1]] if end[1] < len(line) else None
            used_xprompt_skeleton = self._expand_snippet_template_at_range(
                xprompt_completion_skeleton(
                    selected.metadata,
                    append_text_arg_space=append_text_arg_space,
                    next_char=next_char,
                ),
                start,
                end,
            )
            if used_xprompt_skeleton:
                self._note_xprompt_completion_spacer(selected.metadata)

        if not used_xprompt_skeleton:
            self._replace_absolute_range(
                suggestion.replacement_start,
                suggestion.replacement_end,
                selected.insertion,
            )

        self._clear_soft_completion(cancel_timer=True)
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

    def _accept_or_build_soft_completion(self) -> bool:
        """Accept a cached completion, or synchronously compute one for Ctrl+L."""
        if self._accept_soft_completion():
            return True
        if self._soft_completion_blocked():
            return False

        suggestion = self._build_current_soft_completion(
            allow_sync_xprompt_entries=True,
        )
        if suggestion is None:
            return False
        self._set_soft_completion(suggestion)
        return self._accept_soft_completion()

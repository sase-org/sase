"""Xprompt argument hint mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import WorkerState

from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    accepted_xprompt_arg_hint,
    detect_xprompt_arg_hint_at_cursor,
    merge_local_xprompt_entries,
    named_args_skeleton,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


def _prompt_text_area_module() -> Any:
    """Return prompt_text_area for legacy monkeypatch-compatible lookups."""
    from sase.ace.tui.widgets import prompt_text_area

    return prompt_text_area


def _build_xprompt_assist_entries(
    project: str | None = None,
) -> list[XPromptAssistEntry]:
    return _prompt_text_area_module().build_xprompt_assist_entries(project=project)


class XPromptArgHintMixin(_MixinBase):
    """Mixin providing xprompt argument hint behavior for PromptTextArea.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    if TYPE_CHECKING:
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _file_completion_active: bool
        _snippet_tabstops: list[int]
        _xprompt_arg_assist_entries_by_project: dict[
            str | None, list[XPromptAssistEntry]
        ]
        _xprompt_arg_assist_warming_projects: set[str | None]
        _xprompt_arg_assist_worker_projects: dict[str, str | None]

        def _find_prompt_bar(self) -> Any: ...
        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _on_prompt_completion_context_changed(self) -> None: ...
        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> None: ...
        def _expand_snippet_template_at_range(
            self,
            template: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> bool: ...

    def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None:
        """Render the active xprompt argument hint through the prompt bar."""
        bar = self._find_prompt_bar()
        if bar:
            bar.show_xprompt_arg_hint(hint)

    def _clear_xprompt_arg_hint(self) -> None:
        """Clear active xprompt argument hint state and hide its panel."""
        if self._active_xprompt_arg_hint is None:
            return
        self._active_xprompt_arg_hint = None
        bar = self._find_prompt_bar()
        if bar and not self._file_completion_active:
            bar.hide_file_completions()

    def _active_xprompt_hint_is_current(self) -> bool:
        hint = self._active_xprompt_arg_hint
        if hint is None:
            return False
        return (
            self.text[hint.reference_start : hint.reference_end] == hint.reference_text
        )

    def _refresh_xprompt_arg_hint_from_cursor(self) -> None:
        """Refresh typed xprompt arg hints and dismiss stale accepted hints."""
        if self._file_completion_active or self._snippet_tabstops:
            return

        detected = self._detect_xprompt_arg_hint_from_cursor()
        if detected is not None:
            if detected != self._active_xprompt_arg_hint:
                self._active_xprompt_arg_hint = detected
                self._show_xprompt_arg_hint(detected)
            return

        hint = self._active_xprompt_arg_hint
        if hint is None:
            return
        if not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return
        cursor_offset = self._absolute_offset(self.cursor_location)
        if cursor_offset != hint.reference_end:
            self._clear_xprompt_arg_hint()

    def _detect_xprompt_arg_hint_from_cursor(self) -> ActiveXPromptArgHint | None:
        """Return a typed xprompt argument hint at the current cursor."""
        if "#" not in self.text:
            return None
        cursor_offset = self._absolute_offset(self.cursor_location)
        prefix = self.text[:cursor_offset]
        marker = prefix.rfind("#")
        if marker == -1 or not any(ch in prefix[marker:] for ch in (":", "(")):
            return None
        return detect_xprompt_arg_hint_at_cursor(
            self.text,
            cursor_offset,
            self._get_xprompt_arg_assist_entries(),
        )

    def _local_xprompt_assist_entries(self) -> list[XPromptAssistEntry]:
        """Return live local-xprompt assist entries from the parent prompt bar.

        These come from the Frontmatter Panel's ``xprompts:`` field, so a
        ``#_helper`` defined there is treated like a global xprompt by this
        pane's completion and argument-hint surfaces.  Empty when the pane is not
        hosted by a bar with frontmatter (e.g. feedback / approve bars).
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return []
        getter = getattr(bar, "local_xprompt_assist_entries", None)
        if not callable(getter):
            return []
        result = getter()
        return result if isinstance(result, list) else []

    def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]:
        """Return xprompt assist entries (project catalog + live local xprompts).

        The project catalog is cached per project; the live local xprompts are
        merged in fresh on every call so a helper edited in the Frontmatter Panel
        is instantly reflected in argument hints without invalidating the cache.
        """
        project = self._xprompt_arg_assist_project_from_text()
        entries = self._xprompt_arg_assist_entries_by_project.get(project)
        if entries is None:
            entries = _build_xprompt_assist_entries(project=project)
            self._xprompt_arg_assist_entries_by_project[project] = entries
        return merge_local_xprompt_entries(
            entries, self._local_xprompt_assist_entries()
        )

    def _get_warm_xprompt_arg_assist_entries(
        self,
    ) -> list[XPromptAssistEntry] | None:
        """Return warm xprompt entries for the current project, if available."""
        project = self._xprompt_arg_assist_project_from_text()
        return self._xprompt_arg_assist_entries_by_project.get(project)

    def _warm_current_xprompt_assist_entries(self) -> None:
        """Warm prompt-local xprompt entries for the current project in a worker."""
        self._schedule_xprompt_assist_warm(self._xprompt_arg_assist_project_from_text())

    def _schedule_xprompt_assist_warm(self, project: str | None) -> None:
        """Schedule a background xprompt assist catalog build if supported."""
        if project in self._xprompt_arg_assist_entries_by_project:
            return
        if project in self._xprompt_arg_assist_warming_projects:
            return
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return

        self._xprompt_arg_assist_warming_projects.add(project)
        worker_name = f"prompt-xprompt-assist:{project or '<default>'}"
        self._xprompt_arg_assist_worker_projects[worker_name] = project

        def build() -> tuple[str | None, list[XPromptAssistEntry]]:
            return project, _build_xprompt_assist_entries(project=project)

        self.run_worker(
            build,
            name=worker_name,
            thread=True,
        )

    def on_worker_state_changed(self, event: Any) -> None:
        """Apply async xprompt assist warm results."""
        worker = event.worker
        worker_name = str(getattr(worker, "name", ""))
        if not worker_name.startswith("prompt-xprompt-assist:"):
            return
        pending_project = self._xprompt_arg_assist_worker_projects.pop(
            worker_name,
            None,
        )
        if event.state != WorkerState.SUCCESS:
            self._xprompt_arg_assist_warming_projects.discard(pending_project)
            return
        project, entries = worker.result
        self._xprompt_arg_assist_entries_by_project[project] = entries
        self._xprompt_arg_assist_warming_projects.discard(project)
        if project == self._xprompt_arg_assist_project_from_text():
            self._on_prompt_completion_context_changed()

    def _xprompt_arg_assist_project_from_text(self) -> str | None:
        """Derive project-local xprompt context from a leading VCS tag."""
        prompt_text_area = _prompt_text_area_module()
        tag = prompt_text_area.extract_vcs_workflow_tag(self.text)
        if tag is None:
            return None
        return prompt_text_area.extract_project_from_vcs_tag(tag)

    def _maybe_show_inserted_xprompt_arg_hint(
        self,
        reference_start: int,
        reference_end: int,
    ) -> bool:
        """Show a post-accept hint after non-completion xprompt insertion."""
        hint = accepted_xprompt_arg_hint(
            self.text,
            reference_start,
            reference_end,
            self._get_xprompt_arg_assist_entries(),
        )
        if hint is None:
            self._clear_xprompt_arg_hint()
            return False
        self._active_xprompt_arg_hint = hint
        self._show_xprompt_arg_hint(hint)
        return True

    def _can_apply_xprompt_arg_action(self) -> bool:
        """Return True when an active hint can consume syntax action keys."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            return False
        return self._absolute_offset(self.cursor_location) == hint.reference_end

    def _apply_xprompt_colon_arg_hint(self) -> bool:
        """Rewrite the accepted reference with colon-argument syntax."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_xprompt_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        replacement = f"{hint.entry.insertion}:"
        self._replace_via_keyboard(replacement, start, end)
        new_end = hint.reference_start + len(replacement)
        self.cursor_location = self._location_from_absolute(new_end)
        next_hint = ActiveXPromptArgHint(
            entry=hint.entry,
            reference_start=hint.reference_start,
            reference_end=new_end,
            reference_text=replacement,
            trigger_mode="colon",
            active_input_index=hint.active_input_index,
        )
        self._active_xprompt_arg_hint = next_hint
        self._show_xprompt_arg_hint(next_hint)
        return True

    def _apply_xprompt_named_arg_hint(self) -> bool:
        """Rewrite the accepted reference with a named-argument snippet."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_xprompt_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        self._clear_xprompt_arg_hint()
        return self._expand_snippet_template_at_range(
            named_args_skeleton(hint.entry),
            start,
            end,
        )

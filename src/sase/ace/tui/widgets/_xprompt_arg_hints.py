"""Xprompt argument hint mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    PendingXPromptCompletionSpacer,
    XPromptAssistEntry,
    accepted_xprompt_arg_hint,
    detect_xprompt_arg_hint_at_cursor,
    has_no_required_inputs,
    merge_local_xprompt_entries,
    named_args_skeleton,
)
from sase.xprompt.project_identity import canonical_xprompt_project

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


def _prompt_text_area_module() -> Any:
    """Return prompt_text_area for legacy monkeypatch-compatible lookups."""
    from sase.ace.tui.widgets import prompt_text_area

    return prompt_text_area


class XPromptArgHintMixin(_MixinBase):
    """Mixin providing xprompt argument hint behavior for PromptTextArea.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    if TYPE_CHECKING:
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _pending_xprompt_completion_spacer: PendingXPromptCompletionSpacer | None
        _file_completion_active: bool
        _xprompt_arg_assist_entries_by_project: dict[
            str | None, list[XPromptAssistEntry]
        ]
        _xprompt_arg_assist_warming_projects: set[str | None]
        _xprompt_arg_assist_worker_projects: dict[str, str | None]

        @property
        def snippet_session_active(self) -> bool: ...

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
        def _replace_absolute_range(
            self,
            start_offset: int,
            end_offset: int,
            replacement: str,
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
        if self._file_completion_active or self.snippet_session_active:
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
        entries = self._get_app_xprompt_arg_assist_entries(
            project,
            schedule=True,
        )
        if entries is None:
            entries = self._xprompt_arg_assist_entries_by_project.get(project, [])
        return merge_local_xprompt_entries(
            entries, self._local_xprompt_assist_entries()
        )

    def _get_warm_xprompt_arg_assist_entries(
        self,
    ) -> list[XPromptAssistEntry] | None:
        """Return warm xprompt entries for the current project, if available."""
        project = self._xprompt_arg_assist_project_from_text()
        entries = self._get_app_xprompt_arg_assist_entries(project, schedule=False)
        if entries is not None:
            return entries
        return self._xprompt_arg_assist_entries_by_project.get(project)

    def _get_exact_warm_xprompt_arg_assist_entries(
        self,
    ) -> list[XPromptAssistEntry] | None:
        """Return only the exact warm project catalog used for skill syntax."""
        project = self._xprompt_arg_assist_project_from_text()
        getter = getattr(
            self.app,
            "get_warm_prompt_catalog_assist_entries_exact",
            None,
        )
        if callable(getter):
            entries = getter(project)
            return entries if isinstance(entries, list) else None
        return self._get_warm_xprompt_arg_assist_entries()

    def _warm_current_xprompt_assist_entries(self) -> None:
        """Warm prompt-local xprompt entries for the current project in a worker."""
        self._schedule_xprompt_assist_warm(self._xprompt_arg_assist_project_from_text())

    def _schedule_xprompt_assist_warm(self, project: str | None) -> None:
        """Ask the app-owned prompt catalog to warm *project*."""
        warmer = getattr(self.app, "warm_prompt_catalog_project", None)
        if callable(warmer):
            warmer(project)

    def _get_app_xprompt_arg_assist_entries(
        self,
        project: str | None,
        *,
        schedule: bool,
    ) -> list[XPromptAssistEntry] | None:
        getter = getattr(self.app, "get_prompt_catalog_assist_entries", None)
        if not callable(getter):
            return None
        entries = getter(project, schedule=schedule)
        return entries if isinstance(entries, list) else None

    def _xprompt_arg_assist_project_from_text(self) -> str | None:
        """Derive xprompt context from a leading VCS tag or the active app.

        The VCS tag yields a user-facing project name while the prompt context
        yields a ProjectSpec directory key, so both are normalized to the
        canonical xprompt namespace. That keeps the app-level catalog cache
        keyed consistently no matter which source wins.
        """
        prompt_text_area = _prompt_text_area_module()
        tag = (
            prompt_text_area.extract_vcs_workflow_tag(self.text)
            if "#" in self.text
            else None
        )
        if tag is not None:
            project = prompt_text_area.extract_project_from_vcs_tag(tag)
            if project:
                return canonical_xprompt_project(project)

        ctx = getattr(self.app, "_prompt_context", None)
        if ctx is None or bool(getattr(ctx, "is_home_mode", False)):
            return None
        project_name = getattr(ctx, "project_name", None)
        if isinstance(project_name, str) and project_name:
            return canonical_xprompt_project(project_name)
        return None

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

    def _note_xprompt_completion_spacer(self, entry: XPromptAssistEntry) -> None:
        """Record a trailing spacer left by an eligible xprompt completion.

        Xprompts without required inputs complete to ``#name ``. Remembering
        that exact spacer lets the next comma replace it for both no-input and
        optional-only entries, while a colon may replace it only when optional
        inputs exist. Must be called immediately after skeleton expansion while
        the cursor still sits right after the inserted space.
        """
        self._pending_xprompt_completion_spacer = None
        if not has_no_required_inputs(entry):
            return
        cursor_offset = self._absolute_offset(self.cursor_location)
        spacer_offset = cursor_offset - 1
        reference_start = spacer_offset - len(entry.insertion)
        if reference_start < 0 or not (0 <= spacer_offset < len(self.text)):
            return
        if self.text[spacer_offset] != " ":
            return
        if self.text[reference_start:spacer_offset] != entry.insertion:
            return
        self._pending_xprompt_completion_spacer = PendingXPromptCompletionSpacer(
            spacer_offset=spacer_offset,
            reference_start=reference_start,
            reference_text=entry.insertion,
            has_optional_inputs=bool(entry.inputs),
        )

    def _consume_xprompt_completion_spacer(
        self,
        pending: PendingXPromptCompletionSpacer,
        character: str | None,
    ) -> bool:
        """Replace a pending completion spacer with eligible punctuation.

        A comma is eligible for no-input and optional-only entries; a colon is
        eligible only when the completed entry has optional inputs. Returns
        False when the character is ineligible or the cursor, spacer, or
        reference text changed since completion acceptance.
        """
        if character != "," and not (character == ":" and pending.has_optional_inputs):
            return False
        text = self.text
        spacer_end = pending.spacer_offset + 1
        if spacer_end > len(text):
            return False
        if self._absolute_offset(self.cursor_location) != spacer_end:
            return False
        if text[pending.spacer_offset] != " ":
            return False
        if (
            text[pending.reference_start : pending.spacer_offset]
            != pending.reference_text
        ):
            return False
        self._replace_absolute_range(pending.spacer_offset, spacer_end, character)
        return True

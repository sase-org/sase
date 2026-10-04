"""Macro argument hint mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.macro_arg_assist import (
    ActiveMacroArgHint,
    PendingMacroCompletionSpacer,
    MacroAssistEntry,
    accepted_macro_arg_hint,
    detect_macro_arg_hint_at_cursor,
    has_no_required_inputs,
    merge_local_macro_entries,
    named_args_skeleton,
)
from sase.macro.project_identity import (
    canonical_macro_project,
    macro_project_identity_ready,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets._snippets import SnippetExpansionPolicy
else:
    _MixinBase = object


def _prompt_text_area_module() -> Any:
    """Return prompt_text_area for legacy monkeypatch-compatible lookups."""
    from sase.ace.tui.widgets import prompt_text_area

    return prompt_text_area


class MacroArgHintMixin(_MixinBase):
    """Mixin providing macro argument hint behavior for PromptTextArea.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    if TYPE_CHECKING:
        _active_macro_arg_hint: ActiveMacroArgHint | None
        _pending_macro_completion_spacer: PendingMacroCompletionSpacer | None
        _file_completion_active: bool
        _macro_arg_assist_entries_by_project: dict[str | None, list[MacroAssistEntry]]
        _macro_arg_assist_warming_projects: set[str | None]
        _macro_arg_assist_worker_projects: dict[str, str | None]

        @property
        def snippet_session_active(self) -> bool: ...

        def _snippet_tabstop_jump_moves(self, *, retreat: bool) -> bool: ...
        def _try_advance_tabstop(self) -> bool: ...
        def _try_retreat_tabstop(self) -> bool: ...
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
            *,
            session_policy: SnippetExpansionPolicy,
            variables: Mapping[str, str] | None = None,
        ) -> bool: ...

    def _show_macro_arg_hint(self, hint: ActiveMacroArgHint) -> None:
        """Render the active macro argument hint through the prompt bar."""
        try:
            clearer = getattr(self, "_clear_next_word_chain", None)
            if callable(clearer):
                clearer()
        except Exception:
            pass
        bar = self._find_prompt_bar()
        if bar:
            bar.show_macro_arg_hint(hint)

    def _clear_macro_arg_hint(self) -> None:
        """Clear active macro argument hint state and hide its panel."""
        if self._active_macro_arg_hint is None:
            return
        self._active_macro_arg_hint = None
        bar = self._find_prompt_bar()
        if bar and not self._file_completion_active:
            bar.hide_file_completions()

    def _active_macro_hint_is_current(self) -> bool:
        hint = self._active_macro_arg_hint
        if hint is None:
            return False
        return (
            self.text[hint.reference_start : hint.reference_end] == hint.reference_text
        )

    def _cursor_may_need_arg_hint(self) -> bool:
        """Return whether the cursor could sit inside a macro argument list.

        This mirrors the text scan at the top of
        :meth:`_detect_macro_arg_hint_from_cursor`: when it returns False
        detection would find nothing, so callers may skip the catalog-backed
        detect entirely. A leading-tag swap (for example a ``ctrl+n/p``
        cycle) never lands inside an argument list.
        """
        try:
            text = self.text
            cursor_offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return True
        if "#" not in text:
            return False
        marker = text.rfind("#", 0, cursor_offset)
        if marker == -1:
            return False
        window = text[marker:cursor_offset]
        return (":" in window) or ("(" in window)

    def _refresh_macro_arg_hint_from_cursor(self) -> None:
        """Refresh typed macro arg hints and dismiss stale accepted hints."""
        if self._file_completion_active or self.snippet_session_active:
            return

        if self._active_macro_arg_hint is None and not self._cursor_may_need_arg_hint():
            return

        detected = self._detect_macro_arg_hint_from_cursor()
        if detected is not None:
            if detected != self._active_macro_arg_hint:
                self._active_macro_arg_hint = detected
                self._show_macro_arg_hint(detected)
            return

        hint = self._active_macro_arg_hint
        if hint is None:
            return
        if not self._active_macro_hint_is_current():
            self._clear_macro_arg_hint()
            return
        cursor_offset = self._absolute_offset(self.cursor_location)
        if cursor_offset != hint.reference_end:
            self._clear_macro_arg_hint()

    def _detect_macro_arg_hint_from_cursor(self) -> ActiveMacroArgHint | None:
        """Return a typed macro argument hint at the current cursor."""
        if "#" not in self.text:
            return None
        cursor_offset = self._absolute_offset(self.cursor_location)
        prefix = self.text[:cursor_offset]
        marker = prefix.rfind("#")
        if marker == -1 or not any(ch in prefix[marker:] for ch in (":", "(")):
            return None
        return detect_macro_arg_hint_at_cursor(
            self.text,
            cursor_offset,
            self._get_macro_arg_assist_entries(),
        )

    def _local_macro_assist_entries(self) -> list[MacroAssistEntry]:
        """Return live local-macro assist entries from the parent prompt bar.

        These come from the Frontmatter Panel's ``macros:`` field, so a
        ``#_helper`` defined there is treated like a global macro by this
        pane's completion and argument-hint surfaces.  Empty when the pane is not
        hosted by a bar with frontmatter (e.g. feedback / approve bars).
        """
        bar = self._find_prompt_bar()
        if bar is None:
            return []
        getter = getattr(bar, "local_xprompt_assist_entries", None)
        if not callable(getter):
            return []
        try:
            result = getter(self)
        except TypeError:
            result = getter()
        return result if isinstance(result, list) else []

    def _get_macro_arg_assist_entries(self) -> list[MacroAssistEntry]:
        """Return macro assist entries (project catalog + live local macros).

        The project catalog is cached per project; the live local macros are
        merged in fresh on every call so a helper edited in the Frontmatter Panel
        is instantly reflected in argument hints without invalidating the cache.
        """
        project = self._macro_arg_assist_project_from_text()
        entries = self._get_app_macro_arg_assist_entries(
            project,
            schedule=True,
        )
        if entries is None:
            entries = self._macro_arg_assist_entries_by_project.get(project, [])
        return merge_local_macro_entries(entries, self._local_macro_assist_entries())

    def _get_warm_macro_arg_assist_entries(
        self,
    ) -> list[MacroAssistEntry] | None:
        """Return warm macro entries for the current project, if available."""
        project = self._macro_arg_assist_project_from_text()
        entries = self._get_app_macro_arg_assist_entries(project, schedule=False)
        if entries is not None:
            return entries
        return self._macro_arg_assist_entries_by_project.get(project)

    def _get_exact_warm_macro_arg_assist_entries(
        self,
    ) -> list[MacroAssistEntry] | None:
        """Return only the exact warm project catalog used for skill syntax."""
        project = self._macro_arg_assist_project_from_text()
        getter = getattr(
            self.app,
            "get_warm_prompt_catalog_assist_entries_exact",
            None,
        )
        if callable(getter):
            entries = getter(project)
            return entries if isinstance(entries, list) else None
        return self._get_warm_macro_arg_assist_entries()

    def _warm_current_macro_assist_entries(self) -> None:
        """Warm prompt-local macro entries for the current project in a worker."""
        self._schedule_macro_assist_warm(self._macro_arg_assist_project_from_text())

    def _schedule_macro_assist_warm(self, project: str | None) -> None:
        """Ask the app-owned prompt catalog to warm *project*."""
        warmer = getattr(self.app, "warm_prompt_catalog_project", None)
        if callable(warmer):
            warmer(project)

    def _get_app_macro_arg_assist_entries(
        self,
        project: str | None,
        *,
        schedule: bool,
    ) -> list[MacroAssistEntry] | None:
        getter = getattr(self.app, "get_prompt_catalog_assist_entries", None)
        if not callable(getter):
            return None
        entries = getter(project, schedule=schedule)
        return entries if isinstance(entries, list) else None

    def _canonical_macro_project_for_keystroke(self, project: str) -> str | None:
        """Canonicalize *project* without building identity on the key path.

        When the macro project identity registry is already built this is
        memory-only. When it is cold and the host exposes the app-owned
        warm hook, request one warm and return the global namespace (``None``)
        for this refresh so no spurious catalog project key is registered.
        Hosts without the hook keep the synchronous call.
        """
        if macro_project_identity_ready():
            return canonical_macro_project(project)
        try:
            host_app = self.app
        except Exception:  # noqa: BLE001 - no active app outside a run.
            host_app = None
        warmer = getattr(host_app, "request_macro_project_identity_warm", None)
        if callable(warmer):
            try:
                warmer()
            except Exception:  # noqa: BLE001 - warm is best-effort.
                pass
            return None
        return canonical_macro_project(project)

    def _macro_arg_assist_project_from_text(self) -> str | None:
        """Derive macro context from a leading workspace target or the app.

        The target may be a ``+<project>`` tag or a ``#`` VCS ref; tags
        expand to their canonical ref first. The VCS tag yields a
        user-facing project name while the prompt context yields a
        ProjectSpec directory key, so both are normalized to the canonical
        macro namespace. That keeps the app-level catalog cache keyed
        consistently no matter which source wins.
        """
        prompt_text_area = _prompt_text_area_module()
        tag = None
        if "+" in self.text:
            # Tags expand first, but only when the catalog is already warm:
            # this runs on the keystroke path and must never build it.
            from sase.project_tags import (
                effective_vcs_workflow_tag_with_catalog,
                peek_project_tag_catalog,
            )

            catalog = peek_project_tag_catalog()
            if catalog is not None:
                try:
                    tag = effective_vcs_workflow_tag_with_catalog(self.text, catalog)
                except Exception:  # noqa: BLE001 - fall back to the raw tag.
                    tag = None
        if tag is None and "#" in self.text:
            tag = prompt_text_area.extract_vcs_workflow_tag(self.text)
        if tag is not None:
            project = prompt_text_area.extract_project_from_vcs_tag(tag)
            if project:
                return self._canonical_macro_project_for_keystroke(project)

        try:
            host_app = self.app
        except Exception:  # noqa: BLE001 - no active app outside a run.
            return None
        ctx = getattr(host_app, "_prompt_context", None)
        if ctx is None or bool(getattr(ctx, "is_home_mode", False)):
            return None
        project_name = getattr(ctx, "project_name", None)
        if isinstance(project_name, str) and project_name:
            return self._canonical_macro_project_for_keystroke(project_name)
        return None

    def _maybe_show_inserted_macro_arg_hint(
        self,
        reference_start: int,
        reference_end: int,
    ) -> bool:
        """Show a post-accept hint after non-completion macro insertion."""
        hint = accepted_macro_arg_hint(
            self.text,
            reference_start,
            reference_end,
            self._get_macro_arg_assist_entries(),
        )
        if hint is None:
            self._clear_macro_arg_hint()
            return False
        self._active_macro_arg_hint = hint
        self._show_macro_arg_hint(hint)
        return True

    def _can_apply_macro_arg_action(self) -> bool:
        """Return True when an active hint can consume syntax action keys."""
        hint = self._active_macro_arg_hint
        if hint is None or not self._active_macro_hint_is_current():
            return False
        return self._absolute_offset(self.cursor_location) == hint.reference_end

    def _apply_macro_colon_arg_hint(self) -> bool:
        """Rewrite the accepted reference with colon-argument syntax."""
        hint = self._active_macro_arg_hint
        if hint is None or not self._active_macro_hint_is_current():
            self._clear_macro_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_macro_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        replacement = f"{hint.entry.insertion}:"
        self._replace_via_keyboard(replacement, start, end)
        new_end = hint.reference_start + len(replacement)
        self.cursor_location = self._location_from_absolute(new_end)
        next_hint = ActiveMacroArgHint(
            entry=hint.entry,
            reference_start=hint.reference_start,
            reference_end=new_end,
            reference_text=replacement,
            trigger_mode="colon",
            active_input_index=hint.active_input_index,
        )
        self._active_macro_arg_hint = next_hint
        self._show_macro_arg_hint(next_hint)
        return True

    def _apply_macro_named_arg_hint(self) -> bool:
        """Rewrite the accepted reference with a named-argument snippet."""
        hint = self._active_macro_arg_hint
        if hint is None or not self._active_macro_hint_is_current():
            self._clear_macro_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_macro_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        self._clear_macro_arg_hint()
        return self._expand_snippet_template_at_range(
            named_args_skeleton(hint.entry),
            start,
            end,
            session_policy="nest",
        )

    def _note_macro_completion_spacer(self, entry: MacroAssistEntry) -> None:
        """Record a trailing spacer left by an eligible macro completion.

        Macros without required inputs complete to ``#name ``. Remembering
        that exact spacer lets the next comma replace it for both no-input and
        optional-only entries, while a colon or opening parenthesis may
        replace it only when optional inputs exist. Must be called immediately
        after skeleton expansion while the cursor still sits right after the
        inserted space.
        """
        self._pending_macro_completion_spacer = None
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
        self._pending_macro_completion_spacer = PendingMacroCompletionSpacer(
            spacer_offset=spacer_offset,
            reference_start=reference_start,
            reference_text=entry.insertion,
            has_optional_inputs=bool(entry.inputs),
        )

    def _macro_completion_spacer_is_intact(
        self,
        pending: PendingMacroCompletionSpacer,
    ) -> bool:
        """Return True while a pending spacer is still exactly as it was inserted.

        The cursor must still sit immediately after the spacer, the spacer must
        still be a space, and the reference text before it must be unchanged.
        """
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
        return True

    def _consume_macro_completion_spacer(
        self,
        pending: PendingMacroCompletionSpacer,
        character: str | None,
    ) -> bool:
        """Replace a pending completion spacer with eligible punctuation.

        A comma is eligible for no-input and optional-only entries; a colon is
        eligible only when the completed entry has optional inputs. An opening
        parenthesis is handled on a dedicated pairing path alongside colons.
        Returns False when the character is ineligible or the cursor, spacer,
        or reference text changed since completion acceptance.
        """
        if character != "," and not (character == ":" and pending.has_optional_inputs):
            return False
        if not self._macro_completion_spacer_is_intact(pending):
            return False
        spacer_end = pending.spacer_offset + 1
        self._replace_absolute_range(pending.spacer_offset, spacer_end, character)
        return True

    def _consume_macro_completion_spacer_for_tabstop(
        self,
        pending: PendingMacroCompletionSpacer,
        *,
        retreat: bool,
    ) -> bool:
        """Delete a pending completion spacer on the way to a snippet tabstop.

        A macro with no required inputs completes to ``#name ``; when the very
        next key jumps to another tabstop the reference is finished and that
        spacer is dead weight the user would otherwise delete by hand. Deleting
        before the jump lets the session engine remap the target stop for the
        one-character deletion, and keeps the placeholder completion that the jump
        opens in sync with the final text. Returns False -- leaving the spacer and
        the keystroke to the normal Tab path -- when no session is live, when the
        spacer is no longer intact, or when the jump would have no target.
        """
        if not self.snippet_session_active:
            return False
        if not self._macro_completion_spacer_is_intact(pending):
            return False
        if not self._snippet_tabstop_jump_moves(retreat=retreat):
            return False
        self._replace_absolute_range(
            pending.spacer_offset, pending.spacer_offset + 1, ""
        )
        if retreat:
            self._try_retreat_tabstop()
        else:
            self._try_advance_tabstop()
        return True

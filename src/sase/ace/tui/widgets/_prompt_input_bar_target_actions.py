"""Targeted snippet insertion and xprompt expansion actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_suffix_skeleton,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


def _end_location_after_insert(
    start: tuple[int, int],
    inserted: str,
) -> tuple[int, int]:
    """Return the document location at the end of *inserted* placed at *start*.

    Mirrors ``EditResult.end_location`` for an insertion that begins at *start*,
    so the cursor can be positioned at the end of an inline expansion without
    relying on the keyboard-replace return value.
    """
    lines = inserted.split("\n")
    if len(lines) == 1:
        return (start[0], start[1] + len(lines[0]))
    return (start[0] + len(lines) - 1, len(lines[-1]))


class PromptInputBarTargetActionsMixin(_MixinBase):
    """Insert snippets and expand xprompts in a captured prompt pane."""

    if TYPE_CHECKING:

        def active_text_area(self) -> PromptTextArea: ...

    def insert_snippet(
        self,
        snippet_name: str,
        entry: XPromptAssistEntry | None = None,
    ) -> None:
        """Insert a snippet reference at the active pane's cursor.

        Legacy entry point that targets whichever pane is active *now*. The
        ``#@`` selector path routes through :meth:`insert_snippet_at_target`
        instead so it can act on the exact pane that opened the modal.

        The '#' from the '#@' trigger is already in the input
        ('@' was prevented), so we just append the snippet name.

        Args:
            snippet_name: The snippet name to insert (without #)
            entry: Optional selected xprompt metadata for smart argument insertion.
        """
        self._insert_snippet_into(self.active_text_area(), snippet_name, entry)

    def insert_snippet_at_target(
        self,
        target_text_area: object,
        pane_id: str,
        trigger_range: tuple[tuple[int, int], tuple[int, int]] | None,
        snippet_name: str,
        entry: XPromptAssistEntry | None = None,
    ) -> bool:
        """Insert a snippet into the pane that opened the ``#@`` selector.

        Targets the captured origin pane rather than the currently active one,
        so a multi-pane stack inserts into the upper pane the trigger was typed
        in even if focus moved while the modal was open.

        Returns ``False`` without mutating any pane when the captured target is
        stale -- the originating pane or bar was unmounted/rebuilt while the
        modal was open -- so the caller can notify and leave every prompt
        unchanged. Insertion lands on the empty suffix range right after the
        literal ``#`` of *trigger_range*, preserving the ``Enter`` contract of
        inserting ``#name`` after the trigger ``#``.
        """
        text_area = self._resolve_pane_target(target_text_area, pane_id)
        if text_area is None:
            return False
        if trigger_range is not None:
            # Collapse the selection onto the empty range just after the trigger
            # '#' so only that suffix is replaced and the '#' itself is kept.
            text_area.cursor_location = trigger_range[1]
        self._insert_snippet_into(text_area, snippet_name, entry)
        return True

    def expand_xprompt_at_target(
        self,
        target_text_area: object,
        pane_id: str,
        trigger_range: tuple[tuple[int, int], tuple[int, int]] | None,
        expanded_text: str,
    ) -> bool:
        """Inline-expand a selected xprompt into the pane that opened ``#@``.

        Unlike :meth:`insert_snippet_at_target` -- which keeps the trigger ``#``
        and inserts a ``#name`` reference after it -- this *consumes* the ``#``,
        replacing the whole captured *trigger_range* with the already-rendered
        *expanded_text*. The replacement goes through the captured pane's
        ``_replace_via_keyboard()`` so it is recorded as one undoable
        ``TextArea`` edit: a multi-character range replace lands in its own
        isolated undo batch, so a single prompt NORMAL-mode ``u`` restores the
        exact pre-expansion text, including the literal ``#`` trigger.

        Targets the captured origin pane rather than whichever pane is active
        when the modal closes (matching ``insert_snippet_at_target``), and
        returns ``False`` without mutating anything when that target is stale --
        the originating pane or bar was unmounted/rebuilt while the modal was
        open -- so the caller can notify and leave every prompt unchanged.
        """
        text_area = self._resolve_pane_target(target_text_area, pane_id)
        if text_area is None:
            return False
        if text_area.read_only:
            # ``_replace_via_keyboard`` is a no-op in read-only (NORMAL) mode.
            # ``#@`` only fires from INSERT mode, so this is defensive; never
            # report success on a no-op edit (the caller would dismiss the
            # selector for nothing).
            return False

        # Drop transient completion / soft-completion / xprompt-arg-hint state on
        # the captured target before the edit: the ``#`` is about to disappear, so
        # any menu or hint anchored to it would otherwise linger over the spliced
        # body.
        text_area._clear_insert_g_prefix()
        text_area._clear_file_completion()
        text_area._clear_soft_completion(cancel_timer=True)
        text_area._clear_xprompt_arg_hint()

        start, end = trigger_range if trigger_range is not None else text_area.selection
        text_area._replace_via_keyboard(expanded_text, start, end)
        # The replacement inserts ``expanded_text`` starting at ``start``; place
        # the cursor at its end. (Mirrors ``EditResult.end_location`` without
        # relying on the keyboard-replace return value, matching the snippet
        # insertion path.)
        text_area.cursor_location = _end_location_after_insert(start, expanded_text)
        text_area.focus()
        return True

    def _resolve_pane_target(
        self,
        target_text_area: object,
        pane_id: str,
    ) -> PromptTextArea | None:
        """Return the captured origin pane if still live in this bar, else ``None``.

        A prompt-stack rebuild remounts panes under a fresh generation-scoped id
        (see :meth:`_pane_id`), so a captured *pane_id* that still resolves to
        the very same widget instance is proof the origin pane survived;
        a missing id, a mismatched instance, or an unmounted bar means the
        target is stale and the operation must be skipped.

        Shared by the ``#@`` selector (snippet insertion / inline expansion) and
        the ``Ctrl+I`` history load, which all act on the exact pane that opened
        their modal rather than whatever pane is active when it closes.  An empty
        *pane_id* falls back to *target_text_area* itself when it is still
        mounted, letting a programmatic caller without a captured id target the
        pane it passed directly.
        """
        if not self.is_mounted or not isinstance(target_text_area, PromptTextArea):
            return None
        if pane_id:
            try:
                found = self.query_one(f"#{pane_id}", PromptTextArea)
            except Exception:
                return None
            return found if found is target_text_area else None
        return target_text_area if target_text_area.is_mounted else None

    def _insert_snippet_into(
        self,
        text_area: PromptTextArea,
        snippet_name: str,
        entry: XPromptAssistEntry | None,
    ) -> None:
        """Insert *snippet_name* (and optional smart args) into *text_area*."""
        start, end = text_area.selection
        if entry is not None and self._insert_xprompt_smart_snippet(
            text_area,
            entry,
            start,
            end,
        ):
            text_area.focus()
            return

        reference_start = max(0, text_area._absolute_offset(start) - 1)
        text_area._replace_via_keyboard(snippet_name, start, end)
        reference_end = reference_start + 1 + len(snippet_name)
        text_area._maybe_show_inserted_xprompt_arg_hint(reference_start, reference_end)
        text_area.focus()

    def _insert_xprompt_smart_snippet(
        self,
        text_area: PromptTextArea,
        entry: XPromptAssistEntry,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> bool:
        """Insert a selected xprompt using the Ctrl+T completion skeleton."""
        # End-of-line required-text insertions get the ``:: `` shorthand; inline
        # ones keep ``::`` so existing following text is the single delimiter.
        line = text_area.document.get_line(end[0])
        append_text_arg_space = end[1] == len(line)
        next_char = line[end[1]] if end[1] < len(line) else None
        skeleton = xprompt_completion_suffix_skeleton(
            entry,
            append_text_arg_space=append_text_arg_space,
            next_char=next_char,
        )
        if not text_area._expand_snippet_template_at_range(
            skeleton,
            start,
            end,
            session_policy="nest",
        ):
            return False

        text_area._note_xprompt_completion_spacer(entry)
        cursor_offset = text_area._absolute_offset(text_area.cursor_location)
        hint = detect_xprompt_arg_hint_at_cursor(
            text_area.text,
            cursor_offset,
            [entry],
        )
        if hint is None:
            text_area._clear_xprompt_arg_hint()
            return True

        text_area._active_xprompt_arg_hint = hint
        text_area._show_xprompt_arg_hint(hint)
        return True

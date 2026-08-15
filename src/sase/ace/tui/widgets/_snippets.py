"""Snippet expansion mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from textual.document._edit import Edit

from sase.core.snippet_session_facade import (
    SnippetSessionState,
    advance_snippet_session,
    apply_snippet_session_edit,
    clear_snippet_session,
    empty_snippet_session,
    expand_snippet_session,
    plan_snippet_expansion,
    retreat_snippet_session,
)

if TYPE_CHECKING:
    from textual.document._document import EditResult
    from textual.widgets import TextArea as _MixinBase

    from ..app import AceApp
else:
    _MixinBase = object

SnippetExpansionPolicy = Literal["nest", "reset"]


class SnippetExpansionMixin(_MixinBase):
    """Mixin providing snippet expansion and tabstop navigation.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    # -- Attributes and method stubs for type checking --
    if TYPE_CHECKING:
        _snippet_session: SnippetSessionState

        @property
        def _ace_app(self) -> AceApp: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> EditResult | None: ...
        def _try_auto_placeholder_completion(self) -> bool: ...

    # -- Mixin implementation --

    @property
    def snippet_session_active(self) -> bool:
        """Return True while a snippet tabstop session is live."""
        return self._snippet_session.is_active

    def _clear_snippet_session(self) -> None:
        """End any active snippet tabstop session."""
        self._snippet_session = clear_snippet_session(self._snippet_session).state

    def edit(self, edit: Edit) -> EditResult:
        """Feed every document mutation's delta to the active snippet session.

        Every ``insert``/``delete``/``replace`` call and the whole vim
        keyboard-editing tower route through this single Textual hook
        (``TextArea.edit``), so intercepting it here is the one place that
        can keep tabstop anchors correct under arbitrary editing -- including
        a snippet expansion's own substitution of a shorter trigger word for
        a longer (or shorter) template, which must shift every later stop by
        the same length delta a normal edit would.
        """
        if not self._snippet_session.is_active:
            return super().edit(edit)

        start_loc, end_loc = sorted((edit.from_location, edit.to_location))
        edit_start = self._absolute_offset(start_loc)
        edit_end = self._absolute_offset(end_loc)
        result = super().edit(edit)
        transition = apply_snippet_session_edit(
            self._snippet_session,
            edit_start=edit_start,
            edit_end=edit_end,
            inserted_len=len(edit.text),
        )
        self._snippet_session = transition.state
        return result

    def load_text(self, text: str) -> None:
        """Load text wholesale, ending any active snippet session.

        ``load_text`` replaces the whole document without going through
        :meth:`edit`, so it gives the session no delta to remap tabstops
        from; clearing it here is the only correct response.
        """
        super().load_text(text)
        self._snippet_session = empty_snippet_session()

    def _get_snippets(self) -> dict[str, str]:
        """Get the snippet registry from the app config."""
        get_snippets = getattr(self.app, "get_snippets", None)
        if callable(get_snippets):
            return cast("dict[str, str]", get_snippets())
        return self._ace_app.get_snippets()

    def _try_expand_snippet(self) -> bool:
        """Try to expand a snippet trigger word at the cursor.

        Extracts the word immediately before the cursor, looks it up in the
        snippet registry, and replaces it with the expanded template.  Supports
        tabstop markers ``$1``, ``$2``, ... for sequential cursor positions and
        ``$0`` for the final cursor position.  If no ``$0`` is present, the
        final position defaults to the end of the expansion.

        Returns True if a snippet was expanded.
        """
        row, col = self.cursor_location
        line = self.document.get_line(row)

        # Extract word before cursor (alphanumeric + underscore)
        word_start = col
        while word_start > 0 and (
            line[word_start - 1].isalnum() or line[word_start - 1] == "_"
        ):
            word_start -= 1

        if word_start == col:
            return False  # No word before cursor

        trigger = line[word_start:col]
        snippets = self._get_snippets()

        if trigger not in snippets:
            return False

        template = snippets[trigger]
        expanded = self._expand_snippet_template_at_range(
            template,
            (row, word_start),
            (row, col),
            session_policy="nest",
        )
        if expanded:
            self._try_auto_placeholder_completion()
        return expanded

    def _expand_snippet_template_at_range(
        self,
        template: str,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        session_policy: SnippetExpansionPolicy,
    ) -> bool:
        """Expand a snippet template at an explicit document range.

        ``"nest"`` lets the Rust session engine apply its containment rule:
        nest inside the active session when *start*/*end* fall inside the
        innermost expansion, otherwise reset. ``"reset"`` always replaces any
        active session before installing the new expansion.
        """
        row = start[0]
        line = self.document.get_line(row)
        indent_len = len(line) - len(line.lstrip())
        indent = line[:indent_len]

        plan = plan_snippet_expansion(
            template,
            indent,
            indent_continuation_lines=bool(indent),
        )

        range_start = self._absolute_offset(start)

        self._replace_via_keyboard(plan.text, start, end)

        if plan.tabstop_offsets:
            self.cursor_location = self._location_from_absolute(
                range_start + plan.tabstop_offsets[0]
            )
        # No markers: cursor stays wherever _replace_via_keyboard left it
        # (the end of the expansion), matching plain-text insertion.

        state = (
            empty_snippet_session()
            if session_policy == "reset"
            else self._snippet_session
        )
        transition = expand_snippet_session(
            state,
            range_start=range_start,
            range_end=range_start + len(plan.text),
            tabstop_offsets=plan.tabstop_offsets,
        )
        self._snippet_session = transition.state

        return True

    def _try_advance_tabstop(self) -> bool:
        """Advance to the next snippet tabstop. Returns True if advanced."""
        if not self._snippet_session.is_active:
            return False

        transition = advance_snippet_session(self._snippet_session)
        self._snippet_session = transition.state
        if transition.cursor_offset is None:
            return False

        self.cursor_location = self._location_from_absolute(transition.cursor_offset)
        self._try_auto_placeholder_completion()
        return True

    def _snippet_tabstop_jump_moves(self, *, retreat: bool) -> bool:
        """Return True when a tabstop jump would land on another stop.

        The engine's transitions are pure, so this asks it for the answer and
        discards the returned state rather than reimplementing "is there a next
        stop?" in Python -- advancing off the last stop ends the session and
        retreating at the first stop stays put, and both report no target.
        """
        if not self._snippet_session.is_active:
            return False
        move = retreat_snippet_session if retreat else advance_snippet_session
        return move(self._snippet_session).cursor_offset is not None

    def _try_retreat_tabstop(self) -> bool:
        """Retreat to the previous snippet tabstop. Returns True if retreated."""
        if not self._snippet_session.is_active:
            return False

        transition = retreat_snippet_session(self._snippet_session)
        self._snippet_session = transition.state
        if transition.cursor_offset is None:
            return False

        self.cursor_location = self._location_from_absolute(transition.cursor_offset)
        self._try_auto_placeholder_completion()
        return True

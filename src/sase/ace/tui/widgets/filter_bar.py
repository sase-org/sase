"""Shared inline query editor widget."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.events import Click, Key, Mount
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TextArea

from sase.ace.query.limit_token import (
    HOST_LIMIT_HINT,
    HOST_LIMIT_KEY,
    HOST_LIMIT_VALUE_HINT,
    HOST_LIMIT_VALUES,
)
from sase.ace.query.profile_highlighting import highlight_query
from sase.ace.query_profile import CompiledQueryProfile
from sase.ace.tui.widgets._filter_bar_completion import (
    FilterBarCompletionList as _FilterBarCompletionList,
    FilterBarCompletionMixin,
    FilterCompletionMetadata,
    filter_candidate,
    filter_candidate_metadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _FilterBarInput(SingleLineVimTextArea):
    """Single-line editor that keeps completion keys inside its owning bar."""

    async def _on_key(self, event: Key) -> None:
        if event.key not in {
            "escape",
            "tab",
            "up",
            "down",
            "ctrl+p",
            "ctrl+n",
        }:
            return

        bar = self.query_ancestor(FilterBar)
        if event.key == "escape":
            bar._escape()
        elif event.key == "tab":
            bar._accept_highlighted_candidate(default_to_first=True)
        elif event.key in {"down", "ctrl+n"}:
            bar._move_completion(1)
        else:
            bar._move_completion(-1)
        event.stop()
        event.prevent_default()


class FilterBar(FilterBarCompletionMixin, Static):
    """Reusable slash-style query editor with context-aware completion."""

    # Not ClassVars: subclasses override these at class scope, and a
    # profile-configured instance overrides them again in
    # `_configure_from_profile` (e.g. a contract-driven document provider).
    ACCENT: str = "white"
    ROW_ID: ClassVar[str] = "filter-row"
    SIGIL_ID: ClassVar[str] = "filter-sigil"
    INPUT_ID: ClassVar[str] = "filter-input"
    STATUS_ID: ClassVar[str] = "filter-status"
    COMPLETION_ID: ClassVar[str] = "filter-completion"
    CANDIDATE_ID_PREFIX: ClassVar[str] = "filter-candidate"
    DISPLAY_ID: ClassVar[str | None] = None
    KEY_COMPLETIONS: tuple[tuple[str, str], ...] = ()
    STATIC_VALUE_COMPLETIONS: Mapping[str, tuple[str, ...]] = {}
    VALUE_HINTS: Mapping[str, str] = {}
    REPEATABLE_VALUE_KINDS: frozenset[str] = frozenset()
    NEGATABLE_KEYS: frozenset[str] = frozenset()
    FREE_TEXT_HINT: str = ""
    PERSISTENT: ClassVar[bool] = False

    class QueryChanged(Message):
        """The user changed the query text."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Submitted(Message):
        """The user requested that the current query be committed."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Dismissed(Message):
        """The user dismissed the bar after closing any completion menu."""

    class Clicked(Message):
        """An idle persistent bar was clicked, requesting edit mode."""

    def __init__(
        self,
        *args: Any,
        accent: str | None = None,
        profile: CompiledQueryProfile | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if accent is not None:
            self.ACCENT = accent
        self._profile = profile
        if profile is not None:
            self._configure_from_profile(profile)
        else:
            self._inject_host_limit_completions()
        self._completion_sources: dict[str, tuple[str, ...]] = {}
        self._completion_candidates: list[CompletionCandidate] = []
        self._completion_visible = False
        self._completion_signature: (
            tuple[str, int, tuple[tuple[str, tuple[str, ...]], ...]] | None
        ) = None
        self._programmatic_highlight = False
        self._editing = False
        self._last_query_text = ""
        # Keep the widget out of layout even in small test apps that don't load
        # the application stylesheet.
        self.display = self.PERSISTENT
        if self.PERSISTENT:
            self.add_class("persistent")

    def _configure_from_profile(self, profile: CompiledQueryProfile) -> None:
        """Derive this instance's dialect from *profile*, overriding the
        class-level defaults. DOM/message ids stay class-level and
        pane-specific; only the query dialect itself is profile-driven.
        """
        self.KEY_COMPLETIONS = tuple(
            (field.key, field.hint) for field in profile.fields if field.filterable
        )
        self.STATIC_VALUE_COMPLETIONS = {
            field.key: field.static_values
            for field in profile.fields
            if field.filterable and field.static_values
        }
        self.VALUE_HINTS = {
            field.key: field.hint
            for field in profile.fields
            if field.filterable and field.hint
        }
        self.REPEATABLE_VALUE_KINDS = frozenset(profile.repeatable_fields())
        self.NEGATABLE_KEYS = frozenset(profile.negatable_fields())
        self.FREE_TEXT_HINT = profile.free_text_hint
        self._inject_host_limit_completions()

    def _inject_host_limit_completions(self) -> None:
        """Expose the host-owned ``limit:`` cap on every Artifacts filter bar."""

        if not any(key == HOST_LIMIT_KEY for key, _hint in self.KEY_COMPLETIONS):
            items = [*(self.KEY_COMPLETIONS), (HOST_LIMIT_KEY, HOST_LIMIT_HINT)]
            items.sort(key=lambda item: item[0])
            self.KEY_COMPLETIONS = tuple(items)
        static = dict(self.STATIC_VALUE_COMPLETIONS)
        if not static.get(HOST_LIMIT_KEY):
            static[HOST_LIMIT_KEY] = HOST_LIMIT_VALUES
            self.STATIC_VALUE_COMPLETIONS = static
        hints = dict(self.VALUE_HINTS)
        if HOST_LIMIT_KEY not in hints:
            hints[HOST_LIMIT_KEY] = HOST_LIMIT_VALUE_HINT
            self.VALUE_HINTS = hints

    def compose(self) -> ComposeResult:
        """Compose the command line and its screen-overlay completion menu."""
        with Horizontal(id=self.ROW_ID, classes="filter-bar-row"):
            yield Static("/", id=self.SIGIL_ID, classes="filter-bar-sigil")
            editor = _FilterBarInput(
                id=self.INPUT_ID,
                classes="filter-bar-input",
                read_only=self.PERSISTENT,
            )
            closed_display_text = self._closed_display_text(self._last_query_text)
            has_closed_display = (
                self.DISPLAY_ID is not None and closed_display_text is not None
            )
            editor.can_focus = not self.PERSISTENT and not has_closed_display
            editor.display = not has_closed_display
            yield editor
            if self.DISPLAY_ID is not None and closed_display_text is not None:
                display = Static(
                    closed_display_text,
                    id=self.DISPLAY_ID,
                    classes="filter-bar-display",
                )
                display.display = True
                yield display
            yield Static("", id=self.STATUS_ID, classes="filter-bar-status")
        completion = _FilterBarCompletionList(
            id=self.COMPLETION_ID,
            classes="filter-bar-completion",
        )
        completion.can_focus = False
        completion.display = False
        yield completion

    def open(self, prefill: str) -> None:
        """Show and focus the bar with *prefill* loaded into its editor."""
        self._editing = True
        self.display = True
        self._set_closed_display_visible(False)
        editor = self._editor()
        if editor is None:
            self.set_query(prefill)
            return
        editor.display = True
        editor.can_focus = True
        editor.read_only = False
        self.set_query(prefill)
        editor.cursor_position = len(prefill)
        editor._enter_insert_mode()
        editor.focus()
        self._refresh_completion()

    def close(self) -> None:
        """End editing and collapse the completion overlay."""
        self._editing = False
        self._collapse_completion()
        editor = self._editor()
        if editor is None:
            self.display = self.PERSISTENT
            return
        editor._enter_normal_mode()
        editor.read_only = self.PERSISTENT
        if self._set_closed_display_visible(True):
            editor.display = False
            editor.can_focus = False
        else:
            editor.can_focus = not self.PERSISTENT
        self.display = self.PERSISTENT

    def focus_editor(self) -> bool:
        """Focus the editor when it has been composed."""
        editor = self._editor()
        if editor is None:
            return False
        editor.focus()
        return True

    def set_query(self, text: str) -> None:
        """Replace displayed text without emitting a user-edit message."""
        self._completion_signature = None
        self._last_query_text = text
        editor = self._editor()
        if editor is not None and editor.text != text:
            editor.load_text(text)
        self._update_closed_display(text)

    def set_status(
        self,
        match_count: int | None,
        exact: bool,
        error: str | Exception | None,
        *,
        coverage_label: str | None = None,
        lower_bound: bool = False,
    ) -> None:
        """Render the current live-result count, coverage state, or parse error."""
        status = self._status()
        if status is None:
            return
        content = Text(no_wrap=True, overflow="ellipsis")
        if error is not None:
            message = getattr(error, "message", str(error))
            content.append(message, style="bold #FF5F5F")
            status.set_class(True, "error")
        else:
            status.set_class(False, "error")
            if match_count is not None:
                noun = "match" if match_count == 1 and not lower_bound else "matches"
                marker = "+" if lower_bound else ""
                content.append(f"{match_count}{marker} {noun}", style="bold")
                content.append("  ·  ", style="dim")
            label = coverage_label or ("exact" if exact else "preview")
            content.append(label, style=self.ACCENT if exact else "dim #FFD75F")
        status.update(content)

    def clear_status(self) -> None:
        """Blank the status lane for an idle, empty query.

        The closed display's placeholder already says there is no filter;
        a match count or coverage label next to it would be noise.
        """
        status = self._status()
        if status is None:
            return
        status.set_class(False, "error")
        status.update(Text())

    @on(TextArea.Changed)
    def _on_query_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != self.INPUT_ID:
            return
        if self._editing:
            self._refresh_completion()
        text = event.text_area.text
        if text == self._last_query_text:
            return
        self._last_query_text = text
        self.post_message(self.QueryChanged(text))

    @on(TextArea.SelectionChanged)
    def _on_cursor_moved(self, event: TextArea.SelectionChanged) -> None:
        if event.text_area.id == self.INPUT_ID and self._editing:
            self._refresh_completion()

    @on(SingleLineVimTextArea.Submitted)
    def _on_query_submitted(self, event: SingleLineVimTextArea.Submitted) -> None:
        if event.text_area.id != self.INPUT_ID:
            return
        event.stop()
        if self._accept_highlighted_candidate():
            return
        self.post_message(self.Submitted(event.value))

    def _editor(self) -> _FilterBarInput | None:
        if not self.is_mounted:
            return None
        try:
            return self.query_one(f"#{self.INPUT_ID}", _FilterBarInput)
        except NoMatches:
            return None

    def _status(self) -> Static | None:
        if not self.is_mounted:
            return None
        try:
            return self.query_one(f"#{self.STATUS_ID}", Static)
        except NoMatches:
            return None

    def _closed_display(self) -> Static | None:
        if self.DISPLAY_ID is None or not self.is_mounted:
            return None
        try:
            return self.query_one(f"#{self.DISPLAY_ID}", Static)
        except NoMatches:
            return None

    def _closed_display_text(self, text: str) -> Text | None:
        if not text:
            hint = self.FREE_TEXT_HINT
            return Text(hint, style="dim italic") if hint else Text("")
        if self._profile is not None:
            return highlight_query(text, self._profile)
        return Text(text)

    def _update_closed_display(self, text: str) -> bool:
        display = self._closed_display()
        if display is None:
            return False
        rendered = self._closed_display_text(text)
        if rendered is None:
            return False
        display.update(rendered)
        return True

    def _set_closed_display_visible(self, visible: bool) -> bool:
        display = self._closed_display()
        if display is None:
            return False
        if visible and not self._update_closed_display(self._last_query_text):
            return False
        display.display = visible
        return True

    def _sigil(self) -> Static | None:
        if not self.is_mounted:
            return None
        try:
            return self.query_one(f"#{self.SIGIL_ID}", Static)
        except NoMatches:
            return None

    def _on_mount(self, event: Mount) -> None:
        super()._on_mount(event)
        if self.PERSISTENT:
            self._apply_accent()

    def _apply_accent(self) -> None:
        """Resolve border, sigil, and completion-list colors from ACCENT.

        Applied per instance rather than in CSS so a runtime-configured
        accent (a document provider's ``contract.accent``) renders
        correctly even though it is unknown at CSS-authoring time. Scoped to
        persistent bars: non-persistent bars keep their existing per-class
        CSS colors until they gain this idle presentation too.

        Called from ``_on_mount``, where Textual has already attached this
        widget's composed children (so they are queryable) but has not yet
        flipped ``is_mounted`` to ``True`` -- so this queries the DOM
        directly rather than through the ``is_mounted``-gated helpers.
        """
        sigil = self._query_child(self.SIGIL_ID)
        if sigil is not None:
            sigil.styles.color = self.ACCENT
        for widget_id in (self.INPUT_ID, self.DISPLAY_ID, self.COMPLETION_ID):
            widget = self._query_child(widget_id)
            if widget is not None:
                widget.styles.border = ("solid", self.ACCENT)

    def _query_child(self, widget_id: str | None) -> Widget | None:
        if widget_id is None:
            return None
        try:
            return self.query_one(f"#{widget_id}")
        except NoMatches:
            return None

    def on_click(self, event: Click) -> None:
        """Open an idle persistent bar for editing when it is clicked."""
        if not self.PERSISTENT or self._editing:
            return
        event.stop()
        self.post_message(self.Clicked())


__all__ = [
    "FilterBar",
    "FilterCompletionMetadata",
    "filter_candidate",
    "filter_candidate_metadata",
]

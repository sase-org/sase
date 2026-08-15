"""Shared inline query editor and completion-menu machinery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.events import Key
from textual.message import Message
from textual.widgets import OptionList, Static, TextArea
from textual.widgets.option_list import Option

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


@dataclass(frozen=True)
class _FilterCompletionMetadata:
    """Insertion and presentation data attached to a completion row."""

    kind: str
    value: str
    hint: str
    append_space: bool = True
    selectable: bool = True
    repeatable: bool = False


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


class _FilterBarCompletionList(OptionList):
    """Completion list kept separate for precise event routing and styling."""


class FilterBar(Static):
    """Reusable slash-style query editor with context-aware completion."""

    # Not a ClassVar: subclasses override it at class scope, and an instance
    # may further override it (e.g. a contract-driven document provider).
    ACCENT: str = "white"
    ROW_ID: ClassVar[str] = "filter-row"
    SIGIL_ID: ClassVar[str] = "filter-sigil"
    INPUT_ID: ClassVar[str] = "filter-input"
    STATUS_ID: ClassVar[str] = "filter-status"
    COMPLETION_ID: ClassVar[str] = "filter-completion"
    CANDIDATE_ID_PREFIX: ClassVar[str] = "filter-candidate"
    KEY_COMPLETIONS: ClassVar[tuple[tuple[str, str], ...]] = ()
    STATIC_VALUE_COMPLETIONS: ClassVar[Mapping[str, tuple[str, ...]]] = {}
    VALUE_HINTS: ClassVar[Mapping[str, str]] = {}
    REPEATABLE_VALUE_KINDS: ClassVar[frozenset[str]] = frozenset()
    NEGATABLE_KEYS: ClassVar[frozenset[str]] = frozenset()
    FREE_TEXT_HINT: ClassVar[str] = ""
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

    def __init__(self, *args: Any, accent: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if accent is not None:
            self.ACCENT = accent
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

    def compose(self) -> ComposeResult:
        """Compose the command line and its screen-overlay completion menu."""
        with Horizontal(id=self.ROW_ID, classes="filter-bar-row"):
            yield Static("/", id=self.SIGIL_ID, classes="filter-bar-sigil")
            editor = _FilterBarInput(
                id=self.INPUT_ID,
                classes="filter-bar-input",
                read_only=self.PERSISTENT,
            )
            editor.can_focus = not self.PERSISTENT
            yield editor
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
        editor = self._editor()
        self._editing = True
        self.display = True
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
        editor._enter_normal_mode()
        editor.read_only = self.PERSISTENT
        editor.can_focus = not self.PERSISTENT
        self.display = self.PERSISTENT

    def set_query(self, text: str) -> None:
        """Replace displayed text without emitting a user-edit message."""
        self._completion_signature = None
        self._last_query_text = text
        editor = self._editor()
        if editor.text != text:
            editor.load_text(text)

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
        status = self.query_one(f"#{self.STATUS_ID}", Static)
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

    def _set_completion_sources(
        self,
        sources: Mapping[str, Iterable[str]],
    ) -> None:
        """Replace normalized in-memory value sources in one refresh."""
        self._completion_sources = {
            kind: _normalized_sources(values) for kind, values in sources.items()
        }
        self._completion_signature = None
        if self.is_mounted and self._editing:
            self._refresh_completion()

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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != self.COMPLETION_ID:
            return
        event.stop()
        self._accept_candidate_index(event.option_index)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id == self.COMPLETION_ID and self._programmatic_highlight:
            event.stop()

    def _editor(self) -> _FilterBarInput:
        return self.query_one(f"#{self.INPUT_ID}", _FilterBarInput)

    def _completion_list(self) -> _FilterBarCompletionList:
        return self.query_one(f"#{self.COMPLETION_ID}", _FilterBarCompletionList)

    def _refresh_completion(self) -> None:
        if not self._editing:
            self._collapse_completion()
            return
        editor = self._editor()
        source_signature = tuple(sorted(self._completion_sources.items()))
        signature = (editor.text, editor.cursor_position, source_signature)
        if signature == self._completion_signature:
            return
        self._completion_signature = signature
        kind, prefix, negated = self._completion_context(
            editor.text,
            editor.cursor_position,
        )
        candidates = self._candidates_for(kind, prefix, negated=negated)
        if not candidates:
            self._collapse_completion()
            return

        self._completion_candidates = candidates
        options = _candidate_options(candidates, self.CANDIDATE_ID_PREFIX)
        completion = self._completion_list()
        self._programmatic_highlight = True
        try:
            completion.clear_options()
            completion.add_options(options)
            # Merely showing the menu must not make Enter accept a row. Up/down
            # highlights a row; Tab deliberately falls back to the first one.
            completion.highlighted = None
        finally:
            self._programmatic_highlight = False
        completion.display = True
        self._completion_visible = True

    def _collapse_completion(self) -> None:
        if not self.is_mounted:
            self._completion_candidates = []
            self._completion_visible = False
            return
        completion = self._completion_list()
        self._programmatic_highlight = True
        try:
            completion.highlighted = None
            completion.clear_options()
        finally:
            self._programmatic_highlight = False
        completion.display = False
        self._completion_candidates = []
        self._completion_visible = False

    def _candidates_for(
        self,
        kind: str,
        prefix: str,
        *,
        negated: bool,
    ) -> list[CompletionCandidate]:
        folded_prefix = prefix.casefold()
        if kind == "key":
            marker = "-" if negated else ""
            candidates = [
                _candidate(
                    display=f"{marker}{key}:",
                    insertion=f"{marker}{key}:",
                    name=key,
                    metadata=_FilterCompletionMetadata(
                        kind="key",
                        value=f"{marker}{key}:",
                        hint=hint,
                        append_space=False,
                    ),
                )
                for key, hint in self.KEY_COMPLETIONS
                if not negated or key in self.NEGATABLE_KEYS
                if key.casefold().startswith(folded_prefix)
            ]
            if not prefix and self.FREE_TEXT_HINT:
                candidates.append(
                    _candidate(
                        display="free text",
                        insertion="",
                        name="",
                        metadata=_FilterCompletionMetadata(
                            kind="text",
                            value="",
                            hint=self.FREE_TEXT_HINT,
                            selectable=False,
                        ),
                    )
                )
            return candidates

        values = _merge_sources(
            self.STATIC_VALUE_COMPLETIONS.get(kind, ()),
            self._completion_sources.get(kind, ()),
        )
        if not values:
            return []
        hint = self.VALUE_HINTS.get(kind, "")
        return [
            _candidate(
                display=value,
                insertion=value,
                name=value,
                metadata=_FilterCompletionMetadata(
                    kind=kind,
                    value=value,
                    hint=hint,
                    append_space=value != "YYYY-MM-DD",
                    repeatable=kind in self.REPEATABLE_VALUE_KINDS,
                ),
            )
            for value in values
            if value.casefold().startswith(folded_prefix)
        ]

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        """Classify the completion context for a concrete query language."""
        raise NotImplementedError

    def _move_completion(self, direction: int) -> None:
        if not self._completion_visible or not self._completion_candidates:
            return
        completion = self._completion_list()
        if completion.highlighted is None:
            selectable = [
                index
                for index, candidate in enumerate(self._completion_candidates)
                if _metadata(candidate).selectable
            ]
            if selectable:
                completion.highlighted = selectable[0 if direction > 0 else -1]
            return
        if direction > 0:
            completion.action_cursor_down()
        else:
            completion.action_cursor_up()

    def _accept_highlighted_candidate(self, *, default_to_first: bool = False) -> bool:
        if not self._completion_visible:
            return False
        completion = self._completion_list()
        index = completion.highlighted
        if index is None and default_to_first:
            index = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(
                        self._completion_candidates
                    )
                    if _metadata(candidate).selectable
                ),
                None,
            )
        return self._accept_candidate_index(index)

    def _accept_candidate_index(self, index: int | None) -> bool:
        if index is None or not (0 <= index < len(self._completion_candidates)):
            return False
        candidate = self._completion_candidates[index]
        metadata = _metadata(candidate)
        if not metadata.selectable:
            return False

        editor = self._editor()
        text, cursor = _apply_completion(
            editor.text,
            editor.cursor_position,
            metadata,
        )
        self._collapse_completion()
        editor.replace(
            text,
            (0, 0),
            editor.document.end,
            maintain_selection_offset=False,
        )
        editor.cursor_position = cursor
        editor.focus()
        self._refresh_completion()
        return True

    def _escape(self) -> None:
        if self._completion_visible:
            self._collapse_completion()
            return
        self.post_message(self.Dismissed())


def _candidate(
    *,
    display: str,
    insertion: str,
    name: str,
    metadata: _FilterCompletionMetadata,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=display,
        insertion=insertion,
        is_dir=False,
        name=name,
        metadata=metadata,
    )


def _metadata(candidate: CompletionCandidate) -> _FilterCompletionMetadata:
    metadata = candidate.metadata
    assert isinstance(metadata, _FilterCompletionMetadata)
    return metadata


def _candidate_options(
    candidates: list[CompletionCandidate],
    id_prefix: str,
) -> list[Option]:
    label_width = min(
        24,
        max((len(candidate.display) for candidate in candidates), default=0),
    )
    options: list[Option] = []
    for index, candidate in enumerate(candidates):
        metadata = _metadata(candidate)
        prompt = Text(no_wrap=True, overflow="ellipsis")
        label = candidate.display
        if len(label) > label_width:
            label = f"{label[: max(0, label_width - 1)]}…"
        prompt.append(f"{label:<{label_width}}")
        if metadata.hint:
            prompt.append("  ·  ", style="dim")
            prompt.append(metadata.hint, style="dim")
        options.append(
            Option(
                prompt,
                id=f"{id_prefix}-{index}",
                disabled=not metadata.selectable,
            )
        )
    return options


def _normalized_sources(values: Iterable[str]) -> tuple[str, ...]:
    by_folded: dict[str, str] = {}
    for raw_value in values:
        value = raw_value.strip()
        if value:
            by_folded.setdefault(value.casefold(), value)
    return tuple(
        sorted(by_folded.values(), key=lambda value: (value.casefold(), value))
    )


def _merge_sources(*sources: Iterable[str]) -> tuple[str, ...]:
    by_folded: dict[str, str] = {}
    for values in sources:
        for value in values:
            by_folded.setdefault(value.casefold(), value)
    return tuple(by_folded.values())


def _apply_completion(
    text: str,
    cursor: int,
    metadata: _FilterCompletionMetadata,
) -> tuple[str, int]:
    cursor = min(max(cursor, 0), len(text))
    token_start, token_end = _token_bounds(text, cursor)
    if metadata.kind == "key":
        start = token_start
        insertion = metadata.value
    else:
        colon = _first_unquoted(text, token_start, cursor, ":")
        if colon is None:
            start = token_start
            insertion = metadata.value
        else:
            start = colon + 1
            if metadata.repeatable:
                comma = _last_unquoted(text, start, cursor, ",")
                if comma is not None:
                    start = comma + 1
            insertion = _quote_completion_value(metadata.value)

    end = token_end
    if metadata.append_space:
        if end < len(text) and text[end].isspace():
            end += 1
        insertion = f"{insertion} "
    completed = f"{text[:start]}{insertion}{text[end:]}"
    return completed, start + len(insertion)


def _token_bounds(text: str, cursor: int) -> tuple[int, int]:
    in_quotes = False
    start = 0
    for index, char in enumerate(text[:cursor]):
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char.isspace() and not in_quotes:
            start = index + 1

    end = cursor
    for index in range(cursor, len(text)):
        char = text[index]
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char.isspace() and not in_quotes:
            end = index
            break
    else:
        end = len(text)
    return start, end


def _first_unquoted(text: str, start: int, end: int, needle: str) -> int | None:
    in_quotes = False
    for index in range(start, end):
        char = text[index]
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char == needle and not in_quotes:
            return index
    return None


def _last_unquoted(text: str, start: int, end: int, needle: str) -> int | None:
    in_quotes = False
    found: int | None = None
    for index in range(start, end):
        char = text[index]
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char == needle and not in_quotes:
            found = index
    return found


def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slashes += 1
        index -= 1
    return slashes % 2 == 1


def _quote_completion_value(value: str) -> str:
    if not any(char.isspace() or char in {",", '"', "\\"} for char in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


__all__ = ["FilterBar"]

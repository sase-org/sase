"""Inline query editor and completion menu for the commits timeline."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

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
from sase.vcs_log.filter_query import CompletionKind, completion_context

from .types import ARTIFACTS_ACCENTS

__all__ = ["CommitFilterBar"]

_COMMITS_ACCENT = ARTIFACTS_ACCENTS["commits"]
_DATE_COMPLETIONS = (
    "1h",
    "24h",
    "today",
    "yesterday",
    "3d",
    "7d",
    "2w",
    "YYYY-MM-DD",
)
_LIMIT_COMPLETIONS = ("40", "100", "200", "all")
_KEY_COMPLETIONS = (
    ("repo", "repository name or alias"),
    ("author", "name or email substring"),
    ("since", "Nh/Nd/Nw, today, YYYY-MM-DD"),
    ("until", "Nh/Nd/Nw, today, YYYY-MM-DD"),
    ("limit", "N or all"),
)


@dataclass(frozen=True)
class _CompletionMetadata:
    kind: CompletionKind
    value: str
    hint: str
    append_space: bool = True
    selectable: bool = True


class _CommitFilterInput(SingleLineVimTextArea):
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

        bar = self.query_ancestor(CommitFilterBar)
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


class _CommitFilterCompletionList(OptionList):
    """Completion list kept separate for precise event routing and styling."""


class CommitFilterBar(Static):
    """Slash-style commit filter editor with warm, context-aware completion."""

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._repos: tuple[str, ...] = ()
        self._authors: tuple[str, ...] = ()
        self._completion_candidates: list[CompletionCandidate] = []
        self._completion_visible = False
        self._completion_signature: (
            tuple[str, int, tuple[str, ...], tuple[str, ...]] | None
        ) = None
        self._programmatic_highlight = False
        self._last_query_text = ""
        # Keep the widget out of layout even in small test apps that don't load
        # the application stylesheet.
        self.display = False

    def compose(self) -> ComposeResult:
        """Compose the command line and its screen-overlay completion menu."""
        with Horizontal(id="commit-filter-row"):
            yield Static("/", id="commit-filter-sigil")
            yield _CommitFilterInput(id="commit-filter-input")
            yield Static("", id="commit-filter-status")
        yield _CommitFilterCompletionList(id="commit-filter-completion")

    def open(self, prefill: str) -> None:
        """Show and focus the bar with *prefill* loaded into its editor."""
        editor = self._editor()
        self.display = True
        self._completion_signature = None
        self._last_query_text = prefill
        editor.load_text(prefill)
        editor.cursor_position = len(prefill)
        editor._enter_insert_mode()
        editor.focus()
        self._refresh_completion()

    def close(self) -> None:
        """Hide the bar and collapse its completion overlay."""
        self._collapse_completion()
        self.display = False

    def set_status(
        self,
        match_count: int | None,
        exact: bool,
        error: str | Exception | None,
    ) -> None:
        """Render the current live-result count, coverage state, or parse error."""
        status = self.query_one("#commit-filter-status", Static)
        content = Text(no_wrap=True, overflow="ellipsis")
        if error is not None:
            message = getattr(error, "message", str(error))
            content.append(message, style="bold #FF5F5F")
            status.set_class(True, "error")
        else:
            status.set_class(False, "error")
            if match_count is not None:
                noun = "match" if match_count == 1 else "matches"
                content.append(f"{match_count} {noun}", style="bold")
                content.append("  ·  ", style="dim")
            content.append(
                "exact" if exact else "preview",
                style=_COMMITS_ACCENT if exact else "dim #FFD75F",
            )
        status.update(content)

    def set_completion_sources(
        self,
        repos: Iterable[str],
        authors: Iterable[str],
    ) -> None:
        """Replace the in-memory repository and author completion sources."""
        self._repos = _normalized_sources(repos)
        self._authors = _normalized_sources(authors)
        self._completion_signature = None
        if self.is_mounted and self.display:
            self._refresh_completion()

    @on(TextArea.Changed, "#commit-filter-input")
    def _on_query_changed(self, event: TextArea.Changed) -> None:
        self._refresh_completion()
        text = event.text_area.text
        if text == self._last_query_text:
            return
        self._last_query_text = text
        self.post_message(self.QueryChanged(text))

    @on(TextArea.SelectionChanged, "#commit-filter-input")
    def _on_cursor_moved(self, _event: TextArea.SelectionChanged) -> None:
        self._refresh_completion()

    @on(SingleLineVimTextArea.Submitted, "#commit-filter-input")
    def _on_query_submitted(self, event: SingleLineVimTextArea.Submitted) -> None:
        event.stop()
        if self._accept_highlighted_candidate():
            return
        self.post_message(self.Submitted(event.value))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "commit-filter-completion":
            return
        event.stop()
        self._accept_candidate_index(event.option_index)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if (
            event.option_list.id == "commit-filter-completion"
            and self._programmatic_highlight
        ):
            event.stop()

    def _editor(self) -> _CommitFilterInput:
        return self.query_one("#commit-filter-input", _CommitFilterInput)

    def _completion_list(self) -> _CommitFilterCompletionList:
        return self.query_one("#commit-filter-completion", _CommitFilterCompletionList)

    def _refresh_completion(self) -> None:
        editor = self._editor()
        signature = (
            editor.text,
            editor.cursor_position,
            self._repos,
            self._authors,
        )
        if signature == self._completion_signature:
            return
        self._completion_signature = signature
        kind, prefix = completion_context(editor.text, editor.cursor_position)
        candidates = self._candidates_for(kind, prefix)
        if not candidates:
            self._collapse_completion()
            return

        self._completion_candidates = candidates
        options = _candidate_options(candidates)
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
        self, kind: CompletionKind, prefix: str
    ) -> list[CompletionCandidate]:
        folded_prefix = prefix.casefold()
        if kind == "key":
            candidates = [
                _candidate(
                    display=f"{key}:",
                    insertion=f"{key}:",
                    name=key,
                    metadata=_CompletionMetadata(
                        kind="key",
                        value=f"{key}:",
                        hint=hint,
                        append_space=False,
                    ),
                )
                for key, hint in _KEY_COMPLETIONS
                if key.casefold().startswith(folded_prefix)
            ]
            if not prefix:
                candidates.append(
                    _candidate(
                        display="free text",
                        insertion="",
                        name="",
                        metadata=_CompletionMetadata(
                            kind="text",
                            value="",
                            hint="subject terms (AND)",
                            selectable=False,
                        ),
                    )
                )
            return candidates

        if kind == "repo":
            values = self._repos
            hint = "repository"
        elif kind == "author":
            values = self._authors
            hint = "author"
        elif kind in {"since", "until"}:
            values = _DATE_COMPLETIONS
            hint = "date bound"
        elif kind == "limit":
            values = _LIMIT_COMPLETIONS
            hint = "row limit"
        else:
            return []

        return [
            _candidate(
                display=value,
                insertion=value,
                name=value,
                metadata=_CompletionMetadata(
                    kind=kind,
                    value=value,
                    hint=hint,
                    append_space=value != "YYYY-MM-DD",
                ),
            )
            for value in values
            if value.casefold().startswith(folded_prefix)
        ]

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
    metadata: _CompletionMetadata,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=display,
        insertion=insertion,
        is_dir=False,
        name=name,
        metadata=metadata,
    )


def _metadata(candidate: CompletionCandidate) -> _CompletionMetadata:
    metadata = candidate.metadata
    assert isinstance(metadata, _CompletionMetadata)
    return metadata


def _candidate_options(candidates: list[CompletionCandidate]) -> list[Option]:
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
                id=f"commit-filter-candidate-{index}",
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


def _apply_completion(
    text: str,
    cursor: int,
    metadata: _CompletionMetadata,
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
            if metadata.kind in {"repo", "author"}:
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

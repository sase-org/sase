"""Completion state, rendering, and insertion behavior for ``FilterBar``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.css.query import NoMatches
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from sase.ace.query_profile import CompiledQueryProfile
from sase.ace.tui.widgets._filter_bar_completion_edit import (
    FilterCompletionMetadata,
    apply_filter_completion,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.filter_tokens import completion_context as _token_completion_context

if TYPE_CHECKING:
    from textual.message import Message
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
else:
    _MixinBase = object


class FilterBarCompletionList(OptionList):
    """Completion list kept separate for precise event routing and styling."""


class FilterBarCompletionMixin(_MixinBase):
    """Completion behavior shared by profile-driven filter bars."""

    if TYPE_CHECKING:
        CANDIDATE_ID_PREFIX: ClassVar[str]
        COMPLETION_ID: ClassVar[str]
        FREE_TEXT_HINT: str
        KEY_COMPLETIONS: tuple[tuple[str, str], ...]
        NEGATABLE_KEYS: frozenset[str]
        REPEATABLE_VALUE_KINDS: frozenset[str]
        STATIC_VALUE_COMPLETIONS: Mapping[str, tuple[str, ...]]
        VALUE_HINTS: Mapping[str, str]
        Dismissed: type[Message]
        _completion_candidates: list[CompletionCandidate]
        _completion_signature: (
            tuple[str, int, tuple[tuple[str, tuple[str, ...]], ...]] | None
        )
        _completion_sources: dict[str, tuple[str, ...]]
        _completion_visible: bool
        _editing: bool
        _profile: CompiledQueryProfile | None
        _programmatic_highlight: bool

        def _editor(self) -> SingleLineVimTextArea | None: ...

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

    def set_observed_facets(
        self,
        facets: Mapping[str, Iterable[str]],
    ) -> None:
        """Use worker-built values for every profile-declared filter field."""
        if self._profile is None:
            return
        declared = frozenset(self._profile.filterable_fields())
        self._set_completion_sources(
            {key: values for key, values in facets.items() if key in declared}
        )

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

    def _completion_list(self) -> FilterBarCompletionList | None:
        if not self.is_mounted:
            return None
        try:
            return self.query_one(f"#{self.COMPLETION_ID}", FilterBarCompletionList)
        except NoMatches:
            return None

    def _refresh_completion(self) -> None:
        if not self._editing:
            self._collapse_completion()
            return
        editor = self._editor()
        if editor is None:
            self._collapse_completion()
            return
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
        if completion is None:
            self._completion_candidates = []
            self._completion_visible = False
            return
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
        completion = self._completion_list()
        if completion is None:
            self._completion_candidates = []
            self._completion_visible = False
            return
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
                    metadata=FilterCompletionMetadata(
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
                        metadata=FilterCompletionMetadata(
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
        candidates = [
            _candidate(
                display=value,
                insertion=value,
                name=value,
                metadata=FilterCompletionMetadata(
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
        if len(candidates) == 1 and candidates[0].name.casefold() == folded_prefix:
            return []
        return candidates

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        """Classify the completion context for a concrete query language.

        Profile-configured bars get a working default for free: flat query
        dialects all share the same key/value/negation token grammar (see
        :func:`sase.filter_tokens.completion_context`), parameterized only
        by which keys exist, which repeat, and which negate -- all of which
        the profile already declares. A boolean-mode bar (Patch) still
        needs its own override.
        """
        if self._profile is None:
            raise NotImplementedError
        keys = self._profile.filterable_fields()
        if "limit" not in keys:
            keys = (*keys, "limit")
        return _token_completion_context(
            text,
            cursor,
            keys=keys,
            repeatable_keys=self._profile.repeatable_fields(),
            negatable_keys=self._profile.negatable_fields(),
        )

    def _move_completion(self, direction: int) -> None:
        if not self._completion_visible or not self._completion_candidates:
            return
        completion = self._completion_list()
        if completion is None:
            return
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
        if completion is None:
            return False
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
        if editor is None:
            return False
        text, cursor = apply_filter_completion(
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
    metadata: FilterCompletionMetadata,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=display,
        insertion=insertion,
        is_dir=False,
        name=name,
        metadata=metadata,
    )


def _metadata(candidate: CompletionCandidate) -> FilterCompletionMetadata:
    metadata = candidate.metadata
    assert isinstance(metadata, FilterCompletionMetadata)
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


filter_candidate = _candidate
filter_candidate_metadata = _metadata


__all__ = [
    "FilterBarCompletionList",
    "FilterBarCompletionMixin",
    "FilterCompletionMetadata",
    "filter_candidate",
    "filter_candidate_metadata",
]

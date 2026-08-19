"""Inline query editor and completion menu for Artifacts Patches."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message

from sase.ace.query.completion import patch_completion_context
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.filter_bar import (
    FilterBar,
    FilterCompletionMetadata,
    filter_candidate,
    filter_candidate_metadata,
)

from .types import ARTIFACTS_ACCENTS


_PREDICATE_COMPLETIONS: tuple[tuple[str, str], ...] = (
    ("!!!", "has error suffix"),
    ("!!", "no error suffix"),
    ("@@@", "has running agents"),
    ("!@", "no running agents"),
    ("$$$", "has running processes"),
    ("!$", "no running processes"),
    ("*", "any special state"),
)


class PatchFilterBar(FilterBar):
    """Persistent Patch filter editor with boolean completion."""

    PERSISTENT = True
    ACCENT = ARTIFACTS_ACCENTS["patches"]
    ROW_ID = "patch-filter-row"
    SIGIL_ID = "patch-filter-sigil"
    INPUT_ID = "patch-filter-input"
    STATUS_ID = "patch-filter-status"
    COMPLETION_ID = "patch-filter-completion"
    CANDIDATE_ID_PREFIX = "patch-filter-candidate"
    DISPLAY_ID = "patch-filter-display"

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
        self._sigil_value_field: str | None = None
        self._query_empty_for_completion = True

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        if self._profile is None:
            raise NotImplementedError
        self._query_empty_for_completion = not text.strip()
        self._sigil_value_field = _sigil_value_field(text, cursor, self)
        return patch_completion_context(text, cursor, profile=self._profile)

    def _candidates_for(
        self,
        kind: str,
        prefix: str,
        *,
        negated: bool,
    ) -> list[CompletionCandidate]:
        if kind == "macro":
            return self._macro_candidates(prefix)

        candidates = super()._candidates_for(kind, prefix, negated=negated)
        if kind == self._sigil_value_field:
            candidates = [
                _as_sigil_value_candidate(candidate, kind) for candidate in candidates
            ]

        if kind != "key":
            return candidates

        folded_prefix = prefix.casefold()
        candidates.extend(self._sigil_candidates(folded_prefix))
        candidates.extend(self._predicate_candidates(folded_prefix))
        if self._query_empty_for_completion:
            candidates.extend(self._save_candidates(folded_prefix))
        return candidates

    def _sigil_candidates(self, folded_prefix: str) -> list[CompletionCandidate]:
        if self._profile is None:
            return []
        candidates = []
        fields = {field.key: field for field in self._profile.fields}
        for spec in self._profile.sigils:
            field = fields.get(spec.field)
            hint = field.hint if field is not None else spec.field
            if not _matches_prefix(folded_prefix, spec.sigil, spec.field):
                continue
            candidates.append(
                filter_candidate(
                    display=f"{spec.sigil}{spec.field}",
                    insertion=spec.sigil,
                    name=spec.field,
                    metadata=FilterCompletionMetadata(
                        kind="key",
                        value=spec.sigil,
                        hint=hint,
                        append_space=False,
                    ),
                )
            )
        return candidates

    def _macro_candidates(self, prefix: str) -> list[CompletionCandidate]:
        if self._profile is None:
            return []
        folded_prefix = prefix.casefold()
        candidates = []
        for macro in self._profile.macros:
            token = f"{macro.trigger}{macro.letter}"
            if folded_prefix and not macro.letter.casefold().startswith(folded_prefix):
                continue
            candidates.append(
                filter_candidate(
                    display=token,
                    insertion=token,
                    name=token,
                    metadata=FilterCompletionMetadata(
                        kind="key",
                        value=token,
                        hint=f"{macro.field}:{macro.value}",
                    ),
                )
            )
        return candidates

    def _predicate_candidates(
        self,
        folded_prefix: str,
    ) -> list[CompletionCandidate]:
        candidates = []
        for token, hint in _PREDICATE_COMPLETIONS:
            if not _matches_prefix(folded_prefix, token, hint):
                continue
            candidates.append(
                filter_candidate(
                    display=token,
                    insertion=token,
                    name=token,
                    metadata=FilterCompletionMetadata(
                        kind="key",
                        value=token,
                        hint=hint,
                    ),
                )
            )
        return candidates

    def _save_candidates(self, folded_prefix: str) -> list[CompletionCandidate]:
        rows = [("#", "save to next free slot")]
        rows.extend((f"#{slot}", f"save/delete slot {slot}") for slot in range(10))
        candidates = []
        for token, hint in rows:
            if not _matches_prefix(folded_prefix, token, hint):
                continue
            candidates.append(
                filter_candidate(
                    display=token,
                    insertion=token,
                    name=token,
                    metadata=FilterCompletionMetadata(
                        kind="key",
                        value=token,
                        hint=hint,
                    ),
                )
            )
        return candidates

    def _closed_display_text(self, text: str) -> Text | None:
        rendered = super()._closed_display_text(text)
        if rendered is None:
            return None
        slot = self._matching_saved_slot(text)
        if slot is not None:
            rendered.append("  ")
            rendered.append(f"[{self._saved_prefix()}{slot}]", style="bold #00FF00")
        return rendered

    def _matching_saved_slot(self, text: str) -> str | None:
        cache = getattr(getattr(self, "app", None), "_saved_queries", None)
        if not isinstance(cache, dict):
            return None
        for slot, record in cache.get("patches", {}).items():
            if getattr(record, "canonical", None) == text:
                return str(slot)
        return None

    def _saved_prefix(self) -> str:
        registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
        if registry is None:
            return "0"
        from ...keymaps import key_display_name

        return key_display_name(registry.app.start_saved_query_mode)


def _as_sigil_value_candidate(
    candidate: CompletionCandidate,
    kind: str,
) -> CompletionCandidate:
    metadata = filter_candidate_metadata(candidate)
    return filter_candidate(
        display=candidate.display,
        insertion=candidate.insertion,
        name=candidate.name,
        metadata=FilterCompletionMetadata(
            kind=f"sigil:{kind}",
            value=metadata.value,
            hint=metadata.hint,
            append_space=metadata.append_space,
            selectable=metadata.selectable,
            repeatable=metadata.repeatable,
        ),
    )


def _matches_prefix(prefix: str, *values: str) -> bool:
    return not prefix or any(value.casefold().startswith(prefix) for value in values)


def _sigil_value_field(text: str, cursor: int, bar: PatchFilterBar) -> str | None:
    profile = bar._profile
    if profile is None:
        return None
    cursor = min(max(cursor, 0), len(text))
    before = text[:cursor]
    start = len(before)
    while (
        start > 0 and not before[start - 1].isspace() and before[start - 1] not in "()"
    ):
        start -= 1
    token = before[start:]
    if not token:
        return None
    sigil_map = {item.sigil: item.field for item in profile.sigils}
    return sigil_map.get(token[0])


__all__ = ["PatchFilterBar"]

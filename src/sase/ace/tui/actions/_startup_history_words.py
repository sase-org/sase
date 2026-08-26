"""Background prompt-history word cache for ACE completion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.history.prompt_word_deletions import PromptWordDeletionsSourceToken
    from sase.history.prompt_word_index import PromptWordIndex, PromptWordIndexToken

log = logging.getLogger(__name__)

# ``(index source token, deletions source token)``. Keeping the two tokens
# separate lets a deletions-only change skip the far more expensive index
# rebuild and re-read just the small deletions file.
HistoryPromptCacheSourceToken = tuple[
    "PromptWordIndexToken",
    "PromptWordDeletionsSourceToken",
]


@dataclass(frozen=True, slots=True)
class _HistoryWordsLoadResult:
    """Off-thread history-word load result."""

    source_token: HistoryPromptCacheSourceToken
    index: PromptWordIndex | None
    deletions: frozenset[str] | None


class StartupHistoryWordsMixin:
    """Mixin providing an app-global, memory-only prompt-history word cache."""

    _history_prompt_word_index_cache: PromptWordIndex | None
    _history_prompt_word_deletions_cache: frozenset[str] | None
    _history_prompt_words_cache: list[str] | None
    _history_prompt_words_source_token: HistoryPromptCacheSourceToken | None
    _history_prompt_words_rebuild_in_flight: bool
    _history_prompt_words_rebuild_pending: bool

    def history_prompt_word_index(self: Any) -> PromptWordIndex | None:
        """Return the warm prompt-word index without touching disk."""
        return self._history_prompt_word_index_cache

    def history_prompt_words(self: Any) -> list[str] | None:
        """Return the warm MRU history-word list without touching disk."""
        return self._history_prompt_words_cache

    def history_prompt_word_deletions(self: Any) -> frozenset[str]:
        """Return the warm suppressed-word set without touching disk."""
        return self._history_prompt_word_deletions_cache or frozenset()

    def warm_history_prompt_words(self: Any) -> None:
        """Schedule an off-thread cache staleness check and rebuild."""
        settings = self.get_prompt_completion_settings()
        max_words = settings.history_word_count
        min_length = settings.word_min_length
        if max_words <= 0:
            was_cold = self._history_prompt_words_cache is None
            self._set_empty_history_prompt_cache(min_length=min_length)
            self._history_prompt_words_source_token = (
                (min_length, None, ()),
                ("", -1, -1),
            )
            if was_cold:
                self._refresh_visible_history_word_surfaces()
            return

        if self._history_prompt_words_rebuild_in_flight:
            self._history_prompt_words_rebuild_pending = True
            return

        self._history_prompt_words_rebuild_in_flight = True
        self._history_prompt_words_rebuild_pending = False
        previous_token = (
            self._history_prompt_words_source_token
            if self._history_prompt_word_index_cache is not None
            else None
        )

        async def run_rebuild() -> None:
            await self._run_history_prompt_words_rebuild(
                max_words=max_words,
                min_length=min_length,
                previous_token=previous_token,
            )

        try:
            self.run_worker(
                cast(Any, run_rebuild),
                name="prompt-history-words",
                group="prompt-history-words",
                exclusive=False,
            )
        except Exception:
            self._history_prompt_words_rebuild_in_flight = False
            log.exception("Failed to schedule prompt-history word rebuild")
            if self._history_prompt_word_index_cache is None:
                self._set_empty_history_prompt_cache(min_length=min_length)
                self._refresh_visible_history_word_surfaces()

    def forget_history_prompt_word(self: Any, word: str) -> None:
        """Optimistically suppress *word* and refresh visible surfaces.

        The index itself is untouched -- deletions are applied at query time,
        so ``Ctrl+D`` never triggers a full corpus rebuild.
        """
        current = self._history_prompt_word_deletions_cache or frozenset()
        folded = word.casefold()
        if folded in {candidate.casefold() for candidate in current}:
            return
        self._history_prompt_word_deletions_cache = current | {word}
        if isinstance(self._history_prompt_words_cache, list):
            self._history_prompt_words_cache = [
                candidate
                for candidate in self._history_prompt_words_cache
                if candidate.casefold() != folded
            ]
        self._refresh_visible_history_word_surfaces()

    def _set_empty_history_prompt_cache(self: Any, *, min_length: int) -> None:
        from sase.history.prompt_word_index import build_prompt_word_index

        self._history_prompt_word_index_cache = build_prompt_word_index(
            min_length=min_length,
            shard_paths=(),
        )
        self._history_prompt_word_deletions_cache = frozenset()
        self._history_prompt_words_cache = []

    async def _run_history_prompt_words_rebuild(
        self: Any,
        *,
        max_words: int,
        min_length: int,
        previous_token: HistoryPromptCacheSourceToken | None,
    ) -> None:
        """Build history words off-thread and publish on the UI task."""
        import asyncio

        result: _HistoryWordsLoadResult | None = None
        try:
            result = await asyncio.to_thread(
                _load_history_prompt_words,
                min_length=min_length,
                previous_token=previous_token,
            )
        except Exception:
            log.exception("Prompt-history word rebuild failed")
            if self._history_prompt_word_index_cache is None:
                self._set_empty_history_prompt_cache(min_length=min_length)
                self._refresh_visible_history_word_surfaces()
        finally:
            self._history_prompt_words_rebuild_in_flight = False

        if result is not None:
            self._history_prompt_words_source_token = result.source_token
            changed = False
            if result.index is not None:
                self._history_prompt_word_index_cache = result.index
                changed = True
            if result.deletions is not None:
                self._history_prompt_word_deletions_cache = result.deletions
                changed = True
            if changed:
                self._history_prompt_words_cache = _mru_words_from_index(
                    self._history_prompt_word_index_cache,
                    deletions=self._history_prompt_word_deletions_cache or frozenset(),
                    max_words=max_words,
                )
                self._refresh_visible_history_word_surfaces()

        if self._history_prompt_words_rebuild_pending:
            self._history_prompt_words_rebuild_pending = False
            self.warm_history_prompt_words()

    def _refresh_visible_history_word_surfaces(self: Any) -> None:
        """Apply a newly warm cache to active history-word menus."""
        try:
            from ..widgets.history_word_completion import (
                HISTORY_WORD_COMPLETION_KIND,
            )
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            return
        for text_area in text_areas:
            if (
                not getattr(text_area, "is_mounted", False)
                or not getattr(text_area, "_file_completion_active", False)
                or getattr(text_area, "_completion_kind", "")
                != HISTORY_WORD_COMPLETION_KIND
            ):
                continue
            try:
                text_area._apply_history_word_completion_result(
                    self._history_prompt_words_cache or []
                )
            except Exception:
                log.debug(
                    "Failed to refresh history-word completion surface",
                    exc_info=True,
                )


def _mru_words_from_index(
    index: PromptWordIndex | None,
    *,
    deletions: frozenset[str],
    max_words: int,
) -> list[str]:
    """Return canonical words in MRU order, folded deletions and cap applied."""
    if index is None or max_words <= 0:
        return []
    deletion_folds = {word.casefold() for word in deletions}
    words: list[str] = []
    for word_id in index.mru:
        word = index.spelling(word_id)
        if word.casefold() in deletion_folds:
            continue
        words.append(word)
        if len(words) >= max_words:
            break
    return words


def _load_history_prompt_words(
    *,
    min_length: int,
    previous_token: HistoryPromptCacheSourceToken | None,
) -> _HistoryWordsLoadResult:
    """Read the source tokens and rebuild only what has gone stale."""
    from sase.history.prompt_word_deletions import (
        load_deleted_prompt_words,
        prompt_word_deletions_source_token,
    )
    from sase.history.prompt_word_index import (
        build_prompt_word_index,
        prompt_word_index_source_token,
    )

    index_token = prompt_word_index_source_token(min_length=min_length)
    deletions_token = prompt_word_deletions_source_token()
    source_token = (index_token, deletions_token)

    previous_index_token = None if previous_token is None else previous_token[0]
    previous_deletions_token = None if previous_token is None else previous_token[1]

    index: PromptWordIndex | None = None
    if previous_index_token != index_token:
        index = build_prompt_word_index(min_length=min_length)

    deletions: frozenset[str] | None = None
    if previous_deletions_token != deletions_token:
        deletions = frozenset(load_deleted_prompt_words())

    return _HistoryWordsLoadResult(
        source_token=source_token,
        index=index,
        deletions=deletions,
    )

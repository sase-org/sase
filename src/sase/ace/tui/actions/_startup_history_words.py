"""Background prompt-history word cache for ACE completion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.history.prompt_words import HistoryWordsSourceToken

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _HistoryWordsLoadResult:
    """Off-thread history-word load result."""

    source_token: HistoryWordsSourceToken
    words: list[str] | None


class StartupHistoryWordsMixin:
    """Mixin providing an app-global, memory-only prompt-history word cache."""

    _history_prompt_words_cache: list[str] | None
    _history_prompt_words_source_token: HistoryWordsSourceToken | None
    _history_prompt_words_rebuild_in_flight: bool
    _history_prompt_words_rebuild_pending: bool

    def history_prompt_words(self: Any) -> list[str] | None:
        """Return the warm history-word cache without touching disk."""
        return self._history_prompt_words_cache

    def warm_history_prompt_words(self: Any) -> None:
        """Schedule an off-thread cache staleness check and rebuild."""
        settings = self.get_prompt_completion_settings()
        max_words = settings.history_word_count
        min_length = settings.word_min_length
        if max_words <= 0:
            was_cold = self._history_prompt_words_cache is None
            self._history_prompt_words_cache = []
            self._history_prompt_words_source_token = (0, min_length, ())
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
            if self._history_prompt_words_cache is not None
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
            if self._history_prompt_words_cache is None:
                self._history_prompt_words_cache = []
                self._refresh_visible_history_word_surfaces()

    async def _run_history_prompt_words_rebuild(
        self: Any,
        *,
        max_words: int,
        min_length: int,
        previous_token: HistoryWordsSourceToken | None,
    ) -> None:
        """Build history words off-thread and publish on the UI task."""
        import asyncio

        result: _HistoryWordsLoadResult | None = None
        try:
            result = await asyncio.to_thread(
                _load_history_prompt_words,
                max_words=max_words,
                min_length=min_length,
                previous_token=previous_token,
            )
        except Exception:
            log.exception("Prompt-history word rebuild failed")
            if self._history_prompt_words_cache is None:
                self._history_prompt_words_cache = []
                self._refresh_visible_history_word_surfaces()
        finally:
            self._history_prompt_words_rebuild_in_flight = False

        if result is not None:
            self._history_prompt_words_source_token = result.source_token
            if result.words is not None:
                self._history_prompt_words_cache = result.words
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


def _load_history_prompt_words(
    *,
    max_words: int,
    min_length: int,
    previous_token: HistoryWordsSourceToken | None,
) -> _HistoryWordsLoadResult:
    """Read the source token and rebuild only when it is stale."""
    from sase.history.prompt_words import (
        collect_recent_prompt_words,
        history_words_source_token,
    )

    source_token = history_words_source_token(
        max_words=max_words,
        min_length=min_length,
    )
    if source_token == previous_token:
        return _HistoryWordsLoadResult(source_token=source_token, words=None)
    return _HistoryWordsLoadResult(
        source_token=source_token,
        words=collect_recent_prompt_words(
            max_words=max_words,
            min_length=min_length,
        ),
    )

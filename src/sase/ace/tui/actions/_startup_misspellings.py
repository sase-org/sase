"""Background misspelling cache for ACE sticky prompt spellcheck highlighting."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.history.prompt_misspellings import MisspellingsSourceToken

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _MisspellingsLoadResult:
    """Off-thread misspellings load result."""

    source_token: MisspellingsSourceToken
    misspelled: frozenset[str] | None
    allowed: frozenset[str] | None


class StartupMisspellingsMixin:
    """Mixin providing an app-global, memory-only misspelling cache."""

    _misspelled_words_cache: frozenset[str] | None
    _allowed_misspellings_cache: frozenset[str] | None
    _misspellings_source_token: MisspellingsSourceToken | None
    _misspellings_generation: int
    _misspellings_rebuild_in_flight: bool
    _misspellings_rebuild_pending: bool

    def misspelled_words(self: Any) -> frozenset[str]:
        """Return the warm casefolded misspelling set without touching disk."""
        return self._misspelled_words_cache or frozenset()

    def misspellings_generation(self: Any) -> int:
        """Return a counter bumped on every successful cache publish.

        Prompt overlays fold this into their span cache key so a build against
        a cold cache repaints once the saved words land.
        """
        return self._misspellings_generation

    def warm_misspellings(self: Any) -> None:
        """Schedule an off-thread cache staleness check and reload."""
        if self._misspellings_rebuild_in_flight:
            self._misspellings_rebuild_pending = True
            return

        self._misspellings_rebuild_in_flight = True
        self._misspellings_rebuild_pending = False
        previous_token = (
            self._misspellings_source_token
            if self._misspelled_words_cache is not None
            else None
        )

        async def run_rebuild() -> None:
            await self._run_misspellings_rebuild(previous_token=previous_token)

        try:
            self.run_worker(
                cast(Any, run_rebuild),
                name="prompt-misspellings",
                group="prompt-misspellings",
                exclusive=False,
            )
        except Exception:
            self._misspellings_rebuild_in_flight = False
            log.exception("Failed to schedule misspellings reload")
            if self._misspelled_words_cache is None:
                self._misspelled_words_cache = frozenset()
                self._allowed_misspellings_cache = frozenset()
                self._publish_misspellings()

    def record_misspelling(self: Any, word: str) -> None:
        """Optimistically remember *word* as misspelled, then persist off-thread.

        A no-op when *word* is already remembered or has been accepted.
        """
        key = word.casefold()
        if not key:
            return
        if key in self._allowed_misspellings() or key in self._misspelled_words():
            return
        self._misspelled_words_cache = self._misspelled_words() | {key}
        self._publish_misspellings()
        self._schedule_misspellings_persist(_persist_record, word)

    def allow_word(self: Any, word: str) -> None:
        """Optimistically accept *word*, then persist off-thread."""
        key = word.casefold()
        if not key:
            return
        self._misspelled_words_cache = self._misspelled_words() - {key}
        self._allowed_misspellings_cache = self._allowed_misspellings() | {key}
        self._publish_misspellings()
        self._schedule_misspellings_persist(_persist_allow, word)

    def forget_misspelling(self: Any, word: str) -> None:
        """Optimistically clear *word* from the misspelled set, then persist."""
        key = word.casefold()
        if not key or key not in self._misspelled_words():
            return
        self._misspelled_words_cache = self._misspelled_words() - {key}
        self._publish_misspellings()
        self._schedule_misspellings_persist(_persist_forget, word)

    def _misspelled_words(self: Any) -> frozenset[str]:
        return self._misspelled_words_cache or frozenset()

    def _allowed_misspellings(self: Any) -> frozenset[str]:
        return self._allowed_misspellings_cache or frozenset()

    def _schedule_misspellings_persist(
        self: Any,
        persist: Callable[[str], None],
        word: str,
    ) -> None:
        async def run_persist() -> None:
            import asyncio

            try:
                await asyncio.to_thread(persist, word)
            except Exception:
                log.exception("Misspellings persist failed")

        try:
            self.run_worker(
                cast(Any, run_persist),
                name="prompt-misspellings-persist",
                group="prompt-misspellings-persist",
                exclusive=False,
            )
        except Exception:
            log.exception("Failed to schedule misspellings persist")

    async def _run_misspellings_rebuild(
        self: Any,
        *,
        previous_token: MisspellingsSourceToken | None,
    ) -> None:
        """Load the store off-thread and publish on the UI task."""
        import asyncio

        result: _MisspellingsLoadResult | None = None
        try:
            result = await asyncio.to_thread(
                _load_misspellings,
                previous_token=previous_token,
            )
        except Exception:
            log.exception("Misspellings reload failed")
            if self._misspelled_words_cache is None:
                self._misspelled_words_cache = frozenset()
                self._allowed_misspellings_cache = frozenset()
                self._publish_misspellings()
        finally:
            self._misspellings_rebuild_in_flight = False

        if result is not None:
            self._misspellings_source_token = result.source_token
            if result.misspelled is not None:
                self._misspelled_words_cache = result.misspelled
                self._allowed_misspellings_cache = result.allowed or frozenset()
                self._publish_misspellings()

        if self._misspellings_rebuild_pending:
            self._misspellings_rebuild_pending = False
            self.warm_misspellings()

    def _publish_misspellings(self: Any) -> None:
        """Bump the generation counter and refresh any mounted prompt overlays."""
        self._misspellings_generation += 1
        self._refresh_misspelling_overlays()

    def _refresh_misspelling_overlays(self: Any) -> None:
        """Repaint the sticky-misspelling overlay on every mounted prompt input."""
        try:
            from ..widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            return
        for text_area in text_areas:
            if not getattr(text_area, "is_mounted", False):
                continue
            try:
                text_area._refresh_misspelling_overlay()
            except Exception:
                log.debug(
                    "Failed to refresh misspelling overlay surface",
                    exc_info=True,
                )


def _load_misspellings(
    *,
    previous_token: MisspellingsSourceToken | None,
) -> _MisspellingsLoadResult:
    """Reload the store off-thread only when the source token is stale."""
    from sase.history.prompt_misspellings import (
        load_misspellings,
        misspellings_source_token,
    )

    source_token = misspellings_source_token()
    if source_token == previous_token:
        return _MisspellingsLoadResult(
            source_token=source_token,
            misspelled=None,
            allowed=None,
        )
    sets = load_misspellings()
    return _MisspellingsLoadResult(
        source_token=source_token,
        misspelled=frozenset(word.casefold() for word in sets.misspelled),
        allowed=frozenset(word.casefold() for word in sets.allowed),
    )


def _persist_record(word: str) -> None:
    from sase.history.prompt_misspellings import record_misspelling

    record_misspelling(word)


def _persist_allow(word: str) -> None:
    from sase.history.prompt_misspellings import allow_word

    allow_word(word)


def _persist_forget(word: str) -> None:
    from sase.history.prompt_misspellings import forget_misspelling

    forget_misspelling(word)

"""Off-thread next-word prediction corpus warm cache for the TUI app.

Builds :class:`PromptPredictionRow` inputs from the sharded prompt history
next to the history-word warm job, compiles the history and session corpora
through the frozen ``sase_core_rs`` handles, swaps them in atomically on the
UI thread, and composes the prediction model widgets query without disk I/O.

A cold or missing model means no ghost: predictors degrade to silence, a
missing binding leaves the model ``None`` for the session with no toast, and
any prediction error disables the feature for the session and is logged once.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    from sase.core.prompt_prediction_facade import (
        PromptPredictionCorpus,
        PromptPredictionModel,
    )
    from sase.core.prompt_prediction_wire import PromptPredictionRow
    from sase.history.prompt_prediction_archive import ArchivePredictionToken
    from sase.history.prompt_prediction_rows import (
        PromptPredictionProjectResolver,
        PromptPredictionSourceToken,
    )

log = logging.getLogger(__name__)

_SESSION_TEXT_LIMIT: Final = 50


@dataclass(frozen=True, slots=True)
class _PromptPredictionLoadResult:
    """Off-thread prediction cache load result (already-composed model)."""

    source_token: PromptPredictionSourceToken
    history_corpus: PromptPredictionCorpus | None
    session_corpus: PromptPredictionCorpus | None
    archive_corpus: PromptPredictionCorpus | None
    archive_token: ArchivePredictionToken | None
    archive_built_at: float
    model: PromptPredictionModel | None
    history_texts: frozenset[str]
    resolver: PromptPredictionProjectResolver | None


class StartupPromptPredictionMixin:
    """Mixin providing an app-global, memory-only prediction model cache."""

    _prompt_prediction_history_corpus: PromptPredictionCorpus | None
    _prompt_prediction_session_corpus: PromptPredictionCorpus | None
    _prompt_prediction_archive_corpus: PromptPredictionCorpus | None
    _prompt_prediction_archive_token: ArchivePredictionToken | None
    _prompt_prediction_archive_built_at: float
    _prompt_prediction_archive_primed: bool
    _prompt_prediction_model: PromptPredictionModel | None
    _prompt_prediction_source_token: PromptPredictionSourceToken | None
    _prompt_prediction_history_texts: frozenset[str]
    _prompt_prediction_project_resolver: PromptPredictionProjectResolver | None
    _prompt_prediction_session_texts: list[tuple[str, float]]
    _prompt_prediction_session_dirty: bool
    _prompt_prediction_rebuild_in_flight: bool
    _prompt_prediction_rebuild_pending: bool
    _prompt_prediction_disabled: bool
    _prompt_prediction_unavailable: bool
    _prompt_prediction_error_logged: bool

    def get_prompt_prediction_model(self: Any) -> PromptPredictionModel | None:
        """Return the warm prediction model without touching disk."""
        if self._prompt_prediction_disabled:
            return None
        return self._prompt_prediction_model

    def get_prompt_prediction_project(self: Any, text: str) -> str | None:
        """Return the canonical project key for a draft, without disk I/O."""
        resolver = self._prompt_prediction_project_resolver
        if resolver is not None:
            try:
                project = resolver.resolve(text)
            except Exception:
                project = None
            if project is not None:
                return project
        return self._prompt_bar_project_key()

    def prompt_prediction_disabled(self: Any) -> bool:
        """Return whether prediction is disabled for this session."""
        return bool(
            self._prompt_prediction_disabled or self._prompt_prediction_unavailable
        )

    def disable_prompt_prediction(self: Any) -> None:
        """Disable prediction for the session, logging only the first time."""
        self._prompt_prediction_disabled = True
        if not self._prompt_prediction_error_logged:
            self._prompt_prediction_error_logged = True
            log.warning("Prompt prediction disabled for this session")

    def warm_prompt_prediction(self: Any) -> None:
        """Schedule an off-thread prediction corpus staleness check and rebuild."""
        if self._prompt_prediction_disabled or self._prompt_prediction_unavailable:
            return
        try:
            settings = self.get_prompt_completion_settings()
            if getattr(settings, "next_word", "chain") == "off":
                return
        except Exception:
            pass
        if self._prompt_prediction_rebuild_in_flight:
            self._prompt_prediction_rebuild_pending = True
            return

        self._prompt_prediction_rebuild_in_flight = True
        self._prompt_prediction_rebuild_pending = False
        session_dirty = self._prompt_prediction_session_dirty
        self._prompt_prediction_session_dirty = False
        # An empty history still records its source token on swap, so a
        # second warm with an unchanged token is a no-op instead of a
        # full rebuild loop.
        previous_token = self._prompt_prediction_source_token
        # The archive corpus first builds after first paint: the priming
        # swap below schedules a follow-up warm, so the startup pass keeps
        # first paint off the multi-thousand-document archive read.
        include_archive = (
            bool(self._prompt_prediction_archive_primed)
            and self._prompt_prediction_archive_enabled()
        )

        async def run_rebuild() -> None:
            await self._run_prompt_prediction_rebuild(
                previous_token=previous_token,
                history_corpus=self._prompt_prediction_history_corpus,
                session_corpus=self._prompt_prediction_session_corpus,
                session_texts=tuple(self._prompt_prediction_session_texts),
                session_dirty=session_dirty,
                known_history_texts=self._prompt_prediction_history_texts,
                known_resolver=self._prompt_prediction_project_resolver,
                include_archive=include_archive,
                archive_corpus=self._prompt_prediction_archive_corpus,
                archive_token=self._prompt_prediction_archive_token,
                archive_built_at=self._prompt_prediction_archive_built_at,
            )

        try:
            self.run_worker(
                cast(Any, run_rebuild),
                name="prompt-prediction",
                group="prompt-prediction",
                exclusive=False,
            )
        except Exception:
            self._prompt_prediction_rebuild_in_flight = False
            self._prompt_prediction_session_dirty = (
                self._prompt_prediction_session_dirty or session_dirty
            )
            log.exception("Failed to schedule prompt prediction rebuild")

    def note_submitted_prompt_texts(self: Any, texts: list[str]) -> None:
        """Record submitted prompt texts for the session prediction source.

        Keeps a bounded list with submit times, prunes texts already in
        history, and rebuilds the tiny session corpus off-thread with
        coalescing. Never raises: the submit path must not break on cache
        bookkeeping.
        """
        try:
            now = time.time()
            history_texts = self._prompt_prediction_history_texts
            session_texts = self._prompt_prediction_session_texts
            for text in texts:
                if text and text.strip():
                    session_texts.append((text, now))
            if len(session_texts) > _SESSION_TEXT_LIMIT:
                del session_texts[: len(session_texts) - _SESSION_TEXT_LIMIT]
            if history_texts:
                self._prompt_prediction_session_texts = _prune_session_texts(
                    session_texts, history_texts
                )
            self._prompt_prediction_session_dirty = True
        except Exception:
            log.debug("Failed to record submitted prompt texts", exc_info=True)
            return
        try:
            self.warm_prompt_prediction()
        except Exception:
            log.debug("Failed to schedule session prediction rebuild", exc_info=True)

    def _prompt_prediction_archive_enabled(self: Any) -> bool:
        """Return whether the archive source is enabled, without disk I/O."""
        try:
            settings = self.get_prompt_completion_settings()
        except Exception:
            return False
        try:
            sources = getattr(settings, "next_word_sources", ("history",))
        except Exception:
            return False
        return any(
            isinstance(item, str) and item.strip().lower() == "archive"
            for item in (sources if isinstance(sources, (list, tuple)) else ())
        )

    def _prompt_bar_project_key(self: Any) -> str | None:
        """Return the mounted prompt bar's project key from memory, if known."""
        try:
            ctx = getattr(self, "_prompt_context", None)
        except Exception:
            return None
        if ctx is None or bool(getattr(ctx, "is_home_mode", False)):
            return None
        project_name = getattr(ctx, "project_name", None)
        if isinstance(project_name, str) and project_name:
            return project_name
        return None

    async def _run_prompt_prediction_rebuild(
        self: Any,
        *,
        previous_token: PromptPredictionSourceToken | None,
        history_corpus: PromptPredictionCorpus | None,
        session_corpus: PromptPredictionCorpus | None,
        session_texts: tuple[tuple[str, float], ...],
        session_dirty: bool,
        known_history_texts: frozenset[str],
        known_resolver: PromptPredictionProjectResolver | None,
        include_archive: bool,
        archive_corpus: PromptPredictionCorpus | None,
        archive_token: ArchivePredictionToken | None,
        archive_built_at: float,
    ) -> None:
        """Build prediction corpora off-thread and swap them on the UI task."""
        import asyncio

        try:
            result = await asyncio.to_thread(
                _load_prompt_prediction_caches,
                previous_token=previous_token,
                history_corpus=history_corpus,
                session_corpus=session_corpus,
                session_texts=session_texts,
                session_dirty=session_dirty,
                known_history_texts=known_history_texts,
                known_resolver=known_resolver,
                include_archive=include_archive,
                archive_corpus=archive_corpus,
                archive_token=archive_token,
                archive_built_at=archive_built_at,
            )
        except (AttributeError, ImportError):
            if not self._prompt_prediction_unavailable:
                self._prompt_prediction_unavailable = True
                log.info("Prompt prediction unavailable: sase_core_rs binding missing")
            self._prompt_prediction_model = None
            self._prompt_prediction_rebuild_in_flight = False
            if self._prompt_prediction_rebuild_pending:
                self._prompt_prediction_rebuild_pending = False
            return
        except Exception:
            if not self._prompt_prediction_error_logged:
                self._prompt_prediction_error_logged = True
                log.exception("Prompt prediction rebuild failed")
            else:
                log.debug("Prompt prediction rebuild failed", exc_info=True)
            self._prompt_prediction_rebuild_in_flight = False
        else:
            self._prompt_prediction_rebuild_in_flight = False
            if result is not None:
                self._swap_prompt_prediction_caches(result)
            if self._prompt_prediction_rebuild_pending:
                self._prompt_prediction_rebuild_pending = False
                self.warm_prompt_prediction()
            return

        if self._prompt_prediction_rebuild_pending:
            self._prompt_prediction_rebuild_pending = False
            self.warm_prompt_prediction()

    def _swap_prompt_prediction_caches(
        self: Any, result: _PromptPredictionLoadResult
    ) -> None:
        """Atomically publish freshly built corpora and the composed model."""
        self._prompt_prediction_history_corpus = result.history_corpus
        self._prompt_prediction_session_corpus = result.session_corpus
        self._prompt_prediction_archive_corpus = result.archive_corpus
        self._prompt_prediction_archive_token = result.archive_token
        self._prompt_prediction_archive_built_at = result.archive_built_at
        self._prompt_prediction_model = result.model
        self._prompt_prediction_source_token = result.source_token
        self._prompt_prediction_history_texts = result.history_texts
        if result.resolver is not None:
            self._prompt_prediction_project_resolver = result.resolver
        if result.history_texts:
            self._prompt_prediction_session_texts = _prune_session_texts(
                self._prompt_prediction_session_texts, result.history_texts
            )
        if not self._prompt_prediction_archive_primed:
            # First paint has happened by the time a model lands: prime the
            # archive lane so the next warm may build it off-thread.
            self._prompt_prediction_archive_primed = True
            try:
                self.warm_prompt_prediction()
            except Exception:
                log.debug("Failed to schedule archive prediction warm", exc_info=True)
        self._refresh_visible_prompt_prediction_surfaces()

    def _refresh_visible_prompt_prediction_surfaces(self: Any) -> None:
        """Redraw armed next-word ghosts once a warm model lands."""
        try:
            from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

            text_areas = list(self.query(PromptTextArea))
        except Exception:
            return
        for text_area in text_areas:
            try:
                if not getattr(text_area, "is_mounted", False):
                    continue
                refresh = getattr(text_area, "_refresh_visible_next_word_surface", None)
                if callable(refresh):
                    refresh()
            except Exception:
                log.debug("Failed to refresh next-word surface", exc_info=True)


def _prune_session_texts(
    session_texts: list[tuple[str, float]] | tuple[tuple[str, float], ...],
    history_texts: frozenset[str],
) -> list[tuple[str, float]]:
    """Drop session texts whose normalized text now appears in history."""
    from sase.history.prompt_prediction_rows import normalize_session_text

    return [
        (text, epoch)
        for text, epoch in session_texts
        if normalize_session_text(text) not in history_texts
    ]


def _load_prompt_prediction_caches(
    *,
    previous_token: PromptPredictionSourceToken | None,
    history_corpus: PromptPredictionCorpus | None,
    session_corpus: PromptPredictionCorpus | None,
    session_texts: tuple[tuple[str, float], ...],
    session_dirty: bool,
    known_history_texts: frozenset[str],
    known_resolver: PromptPredictionProjectResolver | None,
    include_archive: bool,
    archive_corpus: PromptPredictionCorpus | None,
    archive_token: ArchivePredictionToken | None,
    archive_built_at: float,
) -> _PromptPredictionLoadResult | None:
    """Read row inputs and compile corpora, rebuilding only what went stale.

    Any token change (shards or deletions) recompiles the history corpus
    so baked-in exclusions track the deletions store; the session corpus
    recompiles when dirty, when history rebuilds, or on a deletions-only
    change while session texts exist. The archive corpus rebuilds only on
    token change and at most every ten minutes; disabling the source drops
    it without a rebuild.
    """
    import time as _time

    from sase.core.prompt_prediction_facade import (
        PromptPredictionCorpus,
        PromptPredictionModel,
    )
    from sase.core.prompt_prediction_wire import PromptPredictionModelConfig
    from sase.history.prompt_prediction_archive import (
        ARCHIVE_CORPUS_WEIGHT,
        ARCHIVE_REBUILD_MIN_INTERVAL_SECONDS,
        ARCHIVE_SOURCE_ROLE,
        archive_prediction_source_token,
    )
    from sase.history.prompt_prediction_rows import (
        build_prompt_prediction_project_resolver,
        build_prompt_prediction_rows,
        normalize_session_text,
        prompt_prediction_source_token,
    )

    source_token = prompt_prediction_source_token()
    previous_shards = None if previous_token is None else previous_token[0]
    previous_deletions = None if previous_token is None else previous_token[1]
    history_stale = previous_token is None or previous_shards != source_token[0]
    deletions_stale = previous_deletions != source_token[1]

    now = _time.time()
    archive_token_now = archive_prediction_source_token() if include_archive else None
    archive_throttled = (
        archive_built_at > 0
        and now - archive_built_at < ARCHIVE_REBUILD_MIN_INTERVAL_SECONDS
    )
    if include_archive:
        archive_stale = archive_token is None or archive_token_now != archive_token
        want_archive_rebuild = (archive_stale or archive_corpus is None) and (
            not archive_throttled
        )
    else:
        archive_stale = archive_corpus is not None
        want_archive_rebuild = False

    pruned_session = tuple(
        (text, epoch) for text, epoch in session_texts if text and text.strip()
    )
    if (
        not history_stale
        and not session_dirty
        and not deletions_stale
        and not archive_stale
        and not want_archive_rebuild
    ):
        return None

    resolver = known_resolver
    history_texts = known_history_texts
    history_seed: list[str] | None = None
    if history_stale or deletions_stale:
        resolver = build_prompt_prediction_project_resolver()
        rows = build_prompt_prediction_rows(resolve_project=resolver.resolve)
        history_seed = [row.text for row in rows]
        history_texts = frozenset(normalize_session_text(row.text) for row in rows)
        pruned_session = tuple(
            (text, epoch)
            for text, epoch in pruned_session
            if normalize_session_text(text) not in history_texts
        )
        history_corpus = _compile_history_corpus(rows) if rows else None

    rebuild_session = session_dirty or history_stale or deletions_stale
    if rebuild_session:
        session_rows = _session_rows(pruned_session, resolver)
        session_corpus = _compile_session_corpus(session_rows) if session_rows else None

    if want_archive_rebuild:
        rebuilt = _compile_archive_corpus(history_seed)
        if rebuilt is not None:
            archive_corpus = rebuilt
        else:
            # No archive rows (or a failed compile): drop any stale corpus
            # but still record the token and build time, so the token gate
            # and 10-minute throttle apply to later warms.
            archive_corpus = None
        archive_built_at = now
        archive_token = archive_token_now
    elif not include_archive:
        archive_corpus = None
        archive_token = None

    sources: list[tuple[PromptPredictionCorpus, str, float]] = []
    if history_corpus is not None:
        sources.append((history_corpus, "history", 1.0))
    if session_corpus is not None:
        sources.append((session_corpus, "session", 1.0))
    if include_archive and archive_corpus is not None:
        sources.append((archive_corpus, ARCHIVE_SOURCE_ROLE, ARCHIVE_CORPUS_WEIGHT))
    model: PromptPredictionModel | None = None
    if sources:
        model = PromptPredictionModel.compose(sources, PromptPredictionModelConfig())

    return _PromptPredictionLoadResult(
        source_token=source_token,
        history_corpus=history_corpus,
        session_corpus=session_corpus,
        archive_corpus=archive_corpus if include_archive else None,
        archive_token=archive_token if include_archive else None,
        archive_built_at=archive_built_at,
        model=model,
        history_texts=history_texts,
        resolver=resolver,
    )


def _compile_history_corpus(
    rows: list[PromptPredictionRow],
) -> PromptPredictionCorpus:
    """Compile history rows with the deletions store as excluded words."""
    import time as _time

    from sase.core.prompt_prediction_facade import PromptPredictionCorpus
    from sase.core.prompt_prediction_wire import PromptPredictionCorpusOptions
    from sase.history.prompt_word_deletions import load_deleted_prompt_words

    return PromptPredictionCorpus.compile(
        rows,
        PromptPredictionCorpusOptions(
            now_epoch=int(_time.time()),
            excluded_words=sorted(load_deleted_prompt_words()),
        ),
    )


def _session_rows(
    session_texts: tuple[tuple[str, float], ...],
    resolver: PromptPredictionProjectResolver | None,
) -> list[PromptPredictionRow]:
    """Build typed session-source rows from bounded submit-time texts."""
    from sase.core.prompt_prediction_wire import PromptPredictionRow

    resolve = resolver.resolve if resolver is not None else (lambda _text: None)
    return [
        PromptPredictionRow(
            text=text,
            epoch_seconds=int(epoch),
            project=resolve(text),
            origin="typed",
            cancelled=False,
        )
        for text, epoch in session_texts
    ]


def _compile_session_corpus(
    rows: list[PromptPredictionRow],
) -> PromptPredictionCorpus:
    """Compile session rows with the current deletions as excluded words."""
    import time as _time

    from sase.core.prompt_prediction_facade import PromptPredictionCorpus
    from sase.core.prompt_prediction_wire import PromptPredictionCorpusOptions
    from sase.history.prompt_word_deletions import load_deleted_prompt_words

    return PromptPredictionCorpus.compile(
        rows,
        PromptPredictionCorpusOptions(
            now_epoch=int(_time.time()),
            excluded_words=sorted(load_deleted_prompt_words()),
        ),
    )


def _compile_archive_corpus(
    history_seed: list[str] | None,
) -> PromptPredictionCorpus | None:
    """Compile pruned archive rows, or ``None`` when there is nothing to add.

    Never raises: an empty archive or a failed read degrades the model to
    history-only, and the caller records the token so the next attempt waits
    for the month directories to change.
    """
    import time as _time

    from sase.core.prompt_prediction_facade import PromptPredictionCorpus
    from sase.core.prompt_prediction_wire import PromptPredictionCorpusOptions
    from sase.history.prompt_prediction_archive import build_archive_prediction_rows
    from sase.history.prompt_word_deletions import load_deleted_prompt_words

    try:
        rows = build_archive_prediction_rows(history_texts=history_seed)
    except Exception:
        log.debug("Archive prediction rows failed", exc_info=True)
        return None
    if not rows:
        return None
    try:
        return PromptPredictionCorpus.compile(
            rows,
            PromptPredictionCorpusOptions(
                now_epoch=int(_time.time()),
                prune_singleton_contexts=True,
                excluded_words=sorted(load_deleted_prompt_words()),
            ),
        )
    except Exception:
        log.debug("Archive prediction compile failed", exc_info=True)
        return None

"""Tests for the off-thread next-word prediction warm cache."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions._startup_prompt_prediction import (
    StartupPromptPredictionMixin,
    _load_prompt_prediction_caches,
)
from sase.core.prompt_prediction_wire import PromptPredictionRow
from sase.history.prompt_prediction_rows import PromptPredictionProjectResolver

_SHARD_TOKEN = (("260101.json", 10, 20),)
_DELETIONS_TOKEN = ("/tmp/deleted.json", -1, -1)
_SOURCE_TOKEN = (_SHARD_TOKEN, _DELETIONS_TOKEN)


def _rows() -> list[PromptPredictionRow]:
    return [
        PromptPredictionRow(
            text="help me implement the plan",
            epoch_seconds=100,
            project="sase",
            origin="typed",
        ),
        PromptPredictionRow(
            text="help me review the plan",
            epoch_seconds=101,
            project="sase",
            origin="typed",
        ),
    ]


class _PredictionCacheApp(StartupPromptPredictionMixin):
    def __init__(self) -> None:
        self._prompt_prediction_history_corpus = None
        self._prompt_prediction_session_corpus = None
        self._prompt_prediction_archive_corpus = None
        self._prompt_prediction_archive_token = None
        self._prompt_prediction_archive_built_at = 0.0
        self._prompt_prediction_archive_primed = False
        self._prompt_prediction_model = None
        self._prompt_prediction_source_token = None
        self._prompt_prediction_history_texts = frozenset()
        self._prompt_prediction_project_resolver = None
        self._prompt_prediction_session_texts = []
        self._prompt_prediction_session_dirty = False
        self._prompt_prediction_rebuild_in_flight = False
        self._prompt_prediction_rebuild_pending = False
        self._prompt_prediction_disabled = False
        self._prompt_prediction_unavailable = False
        self._prompt_prediction_error_logged = False
        self._prompt_context = None
        self.refreshes = 0
        self.worker_task: asyncio.Task[None] | None = None

    def run_worker(self, worker: Any, **_kwargs: Any) -> None:
        self.worker_task = asyncio.create_task(worker())

    def _refresh_visible_prompt_prediction_surfaces(self) -> None:
        self.refreshes += 1


def _loader_patches(token: Any = _SOURCE_TOKEN):  # type: ignore[no-untyped-def]
    return (
        patch(
            "sase.history.prompt_prediction_rows.prompt_prediction_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_prediction_rows.build_prompt_prediction_rows",
            return_value=_rows(),
        ),
        patch(
            "sase.history.prompt_prediction_rows.build_prompt_prediction_project_resolver",
            return_value=PromptPredictionProjectResolver(mapping={"sase": "sase"}),
        ),
        patch(
            "sase.history.prompt_word_deletions.load_deleted_prompt_words",
            return_value=[],
        ),
    )


def test_loader_builds_and_composes_on_first_warm() -> None:
    patches = _loader_patches()
    with patches[0], patches[1], patches[2], patches[3]:
        result = _load_prompt_prediction_caches(
            previous_token=None,
            history_corpus=None,
            session_corpus=None,
            session_texts=(),
            session_dirty=False,
            known_history_texts=frozenset(),
            known_resolver=None,
            include_archive=False,
            archive_corpus=None,
            archive_token=None,
            archive_built_at=0.0,
        )
    assert result is not None
    assert result.source_token == _SOURCE_TOKEN
    assert result.history_corpus is not None
    assert result.session_corpus is None
    assert result.model is not None
    assert result.history_texts == frozenset(
        {"help me implement the plan", "help me review the plan"}
    )
    assert result.resolver is not None
    assert result.resolver.mapping["sase"] == "sase"
    from sase.core.prompt_prediction_wire import PromptPredictionRequest

    predicted = result.model.predict(
        PromptPredictionRequest(text_before_cursor="help me")
    )
    assert isinstance(predicted.context_words, list)


def test_loader_skips_rebuild_for_unchanged_token() -> None:
    patches = _loader_patches()
    with (
        patches[0],
        patch(
            "sase.history.prompt_prediction_rows.build_prompt_prediction_rows",
        ) as build,
        patch(
            "sase.core.prompt_prediction_facade.PromptPredictionCorpus.compile",
        ) as compile,
    ):
        result = _load_prompt_prediction_caches(
            previous_token=_SOURCE_TOKEN,
            history_corpus=object(),
            session_corpus=None,
            session_texts=(),
            session_dirty=False,
            known_history_texts=frozenset(),
            known_resolver=None,
            include_archive=False,
            archive_corpus=None,
            archive_token=None,
            archive_built_at=0.0,
        )
    assert result is None
    build.assert_not_called()
    compile.assert_not_called()


def test_loader_rebuilds_only_session_when_history_fresh() -> None:
    from sase.core.prompt_prediction_facade import PromptPredictionCorpus
    from sase.core.prompt_prediction_wire import PromptPredictionCorpusOptions

    patches = _loader_patches()
    history_corpus = PromptPredictionCorpus.compile(
        _rows(), PromptPredictionCorpusOptions(now_epoch=200)
    )
    session_texts = (("a brand new submitted prompt here", time.time()),)
    with (
        patches[0],
        patches[2],
        patches[3],
        patch(
            "sase.history.prompt_prediction_rows.build_prompt_prediction_rows",
        ) as build,
    ):
        result = _load_prompt_prediction_caches(
            previous_token=_SOURCE_TOKEN,
            history_corpus=history_corpus,
            session_corpus=None,
            session_texts=session_texts,
            session_dirty=True,
            known_history_texts=frozenset(),
            known_resolver=PromptPredictionProjectResolver(mapping={}),
            include_archive=False,
            archive_corpus=None,
            archive_token=None,
            archive_built_at=0.0,
        )
    assert result is not None
    assert result.history_corpus is history_corpus
    assert result.session_corpus is not None
    assert result.model is not None
    build.assert_not_called()


async def test_warm_swaps_atomically_and_prunes_session() -> None:
    app = _PredictionCacheApp()
    app._prompt_prediction_session_texts = [
        ("help me implement the plan", 1.0),
        ("a brand new submitted prompt here", 2.0),
    ]
    patches = _loader_patches()
    with patches[0], patches[1], patches[2], patches[3]:
        app.warm_prompt_prediction()
        assert app.worker_task is not None
        await app.worker_task
        # The priming swap schedules a post-paint follow-up warm, which
        # is a no-op here because the archive source is not enabled.
        assert app._prompt_prediction_archive_primed is True
        assert app.worker_task is not None
        await app.worker_task

    assert app._prompt_prediction_model is not None
    assert app._prompt_prediction_history_corpus is not None
    assert app._prompt_prediction_source_token == _SOURCE_TOKEN
    assert app.refreshes == 1
    # The session text now in history is dropped on swap.
    assert app._prompt_prediction_session_texts == [
        ("a brand new submitted prompt here", 2.0)
    ]


def test_note_submitted_trims_to_bound_and_marks_dirty() -> None:
    app = _PredictionCacheApp()
    app._prompt_prediction_session_texts = [
        (f"older prompt {index}", 1.0) for index in range(49)
    ]
    with patch.object(app, "warm_prompt_prediction") as warm:
        app.note_submitted_prompt_texts(["newest prompt one", "newest prompt two"])
    assert len(app._prompt_prediction_session_texts) == 50
    assert app._prompt_prediction_session_texts[-2][0] == "newest prompt one"
    assert app._prompt_prediction_session_texts[-1][0] == "newest prompt two"
    assert app._prompt_prediction_session_dirty is True
    warm.assert_called_once_with()


def test_note_submitted_skips_blank_texts() -> None:
    app = _PredictionCacheApp()
    with patch.object(app, "warm_prompt_prediction"):
        app.note_submitted_prompt_texts(["", "   ", "real prompt here"])
    assert [text for text, _epoch in app._prompt_prediction_session_texts] == [
        "real prompt here"
    ]


async def test_missing_binding_degrades_to_cold_without_raise() -> None:
    app = _PredictionCacheApp()
    patches = _loader_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "sase.core.prompt_prediction_facade.PromptPredictionCorpus.compile",
            side_effect=ImportError("no extension"),
        ),
    ):
        app.warm_prompt_prediction()
        assert app.worker_task is not None
        await app.worker_task

    assert app._prompt_prediction_model is None
    assert app._prompt_prediction_unavailable is True
    assert app.prompt_prediction_disabled() is True
    # Further warms short-circuit without scheduling work.
    app.worker_task = None
    app.warm_prompt_prediction()
    assert app.worker_task is None


def test_accessors_touch_no_disk() -> None:
    app = _PredictionCacheApp()
    app._prompt_prediction_project_resolver = PromptPredictionProjectResolver(
        mapping={"sase": "sase"}
    )
    app._prompt_context = SimpleNamespace(project_name="sase", is_home_mode=False)
    with (
        patch(
            "sase.history.prompt_prediction_rows.iter_shard_paths_newest_first",
            side_effect=AssertionError("disk read"),
        ),
        patch(
            "sase.history.prompt_prediction_rows.load_shard",
            side_effect=AssertionError("disk read"),
        ),
        patch(
            "sase.history.prompt_prediction_rows.prompt_prediction_source_token",
            side_effect=AssertionError("disk read"),
        ),
        patch(
            "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
            side_effect=AssertionError("disk read"),
        ),
    ):
        assert app.get_prompt_prediction_model() is None
        assert app.get_prompt_prediction_project("#gh:sase help me") == "sase"
        assert app.get_prompt_prediction_project("plain draft") == "sase"


def test_project_falls_back_to_bar_context_and_home_is_none() -> None:
    app = _PredictionCacheApp()
    assert app.get_prompt_prediction_project("plain draft") is None
    app._prompt_context = SimpleNamespace(project_name="sase", is_home_mode=True)
    assert app.get_prompt_prediction_project("plain draft") is None
    app._prompt_context = SimpleNamespace(project_name="sase", is_home_mode=False)
    assert app.get_prompt_prediction_project("plain draft") == "sase"


def test_disable_is_session_scoped_and_idempotent() -> None:
    app = _PredictionCacheApp()
    assert app.prompt_prediction_disabled() is False
    app.disable_prompt_prediction()
    app.disable_prompt_prediction()
    assert app.prompt_prediction_disabled() is True


_ARCHIVE_TOKEN = (("sase", "202609", 7, 3),)


def _archive_rows() -> list[PromptPredictionRow]:
    return [
        PromptPredictionRow(
            text="archived prose about the plan",
            epoch_seconds=200,
            project="sase",
        )
    ]


def test_loader_builds_pruned_archive_at_low_weight() -> None:
    from sase.core.prompt_prediction_facade import (
        PromptPredictionCorpus,
        PromptPredictionModel,
    )

    real_compile = PromptPredictionCorpus.compile
    real_compose = PromptPredictionModel.compose
    seen_options: list[Any] = []
    seen_sources: list[list[tuple[str, float]]] = []

    def spy_compile(rows: Any, options: Any) -> Any:  # type: ignore[no-untyped-def]
        seen_options.append(options)
        return real_compile(rows, options)

    def spy_compose(sources: Any, config: Any) -> Any:  # type: ignore[no-untyped-def]
        seen_sources.append([(role, weight) for _corpus, role, weight in sources])
        return real_compose(sources, config)

    patches = _loader_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "sase.history.prompt_prediction_archive.archive_prediction_source_token",
            return_value=_ARCHIVE_TOKEN,
        ),
        patch(
            "sase.history.prompt_prediction_archive.build_archive_prediction_rows",
            return_value=_archive_rows(),
        ),
        patch.object(
            PromptPredictionCorpus, "compile", autospec=True, side_effect=spy_compile
        ),
        patch.object(
            PromptPredictionModel, "compose", autospec=True, side_effect=spy_compose
        ),
    ):
        result = _load_prompt_prediction_caches(
            previous_token=None,
            history_corpus=None,
            session_corpus=None,
            session_texts=(),
            session_dirty=False,
            known_history_texts=frozenset(),
            known_resolver=None,
            include_archive=True,
            archive_corpus=None,
            archive_token=None,
            archive_built_at=0.0,
        )
    assert result is not None
    assert result.archive_corpus is not None
    assert result.archive_token == _ARCHIVE_TOKEN
    assert result.archive_built_at > 0
    # The archive compile prunes singleton contexts; history does not.
    assert [options.prune_singleton_contexts for options in seen_options] == [
        False,
        True,
    ]
    assert seen_sources and seen_sources[-1] == [
        ("history", 1.0),
        ("archive", 0.25),
    ]


def test_loader_skips_archive_rebuild_within_throttle() -> None:
    import time as _time

    from sase.core.prompt_prediction_facade import PromptPredictionCorpus

    patches = _loader_patches()
    with (
        patches[0],
        patch(
            "sase.history.prompt_prediction_archive.archive_prediction_source_token",
            return_value=_ARCHIVE_TOKEN,
        ),
        patch(
            "sase.history.prompt_prediction_archive.build_archive_prediction_rows",
        ) as build_archive,
        patch.object(PromptPredictionCorpus, "compile", autospec=True) as compile,
    ):
        result = _load_prompt_prediction_caches(
            previous_token=_SOURCE_TOKEN,
            history_corpus=object(),
            session_corpus=None,
            session_texts=(),
            session_dirty=False,
            known_history_texts=frozenset(),
            known_resolver=None,
            include_archive=True,
            archive_corpus=object(),
            archive_token=_ARCHIVE_TOKEN,
            archive_built_at=_time.time(),
        )
    assert result is None
    build_archive.assert_not_called()
    compile.assert_not_called()


def test_loader_drops_archive_when_source_disabled() -> None:
    from sase.core.prompt_prediction_facade import (
        PromptPredictionCorpus,
        PromptPredictionModel,
    )
    from sase.core.prompt_prediction_wire import PromptPredictionCorpusOptions

    history_corpus = PromptPredictionCorpus.compile(
        _rows(), PromptPredictionCorpusOptions(now_epoch=200)
    )
    real_compose = PromptPredictionModel.compose
    seen_sources: list[list[tuple[str, float]]] = []

    def spy_compose(sources: Any, config: Any) -> Any:  # type: ignore[no-untyped-def]
        seen_sources.append([(role, weight) for _corpus, role, weight in sources])
        return real_compose(sources, config)

    patches = _loader_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch.object(
            PromptPredictionModel, "compose", autospec=True, side_effect=spy_compose
        ),
    ):
        result = _load_prompt_prediction_caches(
            previous_token=_SOURCE_TOKEN,
            history_corpus=history_corpus,
            session_corpus=None,
            session_texts=(),
            session_dirty=False,
            known_history_texts=frozenset(),
            known_resolver=None,
            include_archive=False,
            archive_corpus=object(),
            archive_token=_ARCHIVE_TOKEN,
            archive_built_at=0.0,
        )
    assert result is not None
    assert result.archive_corpus is None
    assert result.archive_token is None
    assert seen_sources and all(
        role != "archive" for roles in seen_sources for role, _ in roles
    )


def test_compile_archive_corpus_never_raises() -> None:
    from sase.ace.tui.actions._startup_prompt_prediction import (
        _compile_archive_corpus,
    )

    with patch(
        "sase.history.prompt_prediction_archive.build_archive_prediction_rows",
        side_effect=OSError("sidecar gone"),
    ):
        assert _compile_archive_corpus(None) is None


def test_loader_builds_empty_archive_once_across_three_warms() -> None:
    import time as _time

    patches = _loader_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "sase.history.prompt_prediction_archive.archive_prediction_source_token",
            return_value=_ARCHIVE_TOKEN,
        ),
        patch(
            "sase.history.prompt_prediction_archive.build_archive_prediction_rows",
            return_value=[],
        ) as build_archive,
    ):
        first = _load_prompt_prediction_caches(
            previous_token=None,
            history_corpus=None,
            session_corpus=None,
            session_texts=(),
            session_dirty=False,
            known_history_texts=frozenset(),
            known_resolver=None,
            include_archive=True,
            archive_corpus=None,
            archive_token=None,
            archive_built_at=0.0,
        )
    assert first is not None
    assert first.archive_corpus is None
    assert first.archive_token == _ARCHIVE_TOKEN
    assert first.archive_built_at > 0
    assert build_archive.call_count == 1
    assert first.history_corpus is not None

    # Two more warms with an unchanged token must not rebuild the empty
    # archive: the build time throttles them.
    for _ in range(2):
        with (
            patch(
                "sase.history.prompt_prediction_rows.prompt_prediction_source_token",
                return_value=_SOURCE_TOKEN,
            ),
            patch(
                "sase.history.prompt_prediction_archive.archive_prediction_source_token",
                return_value=_ARCHIVE_TOKEN,
            ),
            patch(
                "sase.history.prompt_prediction_archive.build_archive_prediction_rows",
            ) as rebuild,
        ):
            result = _load_prompt_prediction_caches(
                previous_token=_SOURCE_TOKEN,
                history_corpus=first.history_corpus,
                session_corpus=None,
                session_texts=(),
                session_dirty=False,
                known_history_texts=first.history_texts,
                known_resolver=first.resolver,
                include_archive=True,
                archive_corpus=None,
                archive_token=_ARCHIVE_TOKEN,
                archive_built_at=first.archive_built_at,
            )
        assert result is None
        rebuild.assert_not_called()
    assert build_archive.call_count == 1
    assert _time.time() - first.archive_built_at < 600

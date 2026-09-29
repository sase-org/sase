"""Tests for the typed prompt prediction Rust facade and wire mirror."""

from __future__ import annotations

import pytest

from sase.core.prompt_prediction_facade import (
    PROMPT_PREDICTION_SCHEMA_VERSION,
    PromptPredictionCorpus,
    PromptPredictionModel,
    evaluate_prompt_prediction_replay,
)
from sase.core.prompt_prediction_wire import (
    PROMPT_PREDICTION_WIRE_SCHEMA_VERSION,
    PromptPredictionCorpusOptions,
    PromptPredictionModelConfig,
    PromptPredictionReplayOptions,
    PromptPredictionRequest,
    PromptPredictionRow,
    PromptPrefixRankRequest,
    prompt_prediction_replay_report_from_dict,
    prompt_prediction_result_from_dict,
    prompt_prefix_rank_result_from_dict,
)


def _rows() -> list[PromptPredictionRow]:
    return [
        PromptPredictionRow(
            text="help me implement the plan",
            epoch_seconds=100,
            project="sase",
            origin="typed",
        ),
        PromptPredictionRow(
            text="help me implement the fix",
            epoch_seconds=101,
            project="sase",
            origin="typed",
        ),
        PromptPredictionRow(
            text="help me implement the docs",
            epoch_seconds=102,
            project="sase",
            origin="typed",
        ),
        PromptPredictionRow(
            text="can you help me review this",
            epoch_seconds=103,
            project="sase",
            origin="typed",
        ),
    ]


@pytest.fixture(scope="module")
def corpus() -> PromptPredictionCorpus:
    return PromptPredictionCorpus.compile(
        _rows(), PromptPredictionCorpusOptions(now_epoch=200)
    )


@pytest.fixture(scope="module")
def model(corpus: PromptPredictionCorpus) -> PromptPredictionModel:
    return PromptPredictionModel.compose(
        [(corpus, "history", 1.0)], PromptPredictionModelConfig()
    )


def test_schema_versions_match_rust() -> None:
    assert PROMPT_PREDICTION_SCHEMA_VERSION == 1
    assert PROMPT_PREDICTION_WIRE_SCHEMA_VERSION == 1


def test_compile_stats(corpus: PromptPredictionCorpus) -> None:
    stats = corpus.stats()
    assert stats.schema_version == 1
    assert stats.rows_used == 4
    assert stats.rows_generated_skipped == 0
    assert len(corpus) > 0


def test_predict_confident_ghost(model: PromptPredictionModel) -> None:
    result = model.predict(
        PromptPredictionRequest(text_before_cursor="help me implement", project="sase")
    )
    assert result.schema_version == 1
    assert result.blocked_reason is None
    assert result.confident is True
    assert result.ghost[:1] == ["the"]
    assert result.candidates


def test_predict_blocked_on_empty_text(
    model: PromptPredictionModel,
) -> None:
    result = model.predict(PromptPredictionRequest(text_before_cursor=""))
    assert result.confident is False
    assert result.blocked_reason is not None
    assert result.ghost == []


def test_rank_prefix(model: PromptPredictionModel) -> None:
    ranked = model.rank_prefix(
        PromptPrefixRankRequest(text_before_word="help me ", prefix="imp")
    )
    assert ranked.schema_version == 1
    assert ranked.matches
    assert ranked.matches[0].key == "implement"


def test_compose_rejects_unknown_role(
    corpus: PromptPredictionCorpus,
) -> None:
    with pytest.raises(ValueError):
        PromptPredictionModel.compose(
            [(corpus, "draft", 1.0)], PromptPredictionModelConfig()
        )


def test_schema_mismatch_raises(
    monkeypatch: pytest.MonkeyPatch,
    corpus: PromptPredictionCorpus,
) -> None:
    import sase.core.prompt_prediction_facade as adapter

    monkeypatch.setattr(adapter, "PROMPT_PREDICTION_SCHEMA_VERSION", 999_999)
    with pytest.raises(RuntimeError):
        PromptPredictionModel.compose(
            [(corpus, "history", 1.0)], PromptPredictionModelConfig()
        )
    assert PROMPT_PREDICTION_SCHEMA_VERSION == 1


def test_result_from_dict_rejects_schema_drift() -> None:
    with pytest.raises(ValueError):
        prompt_prediction_result_from_dict(
            {"schema_version": 999, "blocked_reason": None}
        )


def test_rank_result_from_dict_rejects_schema_drift() -> None:
    with pytest.raises(ValueError):
        prompt_prefix_rank_result_from_dict(
            {"schema_version": 999, "context_words": []}
        )


def _replay_rows() -> list[PromptPredictionRow]:
    return [
        PromptPredictionRow(
            text=f"can you help me implement it {ending}",
            epoch_seconds=100 + index,
            project="sase",
            origin="typed",
        )
        for index, ending in enumerate(
            ["now", "today", "fast", "soon", "well", "please"]
        )
    ]


def test_replay_report_aggregates_only() -> None:
    report = evaluate_prompt_prediction_replay(
        _replay_rows(),
        PromptPredictionReplayOptions(now_epoch=1000),
    )
    assert report.schema_version == 1
    assert report.rows_total == 6
    assert report.rows_typed == 6
    assert report.rows_warmed == 2
    assert report.rows_scored == 4
    assert report.positions_total > 0
    assert [cohort.cohort for cohort in report.cohorts] == [
        "novel",
        "mid",
        "near-duplicate",
    ]
    assert len(report.sweep) == 10 * 8 * 5
    assert report.corpus_bytes > 0
    assert report.latency_us_p95 >= report.latency_us_p50


def test_replay_report_from_dict_rejects_schema_drift() -> None:
    with pytest.raises(ValueError):
        prompt_prediction_replay_report_from_dict({"schema_version": 999})


def test_replay_sweep_points_carry_novel_tallies() -> None:
    report = evaluate_prompt_prediction_replay(
        _replay_rows(),
        PromptPredictionReplayOptions(now_epoch=1000),
    )
    assert report.sweep
    for point in report.sweep:
        assert 0.0 <= point.novel_coverage <= 1.0
        assert (point.novel_precision is None) == (point.novel_coverage == 0.0)


def test_replay_report_precision_none_when_nothing_gated() -> None:
    report = prompt_prediction_replay_report_from_dict(
        {
            "schema_version": 1,
            "cautious": {"coverage": 0.0, "precision": None},
            "cohorts": [],
            "sweep": [],
        }
    )
    assert report.cautious.precision is None
    assert report.cohorts == []

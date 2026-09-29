"""Tests for the typed prompt prediction Rust facade and wire mirror."""

from __future__ import annotations

import pytest

from sase.core.prompt_prediction_facade import (
    PROMPT_PREDICTION_SCHEMA_VERSION,
    PromptPredictionCorpus,
    PromptPredictionModel,
)
from sase.core.prompt_prediction_wire import (
    PROMPT_PREDICTION_WIRE_SCHEMA_VERSION,
    PromptPredictionCorpusOptions,
    PromptPredictionModelConfig,
    PromptPredictionRequest,
    PromptPredictionRow,
    PromptPrefixRankRequest,
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

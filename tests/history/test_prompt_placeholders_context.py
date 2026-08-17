"""Tests for placeholder context bags, token selection, and trimming."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_placeholders import (
    CONTEXT_STOPWORD_RATIO,
    CONTEXT_TOKENS_PER_PROMPT,
    _prompt_context_tokens,
    load_common_placeholders,
    record_prompt_placeholders,
)
from tests.history._prompt_placeholders_helpers import (
    freeze_timestamps,
    make_sase_home,
    read_store,
    set_limit,
)


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox ``~/.sase`` and default the placeholder limit to 100."""
    return make_sase_home(tmp_path, monkeypatch)


def test_recording_increments_context_once_per_prompt(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000", "260702_000000"])

    record_prompt_placeholders("<alpha> then <alpha> and <beta> write")
    first = read_store(sase_home_dir)
    assert first["version"] == 2
    assert first["prompt_count"] == 1
    by_text = {item["text"]: item for item in first["placeholders"]}
    assert by_text["alpha"]["count"] == 1
    assert by_text["alpha"]["context_uses"] == 1
    assert by_text["beta"]["count"] == 1
    assert "<beta>" in by_text["alpha"]["context"]
    assert by_text["alpha"]["context"]["<beta>"] == 1
    assert "<alpha>" not in by_text["alpha"]["context"]
    assert "<alpha>" in by_text["beta"]["context"]
    assert "<beta>" not in by_text["beta"]["context"]
    assert first["context_frequency"]["<alpha>"] == 1
    assert first["context_frequency"]["<beta>"] == 1

    record_prompt_placeholders("<alpha> then <alpha> and <beta> write")
    second = read_store(sase_home_dir)
    assert second["prompt_count"] == 2
    by_text = {item["text"]: item for item in second["placeholders"]}
    assert by_text["alpha"]["count"] == 2
    assert by_text["alpha"]["context_uses"] == 2
    assert by_text["alpha"]["context"]["<beta>"] == 2
    assert second["context_frequency"]["<alpha>"] == 2


def test_literal_zone_tag_is_context_but_not_a_saved_entry(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze_timestamps(monkeypatch, ["260701_000000"])

    record_prompt_placeholders("see `<alpha>` and <beta>")

    assert load_common_placeholders(10) == ["beta"]
    beta = read_store(sase_home_dir)["placeholders"][0]
    assert "<alpha>" in beta["context"]
    assert "<beta>" not in beta["context"]


def test_prompt_context_tokens_keep_tags_and_drop_stopwords() -> None:
    tokens = _prompt_context_tokens(
        "write the plan <phase title> rareword",
        context_frequency={
            "write": 10,
            "plan": 10,
            "rareword": 1,
            "<phase title>": 10,
        },
        prompt_count=10,
    )
    assert tokens[0] == "<phase title>"
    assert "write" not in tokens
    assert "plan" not in tokens
    assert "rareword" in tokens
    assert 10 / 10 > CONTEXT_STOPWORD_RATIO


def test_prompt_context_tokens_prefer_tags_when_the_prompt_is_capped() -> None:
    words = " ".join(f"word{index:02d}xx" for index in range(30))
    tokens = _prompt_context_tokens(
        f"<alpha> <beta> {words}",
        context_frequency={},
        prompt_count=0,
    )
    assert tokens[:2] == ("<alpha>", "<beta>")
    assert len(tokens) == CONTEXT_TOKENS_PER_PROMPT
    assert "<alpha>" in tokens
    assert "<beta>" in tokens


def test_prompt_context_tokens_are_deterministic() -> None:
    first = _prompt_context_tokens(
        "write the <phase title> plan",
        context_frequency={"write": 2, "phase": 1},
        prompt_count=4,
    )
    second = _prompt_context_tokens(
        "write the <phase title> plan",
        context_frequency={"write": 2, "phase": 1},
        prompt_count=4,
    )
    assert first == second


def test_entry_and_vocabulary_trims_are_deterministic(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(store, "CONTEXT_TOKENS_PER_ENTRY", 2)
    monkeypatch.setattr(store, "CONTEXT_VOCABULARY_LIMIT", 2)
    freeze_timestamps(monkeypatch, ["260701_000000"])
    monkeypatch.setattr(
        store,
        "_prompt_context_tokens",
        lambda _text, **_kwargs: ("<zebra>", "<mango>", "<apple>"),
    )

    with caplog.at_level(logging.DEBUG, logger=store.log.name):
        record_prompt_placeholders("<alpha>")

    saved = read_store(sase_home_dir)
    assert saved["placeholders"][0]["context"] == {"<apple>": 1, "<mango>": 1}
    assert saved["context_frequency"] == {"<apple>": 1, "<mango>": 1}
    assert "trimmed placeholder context bag" in caplog.text
    assert "trimmed placeholder context vocabulary" in caplog.text


def test_entry_trim_keeps_highest_count_then_smallest_token(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "CONTEXT_TOKENS_PER_ENTRY", 2)
    monkeypatch.setattr(store, "CONTEXT_VOCABULARY_LIMIT", 50)
    freeze_timestamps(monkeypatch, ["260701_000000"])
    tokens = iter(
        [
            ("<zebra>", "<apple>"),
            ("<zebra>", "<mango>"),
        ]
    )
    monkeypatch.setattr(
        store,
        "_prompt_context_tokens",
        lambda _text, **_kwargs: next(tokens),
    )

    record_prompt_placeholders("<alpha>")
    record_prompt_placeholders("<alpha>")

    assert read_store(sase_home_dir)["placeholders"][0]["context"] == {
        "<zebra>": 2,
        "<apple>": 1,
    }


def test_lru_eviction_drops_the_bag_and_keeps_corpus_statistics(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_limit(monkeypatch, 2)
    freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<stale> uniqueaaaa")
    freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<older>")
    freeze_timestamps(monkeypatch, ["260703_000000"])
    record_prompt_placeholders("<fresh>")

    data = read_store(sase_home_dir)
    assert [item["text"] for item in data["placeholders"]] == ["fresh", "older"]
    assert data["prompt_count"] == 3
    assert "uniqueaaaa" in data["context_frequency"]
    assert "<stale>" in data["context_frequency"]

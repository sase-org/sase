"""Tests for the prompt-history word corpus index."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.widgets.prompt_word_completion import (
    _word_ranges,
    is_word_character,
)
from sase.history.prompt_store import PromptEntry, save_shard
from sase.history.prompt_word_index import (
    _PROMPT_WORD_RE,
    _extract_prompt_words,
    _shard_token_cache,
    PromptWordIndex,
    build_prompt_word_index,
)
from tests.conftest import redirect_sase_home


@pytest.fixture(autouse=True)
def _isolate_prompt_word_index_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _shard_token_cache.clear()


def _entry(text: str, last_used: str) -> PromptEntry:
    return PromptEntry(text=text, timestamp=last_used, last_used=last_used)


def _write_shard(history_dir: Path, name: str, entries: list[PromptEntry]) -> Path:
    path = history_dir / name
    assert save_shard(path, entries)
    return path


def _spellings_for_prefix(index: PromptWordIndex, prefix: str) -> list[str]:
    return [
        index.spelling(index.folded_order[row])
        for row in index.word_ids_with_prefix(prefix)
    ]


def test_regex_tokenizer_matches_widget_word_character_semantics() -> None:
    for codepoint in range(0x110000):
        character = chr(codepoint)
        assert bool(_PROMPT_WORD_RE.fullmatch(character)) is is_word_character(
            character
        )

    text = "alpha beta-gamma snake_case naïveté - – em-dash 123"
    assert [match.span() for match in _PROMPT_WORD_RE.finditer(text)] == list(
        _word_ranges(text)
    )
    assert list(_extract_prompt_words(text, min_length=1)) == [
        "alpha",
        "beta-gamma",
        "snake_case",
        "naïveté",
        "em-dash",
    ]


def test_prompt_ids_are_newest_first_and_word_postings_are_ascending(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        _write_shard(
            history_dir,
            "2607.json",
            [
                _entry("older shared alpha", "260701_000000"),
                _entry("newest shared beta", "260702_000000"),
            ],
        )
        _write_shard(
            history_dir,
            "2606.json",
            [_entry("archive shared gamma", "260601_000000")],
        )

        index = build_prompt_word_index(
            min_length=1,
            shard_limit=None,
            prompt_limit=None,
        )

    assert [
        [index.spelling(word_id) for word_id in index.prompt_word_ids(prompt_id)]
        for prompt_id in range(index.prompt_count)
    ] == [
        ["newest", "shared", "beta"],
        ["older", "shared", "alpha"],
        ["archive", "shared", "gamma"],
    ]
    shared_id = index.words.index("shared")
    assert list(index.word_prompt_ids(shared_id)) == [0, 1, 2]


def test_document_frequency_counts_prompts_not_occurrences(tmp_path: Path) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        _write_shard(
            history_dir,
            "2607.json",
            [
                _entry("alpha alpha beta", "260702_000000"),
                _entry("alpha gamma", "260701_000000"),
            ],
        )

        index = build_prompt_word_index(
            min_length=1,
            shard_limit=None,
            prompt_limit=None,
        )

    alpha_id = index.words.index("alpha")
    assert index.document_frequency[alpha_id] == 2
    assert index.max_document_frequency == 2


def test_prefix_lookup_is_case_insensitive_and_uses_unicode_folding(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        _write_shard(
            history_dir,
            "2607.json",
            [
                _entry("Alpha alphabet Straße stratum", "260701_000000"),
            ],
        )

        index = build_prompt_word_index(
            min_length=1,
            shard_limit=None,
            prompt_limit=None,
        )

    assert _spellings_for_prefix(index, "ALP") == ["Alpha", "alphabet"]
    assert _spellings_for_prefix(index, "stras") == ["Straße"]
    assert index.word_ids_for_spelling("alpha") == (index.words.index("Alpha"),)
    assert list(index.word_ids_with_prefix("missing")) == []


def test_case_variants_collapse_to_one_canonical_word_id(tmp_path: Path) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        _write_shard(
            history_dir,
            "2607.json",
            [
                _entry("Also also ALSO", "260704_000000"),
                _entry("also beta", "260703_000000"),
                _entry("ALSO gamma", "260702_000000"),
                _entry("Also delta", "260701_000000"),
            ],
        )

        index = build_prompt_word_index(
            min_length=1,
            shard_limit=None,
            prompt_limit=None,
        )

    also_id = index.word_ids_for_spelling("ALSO")[0]
    assert index.spelling(also_id) == "Also"
    assert index.word_ids_for_spelling("also") == (also_id,)
    assert index.document_frequency[also_id] == 4
    assert list(index.word_prompt_ids(also_id)) == [0, 1, 2, 3]
    assert list(index.prompt_word_ids(0)).count(also_id) == 1


def test_per_shard_cache_reuses_and_invalidates_tokenization(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        shard = _write_shard(
            history_dir,
            "2607.json",
            [_entry("alpha beta gamma", "260701_000000")],
        )
        with patch(
            "sase.history.prompt_word_index._extract_prompt_words",
            wraps=_extract_prompt_words,
        ) as extract:
            first = build_prompt_word_index(
                min_length=1,
                shard_limit=None,
                prompt_limit=None,
            )
            second = build_prompt_word_index(
                min_length=1,
                shard_limit=None,
                prompt_limit=None,
            )
            assert first.words == second.words
            assert extract.call_count == 1

            _write_shard(
                history_dir,
                "2607.json",
                [_entry("delta epsilon", "260702_000000")],
            )
            os.utime(shard, ns=(shard.stat().st_atime_ns, shard.stat().st_mtime_ns + 1))
            third = build_prompt_word_index(
                min_length=1,
                shard_limit=None,
                prompt_limit=None,
            )

    assert third.words == ("delta", "epsilon")
    assert extract.call_count == 2


def test_shard_and_prompt_limits_truncate_deterministically(tmp_path: Path) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        _write_shard(
            history_dir,
            "2607.json",
            [
                _entry("newest alpha", "260702_000000"),
                _entry("middle beta", "260701_000000"),
            ],
        )
        _write_shard(
            history_dir,
            "2606.json",
            [_entry("archive gamma", "260601_000000")],
        )

        shard_limited = build_prompt_word_index(
            min_length=1,
            shard_limit=1,
            prompt_limit=None,
        )
        prompt_limited = build_prompt_word_index(
            min_length=1,
            shard_limit=None,
            prompt_limit=1,
        )

    assert shard_limited.words == ("newest", "alpha", "middle", "beta")
    assert prompt_limited.words == ("newest", "alpha")


def test_empty_corrupt_and_missing_shards_yield_empty_index(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not json", encoding="utf-8")
    empty = tmp_path / "empty.json"
    assert save_shard(empty, [])

    index = build_prompt_word_index(
        min_length=1,
        shard_limit=None,
        prompt_limit=None,
        shard_paths=[corrupt, empty, tmp_path / "missing.json"],
        load_shard_func=lambda path: [] if path.name != "corrupt.json" else [],
    )

    assert index.words == ()
    assert index.prompt_count == 0

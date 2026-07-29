"""Tests for recent word derivation from prompt history."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.prompt_store import PromptEntry, save_shard
from sase.history.prompt_word_deletions import delete_prompt_word
from sase.history.prompt_words import (
    _extract_prompt_words,
    collect_recent_prompt_words,
    history_words_source_token,
)
from tests.conftest import redirect_sase_home


@pytest.fixture(autouse=True)
def _redirect_deleted_word_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")


def _entry(
    text: str,
    last_used: str,
    *,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp=last_used,
        last_used=last_used,
        cancelled=cancelled,
    )


def test_extract_prompt_words_uses_shared_unicode_word_semantics() -> None:
    assert list(
        _extract_prompt_words(
            "tiny naïveté snake_case 123456 alpha-omega",
            min_length=5,
        )
    ) == ["naïveté", "snake_case", "alpha", "omega"]
    assert list(_extract_prompt_words("a bb 123", min_length=0)) == ["a", "bb"]


def test_collect_recent_words_preserves_mru_and_exact_spellings(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        save_shard(
            history_dir / "2607.json",
            [
                _entry("older Alpha shared", "260701_000000"),
                _entry(
                    "newest alpha shared cancelled_word",
                    "260702_000000",
                    cancelled=True,
                ),
            ],
        )
        save_shard(
            history_dir / "2606.json",
            [_entry("archive Alpha trailing", "260601_000000")],
        )

        words = collect_recent_prompt_words(max_words=20, min_length=5)

    assert words == [
        "newest",
        "alpha",
        "shared",
        "cancelled_word",
        "older",
        "Alpha",
        "archive",
        "trailing",
    ]


def test_collect_recent_words_stops_before_loading_older_shards() -> None:
    newer = Path("2607.json")
    older = Path("2606.json")
    with (
        patch(
            "sase.history.prompt_words.iter_shard_paths_newest_first",
            return_value=iter([newer, older]),
        ),
        patch(
            "sase.history.prompt_words.load_shard",
            side_effect=lambda path: (
                [_entry("first_word second_word third_word", "260701_000000")]
                if path == newer
                else (_ for _ in ()).throw(AssertionError("loaded older shard"))
            ),
        ),
    ):
        assert collect_recent_prompt_words(max_words=2, min_length=1) == [
            "first_word",
            "second_word",
        ]


def test_collect_recent_words_tolerates_corrupt_shards(tmp_path: Path) -> None:
    history_dir = tmp_path / "prompt_history"
    history_dir.mkdir()
    (history_dir / "2607.json").write_text("not json", encoding="utf-8")
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        save_shard(
            history_dir / "2606.json",
            [_entry("usable history words", "260601_000000")],
        )
        assert collect_recent_prompt_words(max_words=10, min_length=5) == [
            "usable",
            "history",
            "words",
        ]


def test_deleted_words_are_excluded_without_consuming_the_budget(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        save_shard(
            history_dir / "2607.json",
            [_entry("alpha beta gamma", "260701_000000")],
        )
        delete_prompt_word("alpha")

        assert collect_recent_prompt_words(max_words=2, min_length=1) == [
            "beta",
            "gamma",
        ]


def test_history_words_source_token_tracks_shards_and_settings(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        before = history_words_source_token(max_words=1000, min_length=5)
        save_shard(
            history_dir / "2607.json",
            [_entry("recorded prompt history words", "260701_000000")],
        )
        after_write = history_words_source_token(max_words=1000, min_length=5)
        after_count = history_words_source_token(max_words=10, min_length=5)
        after_length = history_words_source_token(max_words=1000, min_length=7)

    assert after_write != before
    assert after_count != after_write
    assert after_length != after_write


def test_history_words_source_token_tracks_deleted_words(tmp_path: Path) -> None:
    history_dir = tmp_path / "prompt_history"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_DIR", history_dir):
        before = history_words_source_token(max_words=1000, min_length=5)
        delete_prompt_word("alpha")
        after = history_words_source_token(max_words=1000, min_length=5)

    assert after != before

"""Tests for the app-level prompt-history word cache loader."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions._startup_history_words import _load_history_prompt_words


def test_history_word_loader_rebuilds_when_source_token_changes() -> None:
    token = (1000, 5, (("2607.json", 10, 20),))
    with (
        patch(
            "sase.history.prompt_words.history_words_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_words.collect_recent_prompt_words",
            return_value=["recent", "words"],
        ) as collect,
    ):
        result = _load_history_prompt_words(
            max_words=1000,
            min_length=5,
            previous_token=None,
        )

    assert result.source_token == token
    assert result.words == ["recent", "words"]
    collect.assert_called_once_with(max_words=1000, min_length=5)


def test_history_word_loader_skips_collection_for_unchanged_token() -> None:
    token = (1000, 5, (("2607.json", 10, 20),))
    with (
        patch(
            "sase.history.prompt_words.history_words_source_token",
            return_value=token,
        ),
        patch(
            "sase.history.prompt_words.collect_recent_prompt_words",
        ) as collect,
    ):
        result = _load_history_prompt_words(
            max_words=1000,
            min_length=5,
            previous_token=token,
        )

    assert result.source_token == token
    assert result.words is None
    collect.assert_not_called()

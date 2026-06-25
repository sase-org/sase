"""Tests for exact-match prompt history rewrites."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.history.prompt_store import (
    PromptEntry,
    load_prompt_history,
    rewrite_prompt_text_exact,
    save_prompt_history,
)


def _entry(text: str, timestamp: str) -> PromptEntry:
    return PromptEntry(text=text, timestamp=timestamp, last_used=timestamp)


def test_rewrite_prompt_text_exact_updates_only_exact_rows(tmp_path: Path) -> None:
    history_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        save_prompt_history(
            [
                _entry("%name:old\nDo work", "260601_000000"),
                _entry("%name:old\nDo different work", "260601_000001"),
            ]
        )

        changed = rewrite_prompt_text_exact("%name:old\nDo work", "%name:new\nDo work")

        assert changed == 1
        assert {entry.text for entry in load_prompt_history()} == {
            "%name:new\nDo work",
            "%name:old\nDo different work",
        }


def test_rewrite_prompt_text_exact_updates_multi_prompt_segments(
    tmp_path: Path,
) -> None:
    history_file = tmp_path / "prompt_history.json"
    old = "%name:old\nBuild\n---\nReview"
    new = "%name:new\nBuild\n---\nReview"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        save_prompt_history(
            [
                _entry(old, "260601_000000"),
                _entry("%name:old\nBuild", "260601_000001"),
                _entry("Review", "260601_000002"),
            ]
        )

        changed = rewrite_prompt_text_exact(old, new)

        assert changed == 2
        assert {entry.text for entry in load_prompt_history()} == {
            new,
            "%name:new\nBuild",
            "Review",
        }

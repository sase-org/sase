"""Tests for prompt history filtering and invalid entries."""

from pathlib import Path
from unittest.mock import patch

from sase.history.prompt_store import (
    PromptEntry,
    add_or_update_prompt,
    is_recordable_prompt,
    load_prompt_history,
    save_prompt_history,
)


def test_is_recordable_prompt_matches_word_threshold() -> None:
    assert is_recordable_prompt("fix bug") is False
    assert is_recordable_prompt("   fix   bug   ") is False
    assert is_recordable_prompt("fix the bug") is False
    assert is_recordable_prompt("fix the auth bug") is False
    assert is_recordable_prompt("fix the auth bug today") is True
    assert is_recordable_prompt("") is False
    assert is_recordable_prompt("   \n\t  ") is False
    assert is_recordable_prompt("#gh:sase") is False


def test_is_recordable_prompt_allows_short_override() -> None:
    assert is_recordable_prompt("#gh:sase", allow_short=True) is True
    assert is_recordable_prompt("", allow_short=True) is True


def test_single_word_prompt_not_written(tmp_path: Path) -> None:
    """Test that a single-word prompt (e.g. bare xprompt trigger) is dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("#gh:sase")
        assert load_prompt_history() == []


def test_whitespace_only_prompt_not_written(tmp_path: Path) -> None:
    """Test that whitespace-only prompts are dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("   \n\t  ")
        assert load_prompt_history() == []


def test_two_word_prompt_not_written(tmp_path: Path) -> None:
    """Test that a 2-word prompt is dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("fix bug")
        assert load_prompt_history() == []


def test_four_word_prompt_not_written(tmp_path: Path) -> None:
    """Test that a 4-word prompt is dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("fix the auth bug")
        assert load_prompt_history() == []


def test_five_word_prompt_is_written(tmp_path: Path) -> None:
    """Test that a 5-word prompt is written normally (boundary case)."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("fix the auth bug today")
        result = load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "fix the auth bug today"


def test_single_word_cancelled_prompt_not_written(tmp_path: Path) -> None:
    """Test that a cancelled single-word prompt is also dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("#gh:sase", cancelled=True)
        assert load_prompt_history() == []


def test_existing_single_word_entry_not_updated(tmp_path: Path) -> None:
    """Test that an existing single-word entry does not get its last_used bumped."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        entry = PromptEntry(
            text="#gh:sase",
            timestamp="251231_100000",
            last_used="251231_100000",
        )
        save_prompt_history([entry])

        with patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_200000"
        ):
            add_or_update_prompt("#gh:sase")

        result = load_prompt_history()
        assert len(result) == 1
        assert result[0].last_used == "251231_100000"


def test_loads_entries_missing_legacy_context_fields(tmp_path: Path) -> None:
    """Test that old context fields are no longer required to load entries."""
    test_file = tmp_path / "prompt_history.json"
    test_file.write_text(
        '{"prompts": [{"text": "missing legacy context", '
        '"timestamp": "251231_143052", "last_used": "251231_143052"}, '
        '{"text": "missing_required_fields"}]}'
    )
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        result = load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "missing legacy context"
        assert result[0].branch_or_workspace == ""
        assert result[0].workspace == ""

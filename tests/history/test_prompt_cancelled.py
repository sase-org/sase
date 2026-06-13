"""Tests for cancelled prompt history entries."""

from pathlib import Path
from unittest.mock import patch

from sase.history.prompt import (
    PromptEntry,
    _load_prompt_history,
    _save_prompt_history,
    add_or_update_prompt,
    get_prompts_for_fzf,
    record_failed_launch_prompt,
)


def test_add_cancelled_prompt(tmp_path: Path) -> None:
    """Test adding a cancelled prompt to history."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("draft prompt", cancelled=True)
        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "draft prompt"
        assert result[0].cancelled is True


def test_cancelled_prompt_not_downgraded(tmp_path: Path) -> None:
    """Test that a non-cancelled prompt is not downgraded to cancelled."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        entry = PromptEntry(
            text="test prompt",
            timestamp="251231_100000",
            last_used="251231_100000",
            cancelled=False,
        )
        _save_prompt_history([entry])

        with patch(
            "sase.history.prompt.generate_timestamp", return_value="251231_200000"
        ):
            add_or_update_prompt("test prompt", cancelled=True)

        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].cancelled is False
        assert result[0].last_used == "251231_200000"


def test_failed_launch_prompt_forces_cancelled_downgrade(tmp_path: Path) -> None:
    """Failed launches force-cancel an earlier optimistic successful write."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        entry = PromptEntry(
            text="test prompt",
            timestamp="251231_100000",
            last_used="251231_100000",
            cancelled=False,
        )
        _save_prompt_history([entry])

        with patch(
            "sase.history.prompt.generate_timestamp", return_value="251231_200000"
        ):
            record_failed_launch_prompt("test prompt")

        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].cancelled is True
        assert result[0].last_used == "251231_200000"


def test_failed_launch_prompt_records_short_vcs_tag(tmp_path: Path) -> None:
    """Failed TUI launches record short prompt tokens such as ``#gh:foo``."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        record_failed_launch_prompt("#gh:foobar")

        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "#gh:foobar"
        assert result[0].cancelled is True


def test_cancelled_prompt_upgraded_on_launch(tmp_path: Path) -> None:
    """Test that a cancelled prompt is upgraded to non-cancelled when launched."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        entry = PromptEntry(
            text="draft prompt",
            timestamp="251231_100000",
            last_used="251231_100000",
            cancelled=True,
        )
        _save_prompt_history([entry])

        with patch(
            "sase.history.prompt.generate_timestamp", return_value="251231_200000"
        ):
            add_or_update_prompt("draft prompt")

        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].cancelled is False


def test_get_prompts_for_fzf_excludes_cancelled_by_default(tmp_path: Path) -> None:
    """Test that cancelled prompts are excluded from fzf results by default."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        entries = [
            PromptEntry(
                text="regular prompt",
                timestamp="251231_143052",
                last_used="251231_143052",
            ),
            PromptEntry(
                text="cancelled prompt",
                timestamp="251231_143053",
                last_used="251231_143053",
                cancelled=True,
            ),
        ]
        _save_prompt_history(entries)

        result = get_prompts_for_fzf()
        assert len(result) == 1
        assert result[0][1].text == "regular prompt"


def test_get_prompts_for_fzf_includes_cancelled_when_requested(
    tmp_path: Path,
) -> None:
    """Test that cancelled prompts are included when include_cancelled=True."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        entries = [
            PromptEntry(
                text="regular prompt",
                timestamp="251231_143052",
                last_used="251231_143052",
            ),
            PromptEntry(
                text="cancelled prompt",
                timestamp="251231_143053",
                last_used="251231_143053",
                cancelled=True,
            ),
        ]
        _save_prompt_history(entries)

        result = get_prompts_for_fzf(include_cancelled=True)
        assert len(result) == 2
        texts = {entry.text for _, entry in result}
        assert "regular prompt" in texts
        assert "cancelled prompt" in texts


def test_cancelled_field_backward_compat(tmp_path: Path) -> None:
    """Test that JSON entries without cancelled field default to False."""
    test_file = tmp_path / "prompt_history.json"
    test_file.write_text(
        '{"prompts": [{"text": "old prompt", "branch_or_workspace": "main", '
        '"timestamp": "251231_143052", "last_used": "251231_143052", '
        '"workspace": "myproject"}]}'
    )
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].cancelled is False

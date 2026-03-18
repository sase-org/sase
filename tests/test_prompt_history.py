"""Tests for prompt history functionality."""

from pathlib import Path
from unittest.mock import patch

from sase.prompt_history import (
    PromptEntry,
    _format_prompt_for_display,
    _load_prompt_history,
    _save_prompt_history,
    add_or_update_prompt,
    get_prompts_for_fzf,
)


def test_add_new_prompt(tmp_path: Path) -> None:
    """Test adding a new prompt to history."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.prompt_history._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.prompt_history._get_workspace_name", return_value="myproject"),
        patch("sase.prompt_history.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("test prompt")
        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "test prompt"
        assert result[0].branch_or_workspace == "main"
        assert result[0].timestamp == "251231_143052"
        assert result[0].last_used == "251231_143052"
        assert result[0].workspace == "myproject"


def test_add_duplicate_updates_timestamp(tmp_path: Path) -> None:
    """Test that adding a duplicate prompt updates its last_used timestamp."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        # Add initial prompt
        initial_entry = PromptEntry(
            text="test prompt",
            branch_or_workspace="main",
            timestamp="251231_100000",
            last_used="251231_100000",
            workspace="test_workspace",
        )
        _save_prompt_history([initial_entry])

        # Add the same prompt again
        with (
            patch(
                "sase.prompt_history._get_current_branch_or_workspace",
                return_value="main",
            ),
            patch("sase.prompt_history._get_workspace_name", return_value="myproject"),
            patch(
                "sase.prompt_history.generate_timestamp", return_value="251231_200000"
            ),
        ):
            add_or_update_prompt("test prompt")

        result = _load_prompt_history()
        # Should still be only 1 prompt (deduplicated)
        assert len(result) == 1
        assert result[0].text == "test prompt"
        # Original timestamp should be preserved
        assert result[0].timestamp == "251231_100000"
        # last_used should be updated
        assert result[0].last_used == "251231_200000"


def test_format_prompt_truncates_long_prompts() -> None:
    """Test that long prompts are truncated with ellipsis."""
    entry = PromptEntry(
        text="a" * 100,
        branch_or_workspace="main",
        timestamp="251231_143052",
        last_used="251231_143052",
        workspace="myproject",
    )
    result = _format_prompt_for_display(entry, "main", "myproject", 10)
    assert "..." in result
    # Should not contain the full prompt
    assert "a" * 100 not in result


def test_get_prompts_for_fzf_empty(tmp_path: Path) -> None:
    """Test get_prompts_for_fzf returns empty list when no history."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        result = get_prompts_for_fzf("main", "myproject")
        assert result == []


def test_get_prompts_for_fzf_sorts_workspace_second(tmp_path: Path) -> None:
    """Test that prompts from same workspace but different branch are sorted second."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        entries = [
            PromptEntry(
                text="other workspace prompt",
                branch_or_workspace="feature",
                timestamp="251231_143052",
                last_used="251231_300000",  # Most recent
                workspace="otherproject",
            ),
            PromptEntry(
                text="same workspace prompt",
                branch_or_workspace="feature2",
                timestamp="251231_143052",
                last_used="251231_200000",  # Middle
                workspace="myproject",
            ),
            PromptEntry(
                text="current branch prompt",
                branch_or_workspace="main",
                timestamp="251231_143052",
                last_used="251231_100000",  # Least recent
                workspace="myproject",
            ),
        ]
        _save_prompt_history(entries)

        result = get_prompts_for_fzf("main", "myproject")
        assert len(result) == 3
        # Current branch first, then same workspace, then other
        assert result[0][1].text == "current branch prompt"
        assert result[1][1].text == "same workspace prompt"
        assert result[2][1].text == "other workspace prompt"


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "prompt_history.json"
    test_file.write_text("not valid json {")
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        result = _load_prompt_history()
        assert result == []


def test_add_cancelled_prompt(tmp_path: Path) -> None:
    """Test adding a cancelled prompt to history."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.prompt_history._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.prompt_history._get_workspace_name", return_value="myproject"),
        patch("sase.prompt_history.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("draft prompt", cancelled=True)
        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "draft prompt"
        assert result[0].cancelled is True


def test_cancelled_prompt_not_downgraded(tmp_path: Path) -> None:
    """Test that a non-cancelled prompt is not downgraded to cancelled."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        # Add a non-cancelled prompt
        entry = PromptEntry(
            text="test prompt",
            branch_or_workspace="main",
            timestamp="251231_100000",
            last_used="251231_100000",
            workspace="myproject",
            cancelled=False,
        )
        _save_prompt_history([entry])

        # Try to add the same prompt as cancelled
        with (
            patch(
                "sase.prompt_history._get_current_branch_or_workspace",
                return_value="main",
            ),
            patch("sase.prompt_history._get_workspace_name", return_value="myproject"),
            patch(
                "sase.prompt_history.generate_timestamp", return_value="251231_200000"
            ),
        ):
            add_or_update_prompt("test prompt", cancelled=True)

        result = _load_prompt_history()
        assert len(result) == 1
        # Should remain non-cancelled
        assert result[0].cancelled is False
        # last_used should still be updated
        assert result[0].last_used == "251231_200000"


def test_cancelled_prompt_upgraded_on_launch(tmp_path: Path) -> None:
    """Test that a cancelled prompt is upgraded to non-cancelled when launched."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        # Add a cancelled prompt
        entry = PromptEntry(
            text="draft prompt",
            branch_or_workspace="main",
            timestamp="251231_100000",
            last_used="251231_100000",
            workspace="myproject",
            cancelled=True,
        )
        _save_prompt_history([entry])

        # Add the same prompt as non-cancelled (simulating a launch)
        with (
            patch(
                "sase.prompt_history._get_current_branch_or_workspace",
                return_value="main",
            ),
            patch("sase.prompt_history._get_workspace_name", return_value="myproject"),
            patch(
                "sase.prompt_history.generate_timestamp", return_value="251231_200000"
            ),
        ):
            add_or_update_prompt("draft prompt")

        result = _load_prompt_history()
        assert len(result) == 1
        # Should be upgraded to non-cancelled
        assert result[0].cancelled is False


def test_get_prompts_for_fzf_excludes_cancelled_by_default(tmp_path: Path) -> None:
    """Test that cancelled prompts are excluded from fzf results by default."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        entries = [
            PromptEntry(
                text="regular prompt",
                branch_or_workspace="main",
                timestamp="251231_143052",
                last_used="251231_143052",
                workspace="myproject",
            ),
            PromptEntry(
                text="cancelled prompt",
                branch_or_workspace="main",
                timestamp="251231_143053",
                last_used="251231_143053",
                workspace="myproject",
                cancelled=True,
            ),
        ]
        _save_prompt_history(entries)

        result = get_prompts_for_fzf("main", "myproject")
        assert len(result) == 1
        assert result[0][1].text == "regular prompt"


def test_get_prompts_for_fzf_includes_cancelled_when_requested(
    tmp_path: Path,
) -> None:
    """Test that cancelled prompts are included when include_cancelled=True."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        entries = [
            PromptEntry(
                text="regular prompt",
                branch_or_workspace="main",
                timestamp="251231_143052",
                last_used="251231_143052",
                workspace="myproject",
            ),
            PromptEntry(
                text="cancelled prompt",
                branch_or_workspace="main",
                timestamp="251231_143053",
                last_used="251231_143053",
                workspace="myproject",
                cancelled=True,
            ),
        ]
        _save_prompt_history(entries)

        result = get_prompts_for_fzf("main", "myproject", include_cancelled=True)
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
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].cancelled is False


def test_handles_missing_fields_in_json(tmp_path: Path) -> None:
    """Test that JSON entries with missing fields are filtered out."""
    test_file = tmp_path / "prompt_history.json"
    # Both entries are missing workspace field, so both should be filtered out
    test_file.write_text(
        '{"prompts": [{"text": "missing_workspace", "branch_or_workspace": "main", '
        '"timestamp": "251231_143052", "last_used": "251231_143052"}, '
        '{"text": "missing_fields"}]}'
    )
    with patch("sase.prompt_history._PROMPT_HISTORY_FILE", test_file):
        result = _load_prompt_history()
        # Both entries are missing required workspace field
        assert len(result) == 0

"""Tests for cancelled prompt history entries."""

from pathlib import Path
from unittest.mock import patch

from sase.history.prompt import (
    PromptEntry,
    _load_prompt_history,
    _save_prompt_history,
    add_or_update_prompt,
    get_prompts_for_fzf,
)


def test_add_cancelled_prompt(tmp_path: Path) -> None:
    """Test adding a cancelled prompt to history."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
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
                "sase.history.prompt._get_current_branch_or_workspace",
                return_value="main",
            ),
            patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
            patch(
                "sase.history.prompt.generate_timestamp", return_value="251231_200000"
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
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
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
                "sase.history.prompt._get_current_branch_or_workspace",
                return_value="main",
            ),
            patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
            patch(
                "sase.history.prompt.generate_timestamp", return_value="251231_200000"
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
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
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
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
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
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].cancelled is False

"""Core prompt history tests."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sase.history.prompt import (
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
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
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
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
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
                "sase.history.prompt._get_current_branch_or_workspace",
                return_value="main",
            ),
            patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
            patch(
                "sase.history.prompt.generate_timestamp", return_value="251231_200000"
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


def test_save_prompt_history_uses_atomic_replace(tmp_path: Path) -> None:
    """Test that saving writes a temp file and atomically replaces the store."""
    test_file = tmp_path / "prompt_history.json"
    entry = PromptEntry(
        text="test prompt",
        branch_or_workspace="main",
        timestamp="251231_100000",
        last_used="251231_100000",
        workspace="myproject",
    )
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = os.replace

    def tracking_replace(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        replace_calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch("sase.history.prompt.os.replace", side_effect=tracking_replace),
    ):
        assert _save_prompt_history([entry]) is True

    assert len(replace_calls) == 1
    temp_path, final_path = replace_calls[0]
    assert temp_path.parent == tmp_path
    assert temp_path.name.startswith(".prompt_history.json.")
    assert final_path == test_file
    assert not temp_path.exists()
    assert json.loads(test_file.read_text(encoding="utf-8"))["prompts"][0]["text"] == (
        "test prompt"
    )


def test_save_prompt_history_keeps_existing_file_when_replace_fails(
    tmp_path: Path,
) -> None:
    """Test that a failed atomic replace leaves the existing history intact."""
    test_file = tmp_path / "prompt_history.json"
    initial_entry = PromptEntry(
        text="initial prompt",
        branch_or_workspace="main",
        timestamp="251231_100000",
        last_used="251231_100000",
        workspace="myproject",
    )
    new_entry = PromptEntry(
        text="new prompt",
        branch_or_workspace="main",
        timestamp="251231_200000",
        last_used="251231_200000",
        workspace="myproject",
    )

    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        assert _save_prompt_history([initial_entry]) is True
        with patch("sase.history.prompt.os.replace", side_effect=OSError):
            assert _save_prompt_history([new_entry]) is False

        result = _load_prompt_history()
        assert [entry.text for entry in result] == ["initial prompt"]
        assert list(tmp_path.glob(".prompt_history.json.*.tmp")) == []


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
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        result = get_prompts_for_fzf("main", "myproject")
        assert result == []


def test_get_prompts_for_fzf_sorts_workspace_second(tmp_path: Path) -> None:
    """Test that prompts from same workspace but different branch are sorted second."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
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
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        result = _load_prompt_history()
        assert result == []


def test_add_prompt_does_not_overwrite_after_transient_decode_failure(
    tmp_path: Path,
) -> None:
    """Test that writer load failures do not turn history into a new tiny file."""
    test_file = tmp_path / "prompt_history.json"
    initial_entry = PromptEntry(
        text="initial prompt",
        branch_or_workspace="main",
        timestamp="251231_100000",
        last_used="251231_100000",
        workspace="myproject",
    )

    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        assert _save_prompt_history([initial_entry]) is True

        with (
            patch(
                "sase.history.prompt._get_current_branch_or_workspace",
                return_value="main",
            ),
            patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
            patch(
                "sase.history.prompt.generate_timestamp",
                return_value="251231_200000",
            ),
            patch(
                "sase.history.prompt.json.load",
                side_effect=json.JSONDecodeError("transient", "", 0),
            ),
        ):
            add_or_update_prompt("new prompt")

        result = _load_prompt_history()
        assert [entry.text for entry in result] == ["initial prompt"]


def test_concurrent_prompt_writers_preserve_all_entries(tmp_path: Path) -> None:
    """Test that concurrent writers serialize read/modify/write cycles."""
    test_file = tmp_path / "prompt_history.json"
    prompts = [f"prompt number {i}" for i in range(12)]

    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace",
            return_value="main",
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(add_or_update_prompt, prompts))

        result = _load_prompt_history()
        assert {entry.text for entry in result} == set(prompts)

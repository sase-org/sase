"""Core prompt history tests."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sase.history.prompt_catalog import get_prompts_for_fzf
from sase.history.prompt_store import (
    PromptEntry,
    add_or_update_prompt,
    format_prompt_for_display,
    load_prompt_history,
    save_prompt_history,
)


def test_add_new_prompt(tmp_path: Path) -> None:
    """Test adding a new prompt to history."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("test prompt")
        result = load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "test prompt"
        assert result[0].timestamp == "251231_143052"
        assert result[0].last_used == "251231_143052"
        assert result[0].branch_or_workspace == ""
        assert result[0].workspace == ""

    saved = json.loads(test_file.read_text(encoding="utf-8"))["prompts"][0]
    assert set(saved) == {"text", "timestamp", "last_used", "cancelled"}


def test_add_duplicate_updates_timestamp(tmp_path: Path) -> None:
    """Test that adding a duplicate prompt updates its last_used timestamp."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        initial_entry = PromptEntry(
            text="test prompt",
            timestamp="251231_100000",
            last_used="251231_100000",
        )
        save_prompt_history([initial_entry])

        with patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_200000"
        ):
            add_or_update_prompt("test prompt")

        result = load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "test prompt"
        assert result[0].timestamp == "251231_100000"
        assert result[0].last_used == "251231_200000"


def test_save_prompt_history_uses_atomic_replace(tmp_path: Path) -> None:
    """Test that saving writes a temp file and atomically replaces the store."""
    test_file = tmp_path / "prompt_history.json"
    entry = PromptEntry(
        text="test prompt",
        timestamp="251231_100000",
        last_used="251231_100000",
    )
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = os.replace

    def tracking_replace(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        replace_calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch("sase.history.prompt_store.os.replace", side_effect=tracking_replace),
    ):
        assert save_prompt_history([entry]) is True

    assert len(replace_calls) == 1
    temp_path, final_path = replace_calls[0]
    assert temp_path.parent == tmp_path
    assert temp_path.name.startswith(".prompt_history.json.")
    assert final_path == test_file
    assert not temp_path.exists()
    saved = json.loads(test_file.read_text(encoding="utf-8"))["prompts"][0]
    assert saved == {
        "text": "test prompt",
        "timestamp": "251231_100000",
        "last_used": "251231_100000",
        "cancelled": False,
    }


def test_save_prompt_history_keeps_existing_file_when_replace_fails(
    tmp_path: Path,
) -> None:
    """Test that a failed atomic replace leaves the existing history intact."""
    test_file = tmp_path / "prompt_history.json"
    initial_entry = PromptEntry(
        text="initial prompt",
        timestamp="251231_100000",
        last_used="251231_100000",
    )
    new_entry = PromptEntry(
        text="new prompt",
        timestamp="251231_200000",
        last_used="251231_200000",
    )

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        assert save_prompt_history([initial_entry]) is True
        with patch("sase.history.prompt_store.os.replace", side_effect=OSError):
            assert save_prompt_history([new_entry]) is False

        result = load_prompt_history()
        assert [entry.text for entry in result] == ["initial prompt"]
        assert list(tmp_path.glob(".prompt_history.json.*.tmp")) == []


def test_format_prompt_truncates_long_prompts() -> None:
    """Test that long prompts are truncated with ellipsis."""
    entry = PromptEntry(
        text="a" * 100,
        timestamp="251231_143052",
        last_used="251231_143052",
    )
    result = format_prompt_for_display(entry)
    assert "..." in result
    assert "a" * 100 not in result


def test_get_prompts_for_fzf_empty(tmp_path: Path) -> None:
    """Test get_prompts_for_fzf returns empty list when no history."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        result = get_prompts_for_fzf()
        assert result == []


def test_get_prompts_for_fzf_sorts_by_last_used_desc(tmp_path: Path) -> None:
    """Test that prompts are sorted by recency only."""
    test_file = tmp_path / "prompt_history.json"
    test_file.write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "text": "old current branch prompt",
                        "branch_or_workspace": "main",
                        "timestamp": "251231_143052",
                        "last_used": "251231_100000",
                        "workspace": "myproject",
                    },
                    {
                        "text": "middle workspace prompt",
                        "branch_or_workspace": "feature",
                        "timestamp": "251231_143052",
                        "last_used": "251231_200000",
                        "workspace": "myproject",
                    },
                    {
                        "text": "new other workspace prompt",
                        "branch_or_workspace": "other",
                        "timestamp": "251231_143052",
                        "last_used": "251231_300000",
                        "workspace": "otherproject",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        result = get_prompts_for_fzf()

    assert [entry.text for _, entry in result] == [
        "new other workspace prompt",
        "middle workspace prompt",
        "old current branch prompt",
    ]


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "prompt_history.json"
    test_file.write_text("not valid json {")
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        result = load_prompt_history()
        assert result == []


def test_add_prompt_does_not_overwrite_after_transient_decode_failure(
    tmp_path: Path,
) -> None:
    """Test that writer load failures do not turn history into a new tiny file."""
    test_file = tmp_path / "prompt_history.json"
    initial_entry = PromptEntry(
        text="initial prompt",
        timestamp="251231_100000",
        last_used="251231_100000",
    )

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        assert save_prompt_history([initial_entry]) is True

        with (
            patch(
                "sase.history.prompt_store.generate_timestamp",
                return_value="251231_200000",
            ),
            patch(
                "sase.history.prompt_store.json.load",
                side_effect=json.JSONDecodeError("transient", "", 0),
            ),
        ):
            add_or_update_prompt("new prompt")

        result = load_prompt_history()
        assert [entry.text for entry in result] == ["initial prompt"]


def test_concurrent_prompt_writers_preserve_all_entries(tmp_path: Path) -> None:
    """Test that concurrent writers serialize read/modify/write cycles."""
    test_file = tmp_path / "prompt_history.json"
    prompts = [f"prompt number {i}" for i in range(12)]

    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(add_or_update_prompt, prompts))

        result = load_prompt_history()
        assert {entry.text for entry in result} == set(prompts)

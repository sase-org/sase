"""Tests for prompt history functionality."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import sase.history.prompt as prompt_history
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


def test_multi_prompt_saves_combined_and_segments(tmp_path: Path) -> None:
    """Test that a multi-agent prompt saves both the combined and individual segments."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt(
            "Fix the auth bug\n---\n%wait Review the fix and add tests"
        )
        result = _load_prompt_history()
        texts = {e.text for e in result}
        assert len(result) == 3
        assert "Fix the auth bug\n---\n%wait Review the fix and add tests" in texts
        assert "Fix the auth bug" in texts
        assert "%wait Review the fix and add tests" in texts


def test_multi_prompt_saves_combined_and_segments_in_one_mutation(
    tmp_path: Path,
) -> None:
    """Test that multi-prompt history does not load/save once per segment."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace",
            return_value="main",
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
        patch(
            "sase.history.prompt._load_prompt_history_for_write",
            wraps=prompt_history._load_prompt_history_for_write,
        ) as load_for_write,
        patch(
            "sase.history.prompt._save_prompt_history",
            wraps=prompt_history._save_prompt_history,
        ) as save_history,
    ):
        add_or_update_prompt("Fix the auth bug\n---\nAdd tests")

        assert load_for_write.call_count == 1
        assert save_history.call_count == 1
        assert {entry.text for entry in _load_prompt_history()} == {
            "Fix the auth bug\n---\nAdd tests",
            "Fix the auth bug",
            "Add tests",
        }


def test_multi_prompt_segment_dedup(tmp_path: Path) -> None:
    """Test that a segment already in history just gets last_used bumped."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        # Pre-existing segment from standalone use
        entry = PromptEntry(
            text="Fix the auth bug",
            branch_or_workspace="main",
            timestamp="251231_100000",
            last_used="251231_100000",
            workspace="myproject",
        )
        _save_prompt_history([entry])

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
            add_or_update_prompt("Fix the auth bug\n---\nAdd tests")

        result = _load_prompt_history()
        # 3 entries: pre-existing segment (deduped), combined, and second segment
        assert len(result) == 3
        # The pre-existing segment should have bumped last_used
        segment_entry = next(e for e in result if e.text == "Fix the auth bug")
        assert segment_entry.timestamp == "251231_100000"
        assert segment_entry.last_used == "251231_200000"


def test_cancelled_multi_prompt_saves_cancelled_segments(tmp_path: Path) -> None:
    """Test that a cancelled multi-agent prompt saves each segment as cancelled."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("Draft fix\n---\nDraft tests", cancelled=True)
        result = _load_prompt_history()
        assert len(result) == 3
        for entry in result:
            assert entry.cancelled is True


def test_single_segment_with_frontmatter_does_not_split(tmp_path: Path) -> None:
    """Test that a single-segment prompt with frontmatter does NOT split."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        prompt = (
            "---\nxprompts:\n  _style:\n    - prompt_part: Be concise\n---\nFix the bug"
        )
        add_or_update_prompt(prompt)
        result = _load_prompt_history()
        # Only the combined prompt, no splitting
        assert len(result) == 1
        assert result[0].text == prompt


def test_multi_prompt_segments_preserve_directives(tmp_path: Path) -> None:
    """Test that segments with directives (%wait, %name) are preserved as-is."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt(
            "%name builder Fix the bug\n---\n%wait\n%name reviewer Review the fix"
        )
        result = _load_prompt_history()
        texts = {e.text for e in result}
        assert "%name builder Fix the bug" in texts
        assert "%wait\n%name reviewer Review the fix" in texts


def test_single_word_prompt_not_written(tmp_path: Path) -> None:
    """Test that a single-word prompt (e.g. bare xprompt trigger) is dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("#gh:sase")
        assert _load_prompt_history() == []


def test_whitespace_only_prompt_not_written(tmp_path: Path) -> None:
    """Test that whitespace-only prompts are dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("   \n\t  ")
        assert _load_prompt_history() == []


def test_two_word_prompt_is_written(tmp_path: Path) -> None:
    """Test that a 2-word prompt is written normally (boundary case)."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("fix bug")
        result = _load_prompt_history()
        assert len(result) == 1
        assert result[0].text == "fix bug"


def test_single_word_cancelled_prompt_not_written(tmp_path: Path) -> None:
    """Test that a cancelled single-word prompt is also dropped."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("#gh:sase", cancelled=True)
        assert _load_prompt_history() == []


def test_multi_prompt_skips_short_segments(tmp_path: Path) -> None:
    """Test that short segments in a multi-prompt are skipped but the whole is kept."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt._get_current_branch_or_workspace", return_value="main"
        ),
        patch("sase.history.prompt._get_workspace_name", return_value="myproject"),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
    ):
        add_or_update_prompt("#gh:sase\n---\nfix auth bug")
        result = _load_prompt_history()
        texts = {e.text for e in result}
        # Whole string (3 words) and "fix auth bug" segment saved;
        # the single-word "#gh:sase" segment skipped.
        assert "#gh:sase\n---\nfix auth bug" in texts
        assert "fix auth bug" in texts
        assert "#gh:sase" not in texts
        assert len(result) == 2


def test_multi_prompt_segments_use_own_vcs_ref_for_history_key(
    tmp_path: Path,
) -> None:
    """Segments with different VCS refs are indexed under their own refs."""
    test_file = tmp_path / "prompt_history.json"
    prompt = (
        "#git:sase #pr:sase_feature\nstart the ChangeSpec\n"
        "---\n"
        "#git:sase_feature\ncontinue the work"
    )
    with (
        patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file),
        patch("sase.history.prompt.generate_timestamp", return_value="251231_143052"),
        patch(
            "sase.workspace_provider.get_ref_patterns",
            return_value={"git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))")},
        ),
    ):
        add_or_update_prompt(
            prompt,
            project_name="sase",
            branch_or_workspace="sase",
        )

        entries = {entry.text: entry for entry in _load_prompt_history()}
        assert entries[prompt].branch_or_workspace == "sase"
        assert (
            entries[
                "#git:sase #pr:sase_feature\nstart the ChangeSpec"
            ].branch_or_workspace
            == "sase"
        )
        assert (
            entries["#git:sase_feature\ncontinue the work"].branch_or_workspace
            == "sase_feature"
        )


def test_existing_single_word_entry_not_updated(tmp_path: Path) -> None:
    """Test that an existing single-word entry does not get its last_used bumped."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        entry = PromptEntry(
            text="#gh:sase",
            branch_or_workspace="main",
            timestamp="251231_100000",
            last_used="251231_100000",
            workspace="myproject",
        )
        _save_prompt_history([entry])

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
            add_or_update_prompt("#gh:sase")

        result = _load_prompt_history()
        assert len(result) == 1
        # last_used should NOT have been bumped
        assert result[0].last_used == "251231_100000"


def test_handles_missing_fields_in_json(tmp_path: Path) -> None:
    """Test that JSON entries with missing fields are filtered out."""
    test_file = tmp_path / "prompt_history.json"
    # Both entries are missing workspace field, so both should be filtered out
    test_file.write_text(
        '{"prompts": [{"text": "missing_workspace", "branch_or_workspace": "main", '
        '"timestamp": "251231_143052", "last_used": "251231_143052"}, '
        '{"text": "missing_fields"}]}'
    )
    with patch("sase.history.prompt._PROMPT_HISTORY_FILE", test_file):
        result = _load_prompt_history()
        # Both entries are missing required workspace field
        assert len(result) == 0

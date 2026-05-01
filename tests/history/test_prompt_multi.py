"""Tests for multi-prompt history entries."""

import re
from pathlib import Path
from unittest.mock import patch

import sase.history.prompt as prompt_history
from sase.history.prompt import (
    PromptEntry,
    _load_prompt_history,
    _save_prompt_history,
    add_or_update_prompt,
)


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

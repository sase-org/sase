"""Tests for multi-prompt history entries."""

from pathlib import Path
from unittest.mock import patch

import sase.history.prompt_store as prompt_store
from sase.history.prompt_store import (
    PromptEntry,
    add_or_update_prompt,
    load_prompt_history,
    save_prompt_history,
)


def test_multi_prompt_saves_combined_and_segments(tmp_path: Path) -> None:
    """Test that a multi-agent prompt saves both the combined and individual segments."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt(
            "Fix the broken auth bug\n---\n%wait Review the fix and add tests"
        )
        result = load_prompt_history()
        texts = {e.text for e in result}
        assert len(result) == 3
        assert (
            "Fix the broken auth bug\n---\n%wait Review the fix and add tests" in texts
        )
        assert "Fix the broken auth bug" in texts
        assert "%wait Review the fix and add tests" in texts


def test_multi_prompt_saves_combined_and_segments_in_one_mutation(
    tmp_path: Path,
) -> None:
    """Test that multi-prompt history does not load/save once per segment."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
        patch(
            "sase.history.prompt_store.load_shard_for_write",
            wraps=prompt_store.load_shard_for_write,
        ) as load_for_write,
        patch(
            "sase.history.prompt_store.save_shard",
            wraps=prompt_store.save_shard,
        ) as save_history,
    ):
        add_or_update_prompt(
            "Fix the broken auth bug\n---\nAdd more regression tests today"
        )

        assert load_for_write.call_count == 1
        assert save_history.call_count == 1
        assert {entry.text for entry in load_prompt_history()} == {
            "Fix the broken auth bug\n---\nAdd more regression tests today",
            "Fix the broken auth bug",
            "Add more regression tests today",
        }


def test_multi_prompt_segment_dedup(tmp_path: Path) -> None:
    """Test that a segment already in history just gets last_used bumped."""
    test_file = tmp_path / "prompt_history.json"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file):
        entry = PromptEntry(
            text="Fix the broken auth bug",
            timestamp="251231_100000",
            last_used="251231_100000",
        )
        save_prompt_history([entry])

        with patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_200000"
        ):
            add_or_update_prompt(
                "Fix the broken auth bug\n---\nAdd more regression tests today"
            )

        result = load_prompt_history()
        assert len(result) == 3
        segment_entry = next(e for e in result if e.text == "Fix the broken auth bug")
        assert segment_entry.timestamp == "251231_100000"
        assert segment_entry.last_used == "251231_200000"


def test_cancelled_multi_prompt_saves_cancelled_segments(tmp_path: Path) -> None:
    """Test that a cancelled multi-agent prompt saves each segment as cancelled."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt(
            "Draft auth fix for later\n---\nDraft test plan for tomorrow",
            cancelled=True,
        )
        result = load_prompt_history()
        assert len(result) == 3
        for entry in result:
            assert entry.cancelled is True


def test_cancelled_multi_prompt_can_save_only_combined_entry(
    tmp_path: Path,
) -> None:
    """Test that cancel-all can preserve a joined prompt as one history entry."""
    test_file = tmp_path / "prompt_history.json"
    prompt = "Draft auth fix\n---\nDraft test plan"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt(prompt, cancelled=True, record_segments=False)
        result = load_prompt_history()

        assert len(result) == 1
        assert result[0].text == prompt
        assert result[0].cancelled is True


def test_single_segment_with_frontmatter_does_not_split(tmp_path: Path) -> None:
    """Test that a single-segment prompt with frontmatter does NOT split."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        prompt = (
            "---\nxprompts:\n  _style:\n    - prompt_part: Be concise\n---\nFix the bug"
        )
        add_or_update_prompt(prompt)
        result = load_prompt_history()
        assert len(result) == 1
        assert result[0].text == prompt


def test_multi_prompt_segments_preserve_directives(tmp_path: Path) -> None:
    """Test that segments with directives (%wait, %id) are preserved as-is."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt(
            "%id builder Fix the bug\n---\n%wait\n%id reviewer Review the fix"
        )
        result = load_prompt_history()
        texts = {e.text for e in result}
        assert "%id builder Fix the bug" in texts
        assert "%wait\n%id reviewer Review the fix" in texts


def test_prompt_history_preserves_raw_alt_prompt(tmp_path: Path) -> None:
    """Fan-out name injection is spawn-time only; history keeps user input."""
    test_file = tmp_path / "prompt_history.json"
    prompt = (
        "%id review\n"
        "%alt(sec=[[security pass]],perf=[[perf pass]])\n"
        "Audit this feature carefully"
    )
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt(prompt)
        entries = load_prompt_history()

    assert [entry.text for entry in entries] == [prompt]
    assert all("%id:review.sec" not in entry.text for entry in entries)


def test_multi_prompt_skips_short_segments(tmp_path: Path) -> None:
    """Test that short segments in a multi-prompt are skipped but the whole is kept."""
    test_file = tmp_path / "prompt_history.json"
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt("#gh:sase\n---\nfix the broken auth bug")
        result = load_prompt_history()
        texts = {e.text for e in result}
        assert "#gh:sase\n---\nfix the broken auth bug" in texts
        assert "fix the broken auth bug" in texts
        assert "#gh:sase" not in texts
        assert len(result) == 2


def test_multi_prompt_segments_do_not_derive_vcs_history_keys(
    tmp_path: Path,
) -> None:
    """Segments are saved and deduped without segment-specific VCS history keys."""
    test_file = tmp_path / "prompt_history.json"
    prompt = (
        "#git:sase #pr:sase_feature\nstart the ChangeSpec\n"
        "---\n"
        "#git:sase_feature\ncontinue the important work"
    )
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", test_file),
        patch(
            "sase.history.prompt_store.generate_timestamp", return_value="251231_143052"
        ),
    ):
        add_or_update_prompt(prompt)

        entries = {entry.text: entry for entry in load_prompt_history()}
        assert entries[prompt].branch_or_workspace == ""
        assert (
            entries[
                "#git:sase #pr:sase_feature\nstart the ChangeSpec"
            ].branch_or_workspace
            == ""
        )
        assert (
            entries[
                "#git:sase_feature\ncontinue the important work"
            ].branch_or_workspace
            == ""
        )

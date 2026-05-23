"""Tests for chat history names, paths, and catalog helpers."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.history.chat import (
    _get_branch_or_workspace_name,
    _load_chat_history,
    generate_chat_filename,
    get_chat_file_path,
    list_chat_histories,
)

from tests.conftest import redirect_sase_home


def test_get_branch_or_workspace_name_strips_reverted_suffix() -> None:
    """Test _get_branch_or_workspace_name strips reverted suffix."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "feature_branch__3\n"

    with patch("sase.history.chat.run_shell_command", return_value=mock_result):
        result = _get_branch_or_workspace_name()
        assert result == "feature_branch"  # suffix stripped


def test_get_branch_or_workspace_name_failure() -> None:
    """Test _get_branch_or_workspace_name with failed command."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "command not found"

    with patch("sase.history.chat.run_shell_command", return_value=mock_result):
        with pytest.raises(
            RuntimeError, match="Failed to get branch_or_workspace_name"
        ):
            _get_branch_or_workspace_name()


def testgenerate_chat_filename_with_agent() -> None:
    """Test generate_chat_filename with agent name."""
    with (
        patch(
            "sase.history.chat._get_branch_or_workspace_name", return_value="my-branch"
        ),
        patch("sase.history.chat.generate_timestamp", return_value="251128_120000"),
    ):
        # User/workflow-derived filename components are sanitized.
        result = generate_chat_filename("crs", agent="planner")
        assert result == "my_branch-crs-planner-251128_120000"


def testgenerate_chat_filename_with_explicit_values() -> None:
    """Test generate_chat_filename with explicit branch and timestamp."""
    result = generate_chat_filename(
        "rerun",
        branch_or_workspace="feature-branch",
        timestamp="251128130000",
    )
    assert result == "feature_branch-rerun-251128130000"


def testgenerate_chat_filename_sanitizes_path_like_branch() -> None:
    """Path-like branch/workspace labels are kept inside one basename."""
    result = generate_chat_filename(
        "ace-run",
        branch_or_workspace="~/org",
        timestamp="260501_225009",
    )

    assert result == "__org-ace_run-260501_225009"
    assert "/" not in result


def testgenerate_chat_filename_preserves_simple_shape() -> None:
    """Simple safe names keep the established branch-workflow-timestamp shape."""
    result = generate_chat_filename(
        "ace-run",
        branch_or_workspace="feature_branch",
        timestamp="260501_225009",
    )

    assert result == "feature_branch-ace_run-260501_225009"


def testget_chat_file_path_with_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_chat_file_path returns the sharded write location for a basename."""
    redirect_sase_home(monkeypatch, tmp_path)
    result = get_chat_file_path("my-branch-run-251128_120000.md")
    # Sharded into the YYYYMM directory derived from the filename timestamp.
    assert result == str(
        tmp_path / "chats" / "202511" / "my-branch-run-251128_120000.md"
    )


def test__load_chat_history_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test _load_chat_history with non-existent file."""
    redirect_sase_home(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        _load_chat_history("nonexistent-run-251128_120000")


def test_list_chat_histories_nonexistent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test list_chat_histories when directory doesn't exist."""
    # Redirect ~/.sase/ into an empty tmp_path -- no chats/ subdir.
    redirect_sase_home(monkeypatch, tmp_path)
    result = list_chat_histories()
    assert result == []


def test_list_chat_histories_with_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test list_chat_histories with multiple files."""
    redirect_sase_home(monkeypatch, tmp_path)
    chats_shard = tmp_path / "chats" / "202511"
    chats_shard.mkdir(parents=True)
    (chats_shard / "test-run-251128_120000.md").write_text("content")
    (chats_shard / "test-run-251128_130000.md").write_text("content")

    result = list_chat_histories()
    assert len(result) == 2
    assert "test-run-251128_120000" in result
    assert "test-run-251128_130000" in result


def test__load_chat_history_with_increment_headings() -> None:
    """Test _load_chat_history with increment_headings=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.md"
        content = """# Main Title

## Section 1

Some content here.

### Subsection

More content.

#### Deep section

Even more."""
        test_file.write_text(content, encoding="utf-8")

        result = _load_chat_history(str(test_file), increment_headings=True)

        # All headings should be incremented by one level
        assert "## Main Title" in result
        assert "### Section 1" in result
        assert "#### Subsection" in result
        assert "##### Deep section" in result
        # Original headings should not be present
        assert "\n# Main Title" not in result

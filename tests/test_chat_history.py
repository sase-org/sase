"""Tests for the chat_history module."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from sase.chat_history import (
    _generate_chat_filename,
    _get_branch_or_workspace_name,
    _get_chat_file_path,
    list_chat_histories,
    load_chat_for_resume,
    _load_chat_history,
    save_chat_history,
)


def test_get_branch_or_workspace_name_strips_reverted_suffix() -> None:
    """Test _get_branch_or_workspace_name strips reverted suffix."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "feature_branch__3\n"

    with patch("sase.chat_history.run_shell_command", return_value=mock_result):
        result = _get_branch_or_workspace_name()
        assert result == "feature_branch"  # suffix stripped


def test_get_branch_or_workspace_name_failure() -> None:
    """Test _get_branch_or_workspace_name with failed command."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "command not found"

    with patch("sase.chat_history.run_shell_command", return_value=mock_result):
        with pytest.raises(
            RuntimeError, match="Failed to get branch_or_workspace_name"
        ):
            _get_branch_or_workspace_name()


def test_generate_chat_filename_with_agent() -> None:
    """Test _generate_chat_filename with agent name."""
    with (
        patch(
            "sase.chat_history._get_branch_or_workspace_name", return_value="my-branch"
        ),
        patch("sase.chat_history.generate_timestamp", return_value="251128_120000"),
    ):
        # Workflow dashes are normalized to underscores in filename
        result = _generate_chat_filename("crs", agent="planner")
        assert result == "my-branch-crs-planner-251128_120000"


def test_generate_chat_filename_with_explicit_values() -> None:
    """Test _generate_chat_filename with explicit branch and timestamp."""
    result = _generate_chat_filename(
        "rerun",
        branch_or_workspace="feature-branch",
        timestamp="251128130000",
    )
    assert result == "feature-branch-rerun-251128130000"


def test_get_chat_file_path_with_extension() -> None:
    """Test _get_chat_file_path when extension is already present."""
    result = _get_chat_file_path("my-branch-run-251128120000.md")
    assert result == os.path.expanduser("~/.sase/chats/my-branch-run-251128120000.md")


def test_save_chat_history_basic() -> None:
    """Test save_chat_history creates a file with correct content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_chats_dir = os.path.join(tmpdir, "chats")
        os.makedirs(test_chats_dir)

        with patch("sase.chat_history.get_sase_directory", return_value=test_chats_dir):
            with patch(
                "sase.chat_history._get_branch_or_workspace_name",
                return_value="test-branch",
            ):
                with patch(
                    "sase.chat_history.generate_timestamp", return_value="251128120000"
                ):
                    result = save_chat_history(
                        prompt="Hello, how are you?",
                        response="I am fine, thank you!",
                        workflow="run",
                    )

                    assert os.path.exists(result)
                    with open(result) as f:
                        content = f.read()
                    assert "Hello, how are you?" in content
                    assert "I am fine, thank you!" in content
                    assert "# Chat History - run" in content


def test_save_chat_history_with_previous_history() -> None:
    """Test save_chat_history with previous history prepended."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_chats_dir = os.path.join(tmpdir, "chats")
        os.makedirs(test_chats_dir)

        with patch("sase.chat_history.get_sase_directory", return_value=test_chats_dir):
            with patch(
                "sase.chat_history._get_branch_or_workspace_name",
                return_value="test-branch",
            ):
                with patch(
                    "sase.chat_history.generate_timestamp", return_value="251128120000"
                ):
                    result = save_chat_history(
                        prompt="Follow up question",
                        response="Follow up answer",
                        workflow="rerun",
                        previous_history="Previous conversation content",
                    )

                    with open(result) as f:
                        content = f.read()
                    assert "Previous Conversation" in content
                    assert "Previous conversation content" in content
                    assert "Follow up question" in content


def test__load_chat_history_not_found() -> None:
    """Test _load_chat_history with non-existent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_chats_dir = os.path.join(tmpdir, "chats")
        os.makedirs(test_chats_dir)

        with patch("sase.chat_history.get_sase_directory", return_value=test_chats_dir):
            with pytest.raises(FileNotFoundError):
                _load_chat_history("nonexistent-run-251128120000")


def test_list_chat_histories_nonexistent_dir() -> None:
    """Test list_chat_histories when directory doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent_dir = os.path.join(tmpdir, "nonexistent")

        with patch(
            "sase.chat_history.get_sase_directory", return_value=nonexistent_dir
        ):
            result = list_chat_histories()
            assert result == []


def test_list_chat_histories_with_files() -> None:
    """Test list_chat_histories with multiple files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_chats_dir = os.path.join(tmpdir, "chats")
        os.makedirs(test_chats_dir)

        # Create test files
        files = ["test-run-251128120000.md", "test-run-251128130000.md"]
        for filename in files:
            filepath = os.path.join(test_chats_dir, filename)
            with open(filepath, "w") as f:
                f.write("content")

        with patch("sase.chat_history.get_sase_directory", return_value=test_chats_dir):
            result = list_chat_histories()
            assert len(result) == 2
            assert "test-run-251128120000" in result
            assert "test-run-251128130000" in result


def test__load_chat_history_with_increment_headings() -> None:
    """Test _load_chat_history with increment_headings=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.md")
        content = """# Main Title

## Section 1

Some content here.

### Subsection

More content.

#### Deep section

Even more."""
        with open(test_file, "w") as f:
            f.write(content)

        result = _load_chat_history(test_file, increment_headings=True)

        # All headings should be incremented by one level
        assert "## Main Title" in result
        assert "### Section 1" in result
        assert "#### Subsection" in result
        assert "##### Deep section" in result
        # Original headings should not be present
        assert "\n# Main Title" not in result


# --- Tests for parse_chat_turns and load_chat_for_resume ---


def test_load_chat_for_resume_format() -> None:
    """Test load_chat_for_resume produces flat User/Assistant format."""
    content = """\
# Chat History - run

**Timestamp:** 2024-01-02

## Previous Conversation

## Chat History - run

**Timestamp:** 2024-01-01

### Prompt

Hello

### Response

World

---

## Prompt

Follow up

## Response

Follow up answer
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.md")
        with open(test_file, "w") as f:
            f.write(content)

        result = load_chat_for_resume(test_file)

    # Should have flat format with no markdown headings
    assert "**User:**" in result
    assert "**Assistant:**" in result
    assert "## Prompt" not in result
    assert "## Response" not in result
    assert "### Prompt" not in result

    # Content should be in chronological order
    hello_pos = result.index("Hello")
    followup_pos = result.index("Follow up")
    assert hello_pos < followup_pos

    # Turns should be separated by ---
    assert "---" in result


def test_load_chat_for_resume_fallback() -> None:
    """Test load_chat_for_resume falls back to raw content if no turns found."""
    content = "Just some raw text with no prompt/response structure."
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.md")
        with open(test_file, "w") as f:
            f.write(content)

        result = load_chat_for_resume(test_file)

    assert result == content

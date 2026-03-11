"""Tests for adding and modifying commit entries."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.commit_utils import (
    add_commit_entry,
    add_proposed_commit_entry,
    get_next_commit_number,
    save_diff,
)
from sase.commit_utils.entries import (
    get_next_proposal_letter,
)


# Tests for get_next_commit_number
def test_get_next_commit_number_wrong_changespec() -> None:
    """Test getting next history number for non-existent changespec."""
    lines = [
        "NAME: other_cl\n",
        "DESCRIPTION:\n",
        "  Test\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (1) First commit\n",
    ]
    next_num = get_next_commit_number(lines, "test_cl")
    assert next_num == 1


# Tests for add_commit_entry
def test_add_commit_entry_new_history_field() -> None:
    """Test adding history entry when COMMITS field doesn't exist."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("DESCRIPTION:\n")
        f.write("  Test description\n")
        f.write("STATUS: Ready\n")
        temp_path = f.name

    try:
        result = add_commit_entry(
            project_file=temp_path,
            cl_name="test_cl",
            note="Initial Commit",
            diff_path="~/.sase/diffs/test.diff",
            chat_path="~/.sase/chats/test.md",
        )
        assert result is True

        # Verify the file contents
        with open(temp_path) as f:
            content = f.read()
        assert "COMMITS:" in content
        assert "  (1) Initial Commit" in content
        assert "      | CHAT: ~/.sase/chats/test.md" in content
        assert "      | DIFF: ~/.sase/diffs/test.diff" in content
    finally:
        os.unlink(temp_path)


def test_add_commit_entry_existing_history_field() -> None:
    """Test adding history entry when COMMITS field already exists."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("DESCRIPTION:\n")
        f.write("  Test description\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("      | DIFF: ~/.sase/diffs/first.diff\n")
        temp_path = f.name

    try:
        result = add_commit_entry(
            project_file=temp_path,
            cl_name="test_cl",
            note="Second commit",
            diff_path="~/.sase/diffs/second.diff",
        )
        assert result is True

        # Verify the file contents
        with open(temp_path) as f:
            content = f.read()
        assert "  (1) First commit" in content
        assert "  (2) Second commit" in content
        assert "      | DIFF: ~/.sase/diffs/second.diff" in content
    finally:
        os.unlink(temp_path)


def test_add_commit_entry_nonexistent_file() -> None:
    """Test adding history entry to non-existent file."""
    result = add_commit_entry(
        project_file="/nonexistent/file.gp",
        cl_name="test_cl",
        note="Test",
    )
    assert result is False


# Tests for save_diff
@patch("sase.commit_utils.workspace.get_vcs_provider")
def test_save_diff_no_changes(mock_get_provider: MagicMock, tmp_path: Path) -> None:
    """Test save_diff when there are no changes (returns None)."""
    mock_provider = MagicMock()
    mock_provider.add_remove.return_value = (True, None)
    mock_provider.diff.return_value = (True, None)
    mock_get_provider.return_value = mock_provider

    result = save_diff("test_cl", str(tmp_path))
    assert result is None


# Tests for get_next_proposal_letter
def test_get_next_proposal_letter_fills_gap() -> None:
    """Test that next letter fills gaps."""
    lines = [
        "NAME: test_cl\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (2) Second commit\n",
        "  (2a) First proposal\n",
        "  (2c) Third proposal\n",  # 'b' is missing
    ]
    letter = get_next_proposal_letter(lines, "test_cl", 2)
    assert letter == "b"


# Tests for add_proposed_commit_entry
def test_add_proposed_commit_entry_new_history() -> None:
    """Test adding proposed entry when no COMMITS exists."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        temp_path = f.name

    try:
        success, entry_id = add_proposed_commit_entry(
            project_file=temp_path,
            cl_name="test_cl",
            note="Proposed change",
            diff_path="~/.sase/diffs/test.diff",
        )
        assert success is True
        assert entry_id == "0a"  # No prior entries, base is 0

        with open(temp_path) as f:
            content = f.read()
        assert "COMMITS:" in content
        assert "(0a) Proposed change" in content
        assert "| DIFF: ~/.sase/diffs/test.diff" in content
    finally:
        os.unlink(temp_path)


def test_add_proposed_commit_entry_existing_history() -> None:
    """Test adding proposed entry to existing COMMITS."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("      | DIFF: ~/.sase/diffs/first.diff\n")
        temp_path = f.name

    try:
        success, entry_id = add_proposed_commit_entry(
            project_file=temp_path,
            cl_name="test_cl",
            note="Proposed change",
            diff_path="~/.sase/diffs/proposed.diff",
            chat_path="~/.sase/chats/proposed.md",
        )
        assert success is True
        assert entry_id == "1a"

        with open(temp_path) as f:
            content = f.read()
        assert "(1) First commit" in content
        assert "(1a) Proposed change" in content
        assert "| CHAT: ~/.sase/chats/proposed.md" in content
        assert "| DIFF: ~/.sase/diffs/proposed.diff" in content
    finally:
        os.unlink(temp_path)


def test_add_proposed_commit_entry_nonexistent_file() -> None:
    """Test adding proposed entry to non-existent file."""
    success, entry_id = add_proposed_commit_entry(
        project_file="/nonexistent/file.gp",
        cl_name="test_cl",
        note="Test",
    )
    assert success is False
    assert entry_id is None

"""Tests for renumber_commit_entries function in accept_workflow module."""

import os
import tempfile

from sase.accept_workflow import renumber_commit_entries


def test_renumber_commit_entries_nonexistent_file() -> None:
    """Test renumbering with non-existent file."""
    result = renumber_commit_entries("/nonexistent/file.gp", "test_cl", [(1, "a")])
    assert result is False


def test_renumber_commit_entries_no_history_section() -> None:
    """Test renumbering when no COMMITS section exists."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        temp_path = f.name

    try:
        result = renumber_commit_entries(temp_path, "test_cl", [(1, "a")])
        assert result is False
    finally:
        os.unlink(temp_path)


def test_renumber_commit_entries_preserves_diffs() -> None:
    """Test that renumbering preserves DIFF paths."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("      | DIFF: ~/.sase/diffs/first.diff\n")
        f.write("  (1a) Proposal\n")
        f.write("      | CHAT: ~/.sase/chats/proposal.md\n")
        f.write("      | DIFF: ~/.sase/diffs/proposal.diff\n")
        temp_path = f.name

    try:
        result = renumber_commit_entries(temp_path, "test_cl", [(1, "a")])
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # Original diffs preserved
        assert "| DIFF: ~/.sase/diffs/first.diff" in content
        # Proposal diffs preserved
        assert "| CHAT: ~/.sase/chats/proposal.md" in content
        assert "| DIFF: ~/.sase/diffs/proposal.diff" in content
    finally:
        os.unlink(temp_path)


def test_renumber_commit_entries_mark_ready_to_mail_idempotent() -> None:
    """Test mark_ready_to_mail doesn't duplicate suffix if already present."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready - (!: READY TO MAIL)\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("  (1a) Only proposal - (!: NEW PROPOSAL)\n")
        temp_path = f.name

    try:
        result = renumber_commit_entries(
            temp_path, "test_cl", [(1, "a")], mark_ready_to_mail=True
        )
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # Should still have exactly one READY TO MAIL suffix
        assert content.count("(!: READY TO MAIL)") == 1
        # Check it's formatted correctly
        assert "STATUS: Ready - (!: READY TO MAIL)" in content
    finally:
        os.unlink(temp_path)


def test_renumber_commit_entries_mark_ready_to_mail_with_extra_msgs() -> None:
    """Test mark_ready_to_mail works correctly with extra_msgs."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("  (1a) Proposal A - (!: NEW PROPOSAL)\n")
        f.write("  (1b) Proposal B - (!: NEW PROPOSAL)\n")
        temp_path = f.name

    try:
        result = renumber_commit_entries(
            temp_path,
            "test_cl",
            [(1, "a")],
            extra_msgs=["Added the foobar"],
            mark_ready_to_mail=True,
        )
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # (1a) became (2) with message appended
        assert "(2) Proposal A - Added the foobar" in content
        # (1b) stays as (1b) but rejected
        assert "(1b) Proposal B - (~!: NEW PROPOSAL)" in content
        # READY TO MAIL suffix added
        assert "STATUS: Ready - (!: READY TO MAIL)" in content
    finally:
        os.unlink(temp_path)

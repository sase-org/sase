"""Tests for comments module utilities."""

import tempfile
from pathlib import Path

from sase.ace.changespec import CommentEntry
from sase.ace.comments import (
    comment_needs_crs,
    get_comments_file_path,
    is_comments_suffix_stale,
)
from sase.ace.constants import DEFAULT_ZOMBIE_TIMEOUT_SECONDS
from sase.core.time import generate_timestamp


def test_get_comments_file_path() -> None:
    """Test that get_comments_file_path builds correct path."""
    file_path = get_comments_file_path("my_feature", "reviewer", "241226_120000")

    # Should contain the name, reviewer, and timestamp
    assert "my_feature" in file_path
    assert "reviewer" in file_path
    assert "241226_120000" in file_path
    assert file_path.endswith(".json")


def test_is_comments_suffix_stale_fresh() -> None:
    """Test is_comments_suffix_stale returns False for fresh timestamp."""
    # Use a timestamp from now - should not be stale
    fresh_timestamp = generate_timestamp()
    assert is_comments_suffix_stale(fresh_timestamp) is False


def test_is_comments_suffix_stale_non_timestamp() -> None:
    """Test is_comments_suffix_stale returns False for non-timestamp suffix."""
    # Non-timestamp suffixes are not considered stale
    assert is_comments_suffix_stale("!") is False
    assert is_comments_suffix_stale("2a") is False


def test_comment_needs_crs_no_suffix() -> None:
    """Test comment_needs_crs returns True when no suffix."""
    entry = CommentEntry(
        reviewer="reviewer",
        file_path="~/.sase/comments/test-reviewer-241226_120000.json",
        suffix=None,
    )
    assert comment_needs_crs(entry) is True


def test_default_zombie_timeout_is_two_hours() -> None:
    """Test that DEFAULT_ZOMBIE_TIMEOUT_SECONDS is 2 hours."""
    assert DEFAULT_ZOMBIE_TIMEOUT_SECONDS == 7200  # 2 hours in seconds


def test_comment_entry_parsing() -> None:
    """Test CommentEntry dataclass creation."""
    entry = CommentEntry(
        reviewer="johndoe",
        file_path="/path/to/comments.json",
        suffix="241226_120000",
    )
    assert entry.reviewer == "johndoe"
    assert entry.file_path == "/path/to/comments.json"
    assert entry.suffix == "241226_120000"


def test_comment_entry_no_suffix() -> None:
    """Test CommentEntry dataclass with no suffix."""
    entry = CommentEntry(
        reviewer="reviewer",
        file_path="/path/to/comments.json",
    )
    assert entry.reviewer == "reviewer"
    assert entry.file_path == "/path/to/comments.json"
    assert entry.suffix is None


def test_is_comments_suffix_stale_none() -> None:
    """Test is_comments_suffix_stale with None suffix."""
    assert is_comments_suffix_stale(None) is False


def test_changespec_with_multiple_comments() -> None:
    """Test ChangeSpec with multiple comment entries."""
    from sase.ace.changespec import ChangeSpec

    cs = ChangeSpec(
        name="Test",
        description="Test",
        parent=None,
        cl="123",
        status="Mailed",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.md",
        line_number=1,
        comments=[
            CommentEntry(
                reviewer="reviewer1",
                file_path="~/.sase/comments/test-reviewer1-241226_120000.json",
            ),
            CommentEntry(
                reviewer="reviewer2",
                file_path="~/.sase/comments/test-reviewer2-241226_130000.json",
                suffix="!",
            ),
        ],
    )
    assert cs.comments is not None
    assert len(cs.comments) == 2
    assert cs.comments[0].reviewer == "reviewer1"
    assert cs.comments[0].suffix is None
    assert cs.comments[1].reviewer == "reviewer2"
    assert cs.comments[1].suffix == "!"


# --- Tests for display module helpers ---


def test_comments_entry_with_suffix_parsing() -> None:
    """Test that COMMENTS entries with suffix are parsed correctly."""
    from sase.ace.changespec import parse_project_file

    project_content = """NAME: test_feature
DESCRIPTION:
  Test feature description
STATUS: Mailed
COMMENTS:
  [reviewer] ~/.sase/comments/test_feature-reviewer-241226_120000.json - (2a)
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(project_content)
        project_file = f.name

    try:
        changespecs = parse_project_file(project_file)
        assert len(changespecs) == 1
        cs = changespecs[0]
        assert cs.comments is not None
        assert len(cs.comments) == 1
        assert cs.comments[0].reviewer == "reviewer"
        assert cs.comments[0].suffix == "2a"
    finally:
        Path(project_file).unlink()

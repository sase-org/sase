"""Tests for ace/scheduler/comments_handler.py - comment zombie detection."""

from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.changespec import CommentEntry
from sase.ace.scheduler.comments_handler import check_comment_zombies


# Tests for check_comment_zombies
def test_check_comment_zombies_no_comments(make_changespec: Any) -> None:
    """Test check_comment_zombies returns empty list when no comments."""
    cs = make_changespec.create(comments=None)
    result = check_comment_zombies(cs)
    assert result == []


@patch("sase.ace.scheduler.comments_handler.set_comment_suffix")
@patch("sase.ace.scheduler.comments_handler.is_comments_suffix_stale")
def test_check_comment_zombies_multiple_mixed(
    mock_is_stale: MagicMock, mock_set_suffix: MagicMock, make_changespec: Any
) -> None:
    """Test check_comment_zombies with mix of stale and fresh comments."""
    # First call returns True (stale), second returns False (fresh)
    mock_is_stale.side_effect = [True, False]

    comments = [
        CommentEntry(
            reviewer="critique", file_path="/path/to/c1.json", suffix="241225_100000"
        ),
        CommentEntry(
            reviewer="critique", file_path="/path/to/c2.json", suffix="241225_120000"
        ),
    ]
    cs = make_changespec.create(comments=comments)

    result = check_comment_zombies(cs)

    assert len(result) == 1
    assert "critique" in result[0]
    mock_set_suffix.assert_called_once()

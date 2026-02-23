"""Tests for evaluating parsed queries against ChangeSpec objects."""

from typing import Any

from sase.ace.changespec import (
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
)
from sase.ace.query import evaluate_query, parse_query


def test_evaluate_string_match_case_sensitive(
    make_changespec: Any,
) -> None:
    """Test case-sensitive string matching."""
    query = parse_query('c"Feature"')
    cs = make_changespec.create(name="my_Feature_test")
    assert evaluate_query(query, cs) is True

    cs2 = make_changespec.create(name="my_feature_test")
    assert evaluate_query(query, cs2) is False


def test_evaluate_or_match(make_changespec: Any) -> None:
    """Test OR expression evaluation."""
    query = parse_query('"feature" OR "bugfix"')
    cs1 = make_changespec.create(name="my_feature")
    assert evaluate_query(query, cs1) is True

    cs2 = make_changespec.create(name="my_bugfix")
    assert evaluate_query(query, cs2) is True

    cs3 = make_changespec.create(name="refactor")
    assert evaluate_query(query, cs3) is False


def test_evaluate_error_suffix_matches_ready_to_mail(
    make_changespec: Any,
) -> None:
    """Test !!! matches ChangeSpec with READY TO MAIL suffix."""
    query = parse_query("!!!")
    cs = make_changespec.create(status="Ready - (!: READY TO MAIL)")
    assert evaluate_query(query, cs) is True


def test_evaluate_error_suffix_matches_history_suffix(
    make_changespec: Any,
) -> None:
    """Test !!! matches ChangeSpec with suffix in COMMITS entry."""
    query = parse_query("!!!")
    cs = make_changespec.create(
        status="Ready",  # No suffix in status
        commits=[
            CommitEntry(
                number=1,
                note="Some note",
                suffix="NEW PROPOSAL",
                suffix_type="error",
            )
        ],
    )
    assert evaluate_query(query, cs) is True


def test_evaluate_error_suffix_matches_comment_suffix(
    make_changespec: Any,
) -> None:
    """Test !!! matches ChangeSpec with suffix in COMMENTS entry."""
    query = parse_query("!!!")
    cs = make_changespec.create(
        status="Ready",  # No suffix in status
        comments=[
            CommentEntry(
                reviewer="reviewer@example.com",
                file_path="~/.sase/comments/test.yml",
                suffix="UNREAD",
                suffix_type="error",
            )
        ],
    )
    assert evaluate_query(query, cs) is True


def test_evaluate_no_status_suffix_excludes_hook_suffix(
    make_changespec: Any,
) -> None:
    """Test !! excludes ChangeSpec with suffix in HOOKS status line."""
    query = parse_query("!!")
    cs = make_changespec.create(
        status="Ready",  # No suffix in status
        hooks=[
            HookEntry(
                command="bb_test",
                status_lines=[
                    HookStatusLine(
                        commit_entry_num="1",
                        timestamp="251230_120000",
                        status="FAILED",
                        suffix="ZOMBIE",
                        suffix_type="error",
                    )
                ],
            )
        ],
    )
    assert evaluate_query(query, cs) is False


def test_evaluate_error_suffix_ignores_plain_hook_suffix(
    make_changespec: Any,
) -> None:
    """Test !!! does NOT match plain suffixes (without !: prefix) in hooks."""
    query = parse_query("!!!")
    cs = make_changespec.create(
        status="Ready",  # No suffix in status
        hooks=[
            HookEntry(
                command="bb_test",
                status_lines=[
                    HookStatusLine(
                        commit_entry_num="1",
                        timestamp="251230_120000",
                        status="FAILED",
                        suffix="CL 123456 presubmit failed",  # Plain suffix, no !:
                        suffix_type=None,  # Not an error suffix
                    )
                ],
            )
        ],
    )
    assert evaluate_query(query, cs) is False


def test_evaluate_error_suffix_ignores_plain_suffix(
    make_changespec: Any,
) -> None:
    """Test !!! does NOT match plain suffixes (no prefix) in history."""
    query = parse_query("!!!")
    cs = make_changespec.create(
        status="Ready",  # No suffix in status
        commits=[
            CommitEntry(
                number=1,
                note="Some note",
                suffix="OLD PROPOSAL",
                suffix_type=None,  # plain suffix, not !:
            )
        ],
    )
    assert evaluate_query(query, cs) is False

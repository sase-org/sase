"""Tests for format_changespec_for_clipboard() function."""

from typing import Any
from unittest.mock import patch

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.ace.tui.actions.clipboard._helpers import format_changespec_for_clipboard


def _make_basic_changespec(
    name: str = "test_cl",
    description: str = "Test description",
    status: str = "Ready",
    **kwargs: Any,
) -> ChangeSpec:
    """Helper to create a basic ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        status=status,
        parent=kwargs.get("parent"),
        cl=kwargs.get("cl"),
        test_targets=kwargs.get("test_targets"),
        kickstart=kwargs.get("kickstart"),
        bug=kwargs.get("bug"),
        commits=kwargs.get("commits"),
        hooks=kwargs.get("hooks"),
        comments=kwargs.get("comments"),
        mentors=kwargs.get("mentors"),
        file_path="/tmp/test.gp",
        line_number=1,
    )


def test_format_changespec_with_parent() -> None:
    """Test formatting ChangeSpec with parent field."""
    cs = _make_basic_changespec(parent="parent_cl")
    result = format_changespec_for_clipboard(cs)
    assert "PARENT: parent_cl" in result


def test_format_changespec_with_cl() -> None:
    """Test formatting ChangeSpec with CL field."""
    cs = _make_basic_changespec(cl="12345")
    with patch(
        "sase.ace.tui.actions.clipboard._helpers.get_change_label",
        return_value="CL",
    ):
        result = format_changespec_for_clipboard(cs)
    assert "CL: 12345" in result


def test_format_changespec_with_bug() -> None:
    """Test formatting ChangeSpec with bug field."""
    cs = _make_basic_changespec(bug="b/123456")
    result = format_changespec_for_clipboard(cs)
    assert "BUG: b/123456" in result


def test_format_changespec_with_test_targets() -> None:
    """Test formatting ChangeSpec with test targets."""
    cs = _make_basic_changespec(test_targets=["//foo:test1", "//bar:test2"])
    result = format_changespec_for_clipboard(cs)
    assert "TEST_TARGETS: //foo:test1, //bar:test2" in result


def test_format_changespec_with_kickstart() -> None:
    """Test formatting ChangeSpec with kickstart field."""
    cs = _make_basic_changespec(kickstart="some kickstart value")
    result = format_changespec_for_clipboard(cs)
    assert "KICKSTART: some kickstart value" in result


def test_format_changespec_commits_with_plain_suffix() -> None:
    """Test formatting commits with plain suffix (no type)."""
    commits = [
        CommitEntry(number=1, note="Commit with note", suffix="Plain note"),
    ]
    cs = _make_basic_changespec(commits=commits)
    result = format_changespec_for_clipboard(cs)
    assert "(1) Commit with note - (Plain note)" in result


def test_format_changespec_commits_with_chat_and_diff() -> None:
    """Test formatting commits with chat and diff paths."""
    commits = [
        CommitEntry(
            number=1,
            note="Commit with artifacts",
            chat="/path/to/chat.md",
            diff="/path/to/diff.txt",
        ),
    ]
    cs = _make_basic_changespec(commits=commits)
    result = format_changespec_for_clipboard(cs)
    assert "[chat: /path/to/chat.md]" in result
    assert "[diff: /path/to/diff.txt]" in result


def test_format_changespec_with_hooks() -> None:
    """Test formatting ChangeSpec with HOOKS section."""
    hooks = [
        HookEntry(command="flake8 src"),
        HookEntry(command="pytest tests"),
    ]
    cs = _make_basic_changespec(hooks=hooks)
    result = format_changespec_for_clipboard(cs)
    assert "HOOKS:" in result
    assert "  flake8 src" in result
    assert "  pytest tests" in result


def test_format_changespec_hooks_with_status_lines() -> None:
    """Test formatting hooks with status lines."""
    hooks = [
        HookEntry(
            command="flake8 src",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_123456",
                    status="PASSED",
                    duration="1m23s",
                ),
            ],
        ),
    ]
    cs = _make_basic_changespec(hooks=hooks)
    result = format_changespec_for_clipboard(cs)
    assert "  flake8 src" in result
    assert "(1) [240601_123456] PASSED (1m23s)" in result


def test_format_changespec_hooks_with_summarize_complete_suffix() -> None:
    """Test formatting hooks with summarize_complete suffix type."""
    hooks = [
        HookEntry(
            command="test_hook",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_123456",
                    status="FAILED",
                    suffix="fix_id",
                    suffix_type="summarize_complete",
                ),
            ],
        ),
    ]
    cs = _make_basic_changespec(hooks=hooks)
    result = format_changespec_for_clipboard(cs)
    assert "(%: fix_id)" in result


def test_format_changespec_hooks_with_summary() -> None:
    """Test formatting hooks with compound suffix (suffix + summary)."""
    hooks = [
        HookEntry(
            command="test_hook",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_123456",
                    status="FAILED",
                    suffix="fix_id",
                    suffix_type="summarize_complete",
                    summary="Brief summary of error",
                ),
            ],
        ),
    ]
    cs = _make_basic_changespec(hooks=hooks)
    result = format_changespec_for_clipboard(cs)
    assert "(%: fix_id | Brief summary of error)" in result


def test_format_changespec_with_comments() -> None:
    """Test formatting ChangeSpec with COMMENTS section."""
    comments = [
        CommentEntry(reviewer="critique", file_path="/path/to/comments.json"),
    ]
    cs = _make_basic_changespec(comments=comments)
    result = format_changespec_for_clipboard(cs)
    assert "COMMENTS:" in result
    assert "[critique] /path/to/comments.json" in result


def test_format_changespec_comments_with_suffix() -> None:
    """Test formatting comments with suffix."""
    comments = [
        CommentEntry(
            reviewer="critique",
            file_path="/path/to/comments.json",
            suffix="Unresolved Comments",
            suffix_type="error",
        ),
    ]
    cs = _make_basic_changespec(comments=comments)
    result = format_changespec_for_clipboard(cs)
    assert "(!: Unresolved Comments)" in result


def test_format_changespec_comments_with_running_agent_suffix() -> None:
    """Test formatting comments with running_agent suffix."""
    comments = [
        CommentEntry(
            reviewer="critique",
            file_path="/path/to/comments.json",
            suffix="agent_240601_123456",
            suffix_type="running_agent",
        ),
    ]
    cs = _make_basic_changespec(comments=comments)
    result = format_changespec_for_clipboard(cs)
    assert "(@: agent_240601_123456)" in result


def test_format_changespec_mentors_with_draft() -> None:
    """Test formatting mentors with Draft marker."""
    mentors = [
        MentorEntry(entry_id="1", profiles=["profile1"], is_draft=True),
    ]
    cs = _make_basic_changespec(mentors=mentors)
    result = format_changespec_for_clipboard(cs)
    assert "(1) profile1 (Draft)" in result


def test_format_changespec_mentors_with_status_lines() -> None:
    """Test formatting mentors with status lines."""
    mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["test_profile"],
            status_lines=[
                MentorStatusLine(
                    timestamp="251231_120000",
                    profile_name="test_profile",
                    mentor_name="test_mentor",
                    status="PASSED",
                    duration="5m30s",
                ),
            ],
        ),
    ]
    cs = _make_basic_changespec(mentors=mentors)
    result = format_changespec_for_clipboard(cs)
    assert "test_profile:test_mentor - PASSED - (5m30s)" in result


def test_format_changespec_mentors_status_with_timestamp() -> None:
    """Test formatting mentor status lines with timestamp."""
    mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["test_profile"],
            status_lines=[
                MentorStatusLine(
                    timestamp="240601_123456",
                    profile_name="test_profile",
                    mentor_name="test_mentor",
                    status="RUNNING",
                ),
            ],
        ),
    ]
    cs = _make_basic_changespec(mentors=mentors)
    result = format_changespec_for_clipboard(cs)
    assert "[240601_123456] test_profile:test_mentor - RUNNING" in result


def test_format_changespec_mentors_status_with_suffix() -> None:
    """Test formatting mentor status lines with suffix."""
    mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["test_profile"],
            status_lines=[
                MentorStatusLine(
                    timestamp="251231_120000",
                    profile_name="test_profile",
                    mentor_name="test_mentor",
                    status="RUNNING",
                    suffix="mentor_process_123",
                    suffix_type="running_agent",
                ),
            ],
        ),
    ]
    cs = _make_basic_changespec(mentors=mentors)
    result = format_changespec_for_clipboard(cs)
    assert "(@: mentor_process_123)" in result

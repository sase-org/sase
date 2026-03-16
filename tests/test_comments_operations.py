"""Tests for ace/comments/operations.py - pure comment formatting and manipulation."""

from sase.ace.changespec import CommentEntry
from sase.ace.comments.operations import (
    _apply_comments_to_lines,
    _format_comments_field,
    mark_comment_agents_as_killed,
)


# ---------------------------------------------------------------------------
# _format_comments_field
# ---------------------------------------------------------------------------


def test_format_comments_field_empty() -> None:
    assert _format_comments_field([]) == []


def test_format_comments_field_plain() -> None:
    entry = CommentEntry(reviewer="alice", file_path="/path/to/file.json")
    lines = _format_comments_field([entry])
    assert lines[0] == "COMMENTS:\n"
    assert "[alice] /path/to/file.json\n" in lines[1]


def test_format_comments_field_error_suffix_by_type() -> None:
    entry = CommentEntry(
        reviewer="bob",
        file_path="/path/file.json",
        suffix="ZOMBIE",
        suffix_type="error",
    )
    lines = _format_comments_field([entry])
    assert "(!: ZOMBIE)" in lines[1]


def test_format_comments_field_error_suffix_auto_detect() -> None:
    entry = CommentEntry(
        reviewer="bob",
        file_path="/path/file.json",
        suffix="ZOMBIE",
        suffix_type=None,
    )
    lines = _format_comments_field([entry])
    assert "(!: ZOMBIE)" in lines[1]


def test_format_comments_field_running_agent_by_type() -> None:
    entry = CommentEntry(
        reviewer="crs",
        file_path="/path/file.json",
        suffix="crs-12345-260101_120000",
        suffix_type="running_agent",
    )
    lines = _format_comments_field([entry])
    assert "(@: crs-12345-260101_120000)" in lines[1]


def test_format_comments_field_running_agent_auto_detect() -> None:
    entry = CommentEntry(
        reviewer="crs",
        file_path="/path/file.json",
        suffix="crs-12345-260101_120000",
        suffix_type=None,
    )
    lines = _format_comments_field([entry])
    assert "(@: crs-12345-260101_120000)" in lines[1]


def test_format_comments_field_killed_agent() -> None:
    entry = CommentEntry(
        reviewer="crs",
        file_path="/path/file.json",
        suffix="crs-12345-260101_120000",
        suffix_type="killed_agent",
    )
    lines = _format_comments_field([entry])
    assert "(~@: crs-12345-260101_120000)" in lines[1]


def test_format_comments_field_plain_suffix() -> None:
    entry = CommentEntry(
        reviewer="alice",
        file_path="/path/file.json",
        suffix="3a",
        suffix_type="plain",
    )
    lines = _format_comments_field([entry])
    assert "(3a)" in lines[1]
    # Should not have error or running prefix
    assert "!:" not in lines[1]
    assert "@:" not in lines[1]


def test_format_comments_field_multiple() -> None:
    entries = [
        CommentEntry(reviewer="alice", file_path="/a.json"),
        CommentEntry(reviewer="bob", file_path="/b.json", suffix="done"),
    ]
    lines = _format_comments_field(entries)
    assert len(lines) == 3  # header + 2 entries


# ---------------------------------------------------------------------------
# _apply_comments_to_lines
# ---------------------------------------------------------------------------


def test_apply_comments_insert_new() -> None:
    """Insert COMMENTS into a changespec that has none."""
    file_lines = [
        "NAME: my_feature\n",
        "DESCRIPTION: Feature description\n",
        "STATUS: Draft\n",
    ]
    entry = CommentEntry(reviewer="alice", file_path="/a.json")
    result = _apply_comments_to_lines(file_lines, "my_feature", [entry])
    assert "COMMENTS:\n" in result
    assert "[alice]" in result


def test_apply_comments_replace_existing() -> None:
    """Replace existing COMMENTS field."""
    file_lines = [
        "NAME: my_feature\n",
        "COMMENTS:\n",
        "  [old_reviewer] /old.json\n",
        "STATUS: Draft\n",
    ]
    entry = CommentEntry(reviewer="new_rev", file_path="/new.json")
    result = _apply_comments_to_lines(file_lines, "my_feature", [entry])
    assert "[new_rev]" in result
    assert "[old_reviewer]" not in result


def test_apply_comments_remove() -> None:
    """Remove COMMENTS field when comments=None."""
    file_lines = [
        "NAME: my_feature\n",
        "COMMENTS:\n",
        "  [alice] /a.json\n",
        "STATUS: Draft\n",
    ]
    result = _apply_comments_to_lines(file_lines, "my_feature", None)
    assert "COMMENTS:" not in result
    assert "[alice]" not in result


def test_apply_comments_wrong_changespec() -> None:
    """Don't modify a different changespec."""
    file_lines = [
        "NAME: other_feature\n",
        "STATUS: Draft\n",
    ]
    entry = CommentEntry(reviewer="alice", file_path="/a.json")
    result = _apply_comments_to_lines(file_lines, "my_feature", [entry])
    assert "COMMENTS:" not in result


def test_apply_comments_end_of_file() -> None:
    """Insert at end when target is last changespec with no trailing content."""
    file_lines = [
        "NAME: my_feature\n",
        "STATUS: Draft\n",
    ]
    entry = CommentEntry(reviewer="alice", file_path="/a.json")
    result = _apply_comments_to_lines(file_lines, "my_feature", [entry])
    assert "COMMENTS:\n" in result
    assert "[alice]" in result


def test_apply_comments_multiple_changespecs() -> None:
    """Insert into correct changespec when multiple exist."""
    file_lines = [
        "NAME: first\n",
        "STATUS: Draft\n",
        "\n",
        "\n",
        "NAME: second\n",
        "STATUS: Ready\n",
    ]
    entry = CommentEntry(reviewer="bob", file_path="/b.json")
    result = _apply_comments_to_lines(file_lines, "second", [entry])
    assert "[bob]" in result
    # The first changespec should not get comments
    first_idx = result.index("NAME: first")
    second_idx = result.index("NAME: second")
    bob_idx = result.index("[bob]")
    assert bob_idx > second_idx > first_idx


# ---------------------------------------------------------------------------
# mark_comment_agents_as_killed
# ---------------------------------------------------------------------------


def test_mark_agents_killed_basic() -> None:
    c1 = CommentEntry(
        reviewer="crs",
        file_path="/a.json",
        suffix="crs-12345-260101_120000",
        suffix_type="running_agent",
    )
    c2 = CommentEntry(reviewer="alice", file_path="/b.json")
    killed = [(c1, 12345)]
    result = mark_comment_agents_as_killed([c1, c2], killed)
    assert result[0].suffix_type == "killed_agent"
    assert result[1].suffix_type is None  # unchanged


def test_mark_agents_killed_no_match() -> None:
    c1 = CommentEntry(reviewer="alice", file_path="/a.json")
    result = mark_comment_agents_as_killed(
        [c1],
        [(CommentEntry(reviewer="bob", file_path="/b.json", suffix="x"), 999)],
    )
    assert result[0].suffix_type is None


def test_mark_agents_killed_empty() -> None:
    result = mark_comment_agents_as_killed([], [])
    assert result == []

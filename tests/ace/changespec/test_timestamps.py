"""Tests for TIMESTAMPS field parsing, formatting, and recording."""

import os
import tempfile

from sase.ace.changespec.models import TimestampEntry
from sase.ace.changespec.parser import parse_project_file
from sase.ace.timestamps.formatting import format_timestamps_field
from sase.ace.timestamps.recording import (
    _find_timestamps_insert_point,
    add_timestamp_entry_atomic,
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_timestamps_section() -> None:
    """Round-trip: parse a TIMESTAMPS section from a .gp file."""
    content = """\
NAME: my-cl
DESCRIPTION:
  Some description
STATUS: WIP
TIMESTAMPS:
  [2026-03-29 14:30:22] COMMIT  (1)
  [2026-03-29 14:32:15] COMMIT  (2)
  [2026-03-29 14:35:10] STATUS  WIP -> Draft
  [2026-03-29 15:00:00] SYNC    success
  [2026-03-29 15:10:00] REWORD  description
  [2026-03-29 15:15:00] REWORD  tag "Bug"
  [2026-03-29 15:20:00] COMMIT  (2a)


"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name

    try:
        changespecs = parse_project_file(path)
        assert len(changespecs) == 1
        cs = changespecs[0]
        assert cs.timestamps is not None
        assert len(cs.timestamps) == 7

        # Verify first entry
        assert cs.timestamps[0].timestamp == "2026-03-29 14:30:22"
        assert cs.timestamps[0].event_type == "COMMIT"
        assert cs.timestamps[0].detail == "(1)"

        # Verify STATUS entry
        assert cs.timestamps[2].event_type == "STATUS"
        assert cs.timestamps[2].detail == "WIP -> Draft"

        # Verify SYNC entry
        assert cs.timestamps[3].event_type == "SYNC"
        assert cs.timestamps[3].detail == "success"

        # Verify REWORD entries
        assert cs.timestamps[4].event_type == "REWORD"
        assert cs.timestamps[4].detail == "description"
        assert cs.timestamps[5].detail == 'tag "Bug"'

        # Verify proposed commit
        assert cs.timestamps[6].detail == "(2a)"
    finally:
        os.unlink(path)


def test_parse_no_timestamps_section() -> None:
    """ChangeSpec without TIMESTAMPS should have timestamps=None."""
    content = """\
NAME: my-cl
DESCRIPTION:
  Some description
STATUS: WIP


"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name

    try:
        changespecs = parse_project_file(path)
        assert len(changespecs) == 1
        assert changespecs[0].timestamps is None
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_timestamps_field() -> None:
    """Serialize TimestampEntry list to .gp format."""
    entries = [
        TimestampEntry("2026-03-29 14:30:22", "COMMIT", "(1)"),
        TimestampEntry("2026-03-29 14:35:10", "STATUS", "WIP -> Draft"),
        TimestampEntry("2026-03-29 15:00:00", "SYNC", "success"),
        TimestampEntry("2026-03-29 15:10:00", "REWORD", "description"),
    ]
    result = format_timestamps_field(entries)

    assert result.startswith("TIMESTAMPS:\n")
    lines = result.strip().split("\n")
    assert len(lines) == 5  # header + 4 entries

    # Check alignment — event type padded to 7 chars
    assert "COMMIT " in lines[1]
    assert "STATUS " in lines[2]
    assert "SYNC   " in lines[3]
    assert "REWORD " in lines[4]


# ---------------------------------------------------------------------------
# Atomic recording
# ---------------------------------------------------------------------------


def test_find_timestamps_insert_creates_section() -> None:
    """First event creates the TIMESTAMPS section header."""
    lines = [
        "NAME: my-cl\n",
        "DESCRIPTION:\n",
        "  Some description\n",
        "STATUS: WIP\n",
        "\n",
        "\n",
    ]
    idx = _find_timestamps_insert_point(lines, "my-cl")
    assert idx is not None
    # The header should have been inserted
    assert any("TIMESTAMPS:" in line for line in lines)
    # Insert point is right after the header
    header_idx = next(i for i, line in enumerate(lines) if "TIMESTAMPS:" in line)
    assert idx == header_idx + 1


def test_find_timestamps_insert_appends_to_existing() -> None:
    """New entries append after the last existing entry."""
    lines = [
        "NAME: my-cl\n",
        "STATUS: WIP\n",
        "TIMESTAMPS:\n",
        "  [2026-03-29 14:30:22] COMMIT  (1)\n",
        "\n",
        "\n",
    ]
    idx = _find_timestamps_insert_point(lines, "my-cl")
    assert idx == 4  # right after entry on line 3


def test_add_timestamp_entry_atomic_creates_entry() -> None:
    """add_timestamp_entry_atomic creates section and entry in file."""
    content = """\
NAME: my-cl
DESCRIPTION:
  Some description
STATUS: WIP


"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name

    try:
        ok = add_timestamp_entry_atomic(path, "my-cl", "COMMIT", "(1)")
        assert ok

        with open(path) as f:
            new_content = f.read()

        assert "TIMESTAMPS:" in new_content
        assert "COMMIT " in new_content
        assert "(1)" in new_content
    finally:
        os.unlink(path)


def test_add_timestamp_entry_atomic_appends() -> None:
    """Second call appends to existing section."""
    content = """\
NAME: my-cl
DESCRIPTION:
  Some description
STATUS: WIP
TIMESTAMPS:
  [2026-03-29 14:30:22] COMMIT  (1)


"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name

    try:
        ok = add_timestamp_entry_atomic(path, "my-cl", "STATUS", "WIP -> Draft")
        assert ok

        with open(path) as f:
            new_content = f.read()

        assert "STATUS " in new_content
        assert "WIP -> Draft" in new_content
        # Original entry still present
        assert "COMMIT " in new_content
        assert "(1)" in new_content
    finally:
        os.unlink(path)


def test_initial_commits_record_timestamps() -> None:
    """add_changespec_to_project_file records COMMIT timestamps for initial commits."""
    # Create a minimal project file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("")
        f.flush()
        path = f.name

    try:
        from unittest.mock import patch

        from sase.workflows.commit.changespec_operations import (
            add_changespec_to_project_file,
        )

        with patch(
            "sase.workflows.commit.changespec_operations.get_project_file_path",
            return_value=path,
        ):
            cl_name = add_changespec_to_project_file(
                project="test-proj",
                cl_name="test_cl",
                description="Test description",
                parent=None,
                initial_commits=[(1, "[run] Initial Commit", None, None)],
            )

        assert cl_name is not None

        with open(path) as f:
            content = f.read()

        assert "TIMESTAMPS:" in content
        assert "COMMIT" in content
        assert "(1)" in content
    finally:
        os.unlink(path)


def test_add_timestamp_entry_wrong_cl_returns_false() -> None:
    """Returns False when CL name not found."""
    content = """\
NAME: my-cl
STATUS: WIP


"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name

    try:
        ok = add_timestamp_entry_atomic(path, "nonexistent-cl", "COMMIT", "(1)")
        assert not ok
    finally:
        os.unlink(path)

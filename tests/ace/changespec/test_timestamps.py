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
  260329_143022 COMMIT  (1)
  260329_143215 COMMIT  (2)
  260329_143510 STATUS  WIP -> Draft
  260329_150000 SYNC    success
  260329_151000 REWORD  description
  260329_151500 REWORD  tag "Bug"
  260329_152000 COMMIT  (2a)
  260329_152500 REWIND  (3)


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
        assert len(cs.timestamps) == 8

        # Verify first entry
        assert cs.timestamps[0].timestamp == "260329_143022"
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

        # Verify REWIND entry
        assert cs.timestamps[7].event_type == "REWIND"
        assert cs.timestamps[7].detail == "(3)"
    finally:
        os.unlink(path)


def test_parse_timestamps_old_format() -> None:
    """Backward compatibility: parse old [YYYY-MM-DD HH:MM:SS] format."""
    content = """\
NAME: my-cl
DESCRIPTION:
  Some description
STATUS: WIP
TIMESTAMPS:
  [2026-03-29 14:30:22] COMMIT  (1)
  [2026-03-29 14:35:10] STATUS  WIP -> Draft


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
        assert len(cs.timestamps) == 2

        assert cs.timestamps[0].timestamp == "2026-03-29 14:30:22"
        assert cs.timestamps[0].event_type == "COMMIT"
        assert cs.timestamps[0].detail == "(1)"

        assert cs.timestamps[1].timestamp == "2026-03-29 14:35:10"
        assert cs.timestamps[1].event_type == "STATUS"
        assert cs.timestamps[1].detail == "WIP -> Draft"
    finally:
        os.unlink(path)


def test_parse_timestamps_hybrid_format() -> None:
    """Parse hybrid [YYMMDD_HHMMSS] format from migration transition."""
    content = """\
NAME: my-cl
DESCRIPTION:
  Some description
STATUS: WIP
TIMESTAMPS:
  [260330_102053] SYNC    success
  [260330_102100] COMMIT  (1)

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
        assert len(cs.timestamps) == 2

        assert cs.timestamps[0].timestamp == "260330_102053"
        assert cs.timestamps[0].event_type == "SYNC"
        assert cs.timestamps[0].detail == "success"

        assert cs.timestamps[1].timestamp == "260330_102100"
        assert cs.timestamps[1].event_type == "COMMIT"
        assert cs.timestamps[1].detail == "(1)"
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
        TimestampEntry("260329_143022", "COMMIT", "(1)"),
        TimestampEntry("260329_143510", "STATUS", "WIP -> Draft"),
        TimestampEntry("260329_150000", "SYNC", "success"),
        TimestampEntry("260329_151000", "REWORD", "description"),
        TimestampEntry("260329_152500", "REWIND", "(3)"),
    ]
    result = format_timestamps_field(entries)

    assert result.startswith("TIMESTAMPS:\n")
    lines = result.strip().split("\n")
    assert len(lines) == 6  # header + 5 entries

    # Check alignment — event type padded to 7 chars
    assert "COMMIT " in lines[1]
    assert "STATUS " in lines[2]
    assert "SYNC   " in lines[3]
    assert "REWORD " in lines[4]
    assert "REWIND " in lines[5]


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
        "  260329_143022 COMMIT  (1)\n",
        "\n",
        "\n",
    ]
    idx = _find_timestamps_insert_point(lines, "my-cl")
    assert idx == 4  # right after entry on line 3


def test_find_timestamps_insert_appends_to_old_format() -> None:
    """New entries append after old-format entries too."""
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


def test_find_timestamps_insert_appends_to_hybrid_format() -> None:
    """New entries append after hybrid [YYMMDD_HHMMSS] entries."""
    lines = [
        "NAME: my-cl\n",
        "STATUS: WIP\n",
        "TIMESTAMPS:\n",
        "  [260330_102053] SYNC    success\n",
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
  260329_143022 COMMIT  (1)


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


def test_add_timestamp_entry_atomic_after_name_change() -> None:
    """Timestamp recording works when CL name was changed by suffix strip."""
    # Simulate post-suffix-strip state: file has NAME: foo (not foo__1)
    content = """\
NAME: foo
DESCRIPTION:
  Some description
STATUS: Ready
TIMESTAMPS:
  260329_143022 COMMIT  (1)


"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        f.flush()
        path = f.name

    try:
        # Using the post-rename name "foo" (not "foo__1") should succeed
        ok = add_timestamp_entry_atomic(path, "foo", "STATUS", "Draft -> Ready")
        assert ok

        with open(path) as f:
            new_content = f.read()

        assert "STATUS " in new_content
        assert "Draft -> Ready" in new_content
        # Original entry still present
        assert "COMMIT " in new_content
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

"""Tests for COMMITS field parsing and CommitEntry dataclass."""

from sase.ace.patch import CommitEntry
from sase.ace.patch.parser import _parse_patch_from_lines


# Tests for build_commit_entry
# Tests for COMMITS field parsing
def test_parse_patch_history_without_optional_fields() -> None:
    """Test parsing COMMITS entry without CHAT field."""
    lines = [
        "## ChangeSpec\n",
        "NAME: test_cl\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (1) Manual commit\n",
        "      | DIFF: ~/.sase/diffs/test.diff\n",
        "\n",
    ]
    patch, _ = _parse_patch_from_lines(lines, 0, "/test/file.sase")
    assert patch is not None
    assert patch.commits is not None
    assert len(patch.commits) == 1
    assert patch.commits[0].number == 1
    assert patch.commits[0].note == "Manual commit"
    assert patch.commits[0].chat is None
    assert patch.commits[0].diff == "~/.sase/diffs/test.diff"


# Tests for CommitEntry dataclass
def test_history_entry_dataclass() -> None:
    """Test CommitEntry dataclass creation."""
    entry = CommitEntry(
        number=1,
        note="Test note",
        chat="test.md",
        diff="test.diff",
    )
    assert entry.number == 1
    assert entry.note == "Test note"
    assert entry.chat == "test.md"
    assert entry.diff == "test.diff"


def test_history_entry_dataclass_defaults() -> None:
    """Test CommitEntry dataclass with default values."""
    entry = CommitEntry(number=1, note="Test")
    assert entry.number == 1
    assert entry.note == "Test"
    assert entry.chat is None
    assert entry.diff is None


def test_parse_patch_plan_drawer() -> None:
    """Test parsing COMMITS entry with PLAN drawer."""
    lines = [
        "## ChangeSpec\n",
        "NAME: test_cl\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (1) Implement plan\n",
        "      | DIFF: ~/.sase/diffs/test.diff\n",
        "      | PLAN: ~/.sase/plans/plan_foo.md\n",
        "\n",
    ]
    patch, _ = _parse_patch_from_lines(lines, 0, "/test/file.sase")
    assert patch is not None
    assert patch.commits is not None
    assert len(patch.commits) == 1
    assert patch.commits[0].plan == "~/.sase/plans/plan_foo.md"
    assert patch.commits[0].diff == "~/.sase/diffs/test.diff"


def test_parse_patch_plan_drawer_absent() -> None:
    """Test that plan is None when no PLAN drawer exists."""
    lines = [
        "## ChangeSpec\n",
        "NAME: test_cl\n",
        "DESCRIPTION:\n",
        "  Test description\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (1) Manual commit\n",
        "      | DIFF: ~/.sase/diffs/test.diff\n",
        "\n",
    ]
    patch, _ = _parse_patch_from_lines(lines, 0, "/test/file.sase")
    assert patch is not None
    assert patch.commits is not None
    assert patch.commits[0].plan is None


# Tests for CommitEntry proposal properties
# Tests for parsing proposed COMMITS entries

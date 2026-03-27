"""Tests for multi-line COMMITS note body: parsing, writing, truncation, and folding."""

from rich.text import Text

from sase.ace.changespec import ChangeSpec, CommitEntry
from sase.ace.changespec.parser import _parse_changespec_from_lines
from sase.ace.changespec.section_parsers import CommitEntryDict, build_commit_entry
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.commits_builder import (
    _truncate_note,
    build_commits_section,
)
from sase.ace.tui.widgets.hint_tracker import HintTracker
from sase.workflows.renumber_utils import (
    build_commits_section as renumber_build_commits_section,
    find_commits_section,
    parse_commit_entries,
)


# ---------------------------------------------------------------------------
# Phase 1: Data Model & Parsing
# ---------------------------------------------------------------------------


class TestCommitEntryBody:
    """Tests for the body field on CommitEntry."""

    def test_default_body_is_none(self) -> None:
        entry = CommitEntry(number=1, note="Test")
        assert entry.body is None

    def test_body_with_lines(self) -> None:
        entry = CommitEntry(number=1, note="Header", body=["Line 1", "Line 2"])
        assert entry.body == ["Line 1", "Line 2"]

    def test_body_with_blank_lines(self) -> None:
        entry = CommitEntry(number=1, note="Header", body=["Para 1", "", "Para 2"])
        assert entry.body == ["Para 1", "", "Para 2"]


class TestBuildCommitEntryWithBody:
    """Tests for build_commit_entry() with body field."""

    def test_body_passed_through(self) -> None:
        d: CommitEntryDict = {
            "number": 1,
            "note": "Header",
            "chat": None,
            "diff": None,
            "proposal_letter": None,
            "suffix": None,
            "suffix_type": None,
            "body": ["Line 1", "Line 2"],
        }
        entry = build_commit_entry(d)
        assert entry.body == ["Line 1", "Line 2"]

    def test_none_body(self) -> None:
        d: CommitEntryDict = {
            "number": 1,
            "note": "Header",
            "chat": None,
            "diff": None,
            "proposal_letter": None,
            "suffix": None,
            "suffix_type": None,
            "body": None,
        }
        entry = build_commit_entry(d)
        assert entry.body is None

    def test_empty_list_body_treated_as_none(self) -> None:
        d: CommitEntryDict = {
            "number": 1,
            "note": "Header",
            "chat": None,
            "diff": None,
            "proposal_letter": None,
            "suffix": None,
            "suffix_type": None,
            "body": [],
        }
        entry = build_commit_entry(d)
        assert entry.body is None


class TestParseCommitsLineBody:
    """Tests for parse_commits_line() with body continuation lines."""

    def test_parse_multiline_note(self) -> None:
        lines = [
            "## ChangeSpec\n",
            "NAME: test_cl\n",
            "DESCRIPTION:\n",
            "  Test\n",
            "STATUS: Ready\n",
            "COMMITS:\n",
            "  (1) Header line\n",
            "      Body line one.\n",
            "      Body line two.\n",
            "      | CHAT: /tmp/chat.md\n",
            "\n",
        ]
        cs, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
        assert cs is not None
        assert cs.commits is not None
        assert len(cs.commits) == 1
        assert cs.commits[0].note == "Header line"
        assert cs.commits[0].body == ["Body line one.", "Body line two."]
        assert cs.commits[0].chat == "/tmp/chat.md"

    def test_parse_blank_line_marker(self) -> None:
        lines = [
            "## ChangeSpec\n",
            "NAME: test_cl\n",
            "DESCRIPTION:\n",
            "  Test\n",
            "STATUS: Ready\n",
            "COMMITS:\n",
            "  (1) Header\n",
            "      Para one.\n",
            "      .\n",
            "      Para two.\n",
            "\n",
        ]
        cs, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
        assert cs is not None
        commits = cs.commits
        assert commits is not None
        assert commits[0].body == ["Para one.", "", "Para two."]

    def test_parse_no_body(self) -> None:
        lines = [
            "## ChangeSpec\n",
            "NAME: test_cl\n",
            "DESCRIPTION:\n",
            "  Test\n",
            "STATUS: Ready\n",
            "COMMITS:\n",
            "  (1) Single line note\n",
            "\n",
        ]
        cs, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
        assert cs is not None
        commits = cs.commits
        assert commits is not None
        assert commits[0].body is None

    def test_parse_body_with_drawers(self) -> None:
        """Body lines before drawers are parsed correctly."""
        lines = [
            "## ChangeSpec\n",
            "NAME: test_cl\n",
            "DESCRIPTION:\n",
            "  Test\n",
            "STATUS: Ready\n",
            "COMMITS:\n",
            "  (1) Header\n",
            "      Body line.\n",
            "      | CHAT: /tmp/c.md\n",
            "      | DIFF: /tmp/d.diff\n",
            "\n",
        ]
        cs, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
        assert cs is not None
        commits = cs.commits
        assert commits is not None
        e = commits[0]
        assert e.body == ["Body line."]
        assert e.chat == "/tmp/c.md"
        assert e.diff == "/tmp/d.diff"

    def test_parse_multiple_entries_with_body(self) -> None:
        lines = [
            "## ChangeSpec\n",
            "NAME: test_cl\n",
            "DESCRIPTION:\n",
            "  Test\n",
            "STATUS: Ready\n",
            "COMMITS:\n",
            "  (1) First header\n",
            "      First body.\n",
            "  (2) Second header\n",
            "      Second body.\n",
            "\n",
        ]
        cs, _ = _parse_changespec_from_lines(lines, 0, "/test/file.gp")
        assert cs is not None
        commits = cs.commits
        assert commits is not None
        assert len(commits) == 2
        assert commits[0].body == ["First body."]
        assert commits[1].body == ["Second body."]


# ---------------------------------------------------------------------------
# Phase 1: renumber_utils parsing
# ---------------------------------------------------------------------------


class TestRenumberParseBody:
    """Tests for parse_commit_entries() with body lines."""

    def test_parse_body_lines(self) -> None:
        lines = [
            "  (1) Header\n",
            "      Body line one.\n",
            "      Body line two.\n",
        ]
        result = parse_commit_entries(lines)
        assert len(result) == 1
        assert result[0]["body"] == ["Body line one.", "Body line two."]

    def test_parse_blank_marker(self) -> None:
        lines = [
            "  (1) Header\n",
            "      Para 1.\n",
            "      .\n",
            "      Para 2.\n",
        ]
        result = parse_commit_entries(lines)
        assert result[0]["body"] == ["Para 1.", "", "Para 2."]

    def test_parse_no_body(self) -> None:
        lines = ["  (1) Just a header\n"]
        result = parse_commit_entries(lines)
        assert result[0]["body"] is None

    def test_parse_body_with_raw_lines(self) -> None:
        lines = [
            "  (1) Header\n",
            "      Body.\n",
            "      | CHAT: /tmp/c.md\n",
        ]
        result = parse_commit_entries(lines, include_raw_lines=True)
        assert result[0]["body"] == ["Body."]
        assert len(result[0]["raw_lines"]) == 3


class TestRenumberBuildBody:
    """Tests for build_commits_section() with body."""

    def test_build_with_body(self) -> None:
        entries = [
            {
                "number": 1,
                "letter": None,
                "note": "Header",
                "chat": None,
                "diff": None,
                "body": ["Line 1", "Line 2"],
            },
        ]
        result = renumber_build_commits_section(entries)
        assert result == [
            "COMMITS:\n",
            "  (1) Header\n",
            "      Line 1\n",
            "      Line 2\n",
        ]

    def test_build_with_blank_marker(self) -> None:
        entries = [
            {
                "number": 1,
                "letter": None,
                "note": "Header",
                "chat": None,
                "diff": None,
                "body": ["Para 1", "", "Para 2"],
            },
        ]
        result = renumber_build_commits_section(entries)
        assert result == [
            "COMMITS:\n",
            "  (1) Header\n",
            "      Para 1\n",
            "      .\n",
            "      Para 2\n",
        ]

    def test_build_body_before_drawers(self) -> None:
        entries = [
            {
                "number": 1,
                "letter": None,
                "note": "Header",
                "chat": "/tmp/c.md",
                "diff": "/tmp/d.diff",
                "body": ["Body."],
            },
        ]
        result = renumber_build_commits_section(entries)
        assert result == [
            "COMMITS:\n",
            "  (1) Header\n",
            "      Body.\n",
            "      | CHAT: /tmp/c.md\n",
            "      | DIFF: /tmp/d.diff\n",
        ]

    def test_build_no_body(self) -> None:
        entries = [
            {
                "number": 1,
                "letter": None,
                "note": "Header",
                "chat": None,
                "diff": None,
                "body": None,
            },
        ]
        result = renumber_build_commits_section(entries)
        assert result == ["COMMITS:\n", "  (1) Header\n"]


class TestRoundTrip:
    """Parse → build → parse round-trip tests."""

    def test_round_trip_with_body(self) -> None:
        original = [
            "  (1) Header line\n",
            "      Body line one.\n",
            "      Body line two.\n",
            "      | CHAT: /tmp/c.md\n",
            "      | DIFF: /tmp/d.diff\n",
        ]
        parsed = parse_commit_entries(original)
        rebuilt = renumber_build_commits_section(parsed)
        # Strip "COMMITS:\n" header for comparison
        reparsed = parse_commit_entries(rebuilt[1:])
        assert parsed[0]["note"] == reparsed[0]["note"]
        assert parsed[0]["body"] == reparsed[0]["body"]
        assert parsed[0]["chat"] == reparsed[0]["chat"]
        assert parsed[0]["diff"] == reparsed[0]["diff"]

    def test_round_trip_blank_markers(self) -> None:
        original = [
            "  (1) Header\n",
            "      Para 1.\n",
            "      .\n",
            "      Para 2.\n",
        ]
        parsed = parse_commit_entries(original)
        rebuilt = renumber_build_commits_section(parsed)
        reparsed = parse_commit_entries(rebuilt[1:])
        assert parsed[0]["body"] == reparsed[0]["body"]


class TestFindCommitsSectionWithBody:
    """Test find_commits_section recognizes body lines."""

    def test_body_lines_included_in_section(self) -> None:
        lines = [
            "NAME: test_cl\n",
            "COMMITS:\n",
            "  (1) Header\n",
            "      Body line.\n",
            "      | CHAT: /tmp/c.md\n",
        ]
        start, end = find_commits_section(lines, "test_cl")
        assert (start, end) == (1, 5)


# ---------------------------------------------------------------------------
# Phase 3: Truncation
# ---------------------------------------------------------------------------


class TestTruncateNote:
    def test_no_truncation_needed(self) -> None:
        assert _truncate_note("Short", 10) == "Short"

    def test_exact_fit(self) -> None:
        assert _truncate_note("12345", 5) == "12345"

    def test_truncated(self) -> None:
        assert _truncate_note("Hello World", 6) == "Hello\u2026"  # "Hello…"

    def test_zero_available(self) -> None:
        assert _truncate_note("Test", 0) == "\u2026"

    def test_one_available(self) -> None:
        assert _truncate_note("Test", 1) == "\u2026"


# ---------------------------------------------------------------------------
# Phase 4: Body Folding (TUI)
# ---------------------------------------------------------------------------


def _make_changespec(
    commits: list[CommitEntry] | None = None,
) -> ChangeSpec:
    return ChangeSpec(
        name="test",
        description="Test",
        parent=None,
        cl=None,
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        commits=commits,
    )


class TestBodyFolding:
    """Tests for body folding in TUI display."""

    def _render(
        self,
        entry: CommitEntry,
        fold: FoldLevel,
        max_width: int | None = None,
    ) -> str:
        cs = _make_changespec(commits=[entry])
        text = Text()
        build_commits_section(
            text,
            cs,
            False,
            fold,
            HintTracker(0, {}, {}, {}, {}),
            max_width=max_width,
        )
        return text.plain

    def test_body_hidden_when_collapsed(self) -> None:
        entry = CommitEntry(number=1, note="Header", body=["Line 1", "Line 2"])
        result = self._render(entry, FoldLevel.COLLAPSED)
        assert "[+2 lines]" in result
        assert "Line 1" not in result
        assert "Line 2" not in result

    def test_body_shown_when_expanded(self) -> None:
        entry = CommitEntry(number=1, note="Header", body=["Line 1", "Line 2"])
        result = self._render(entry, FoldLevel.EXPANDED)
        assert "[+2 lines]" not in result
        assert "Line 1" in result
        assert "Line 2" in result

    def test_body_shown_when_fully_expanded(self) -> None:
        entry = CommitEntry(number=1, note="Header", body=["Line 1", "Line 2"])
        result = self._render(entry, FoldLevel.FULLY_EXPANDED)
        assert "Line 1" in result
        assert "Line 2" in result

    def test_no_body_no_indicator(self) -> None:
        entry = CommitEntry(number=1, note="Header")
        result = self._render(entry, FoldLevel.COLLAPSED)
        assert "[+" not in result

    def test_blank_body_lines_expanded(self) -> None:
        entry = CommitEntry(number=1, note="Header", body=["Para 1", "", "Para 2"])
        result = self._render(entry, FoldLevel.EXPANDED)
        assert "Para 1" in result
        assert "Para 2" in result

    def test_truncation_with_max_width(self) -> None:
        entry = CommitEntry(
            number=1,
            note="A very long note that should be truncated at some point",
        )
        result = self._render(entry, FoldLevel.COLLAPSED, max_width=30)
        assert "\u2026" in result

    def test_no_truncation_when_fits(self) -> None:
        entry = CommitEntry(number=1, note="Short")
        result = self._render(entry, FoldLevel.COLLAPSED, max_width=200)
        assert "\u2026" not in result
        assert "Short" in result

    def test_suffix_preserved_with_truncation(self) -> None:
        entry = CommitEntry(
            number=1,
            note="A very long note that definitely exceeds width",
            suffix="ERROR",
            suffix_type="error",
        )
        result = self._render(entry, FoldLevel.COLLAPSED, max_width=40)
        assert "ERROR" in result

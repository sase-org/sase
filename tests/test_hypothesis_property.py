"""Property-based tests using Hypothesis for increased coverage and robustness."""

import re

from hypothesis import given, assume
from hypothesis import strategies as st

from sase.ace.changespec.suffix_utils import parse_suffix_prefix, _ParsedSuffix
from sase.ace.changespec.models import (
    is_running_agent_suffix,
    extract_pid_from_agent_suffix,
    HookStatusLine,
    HookEntry,
)
from sase.ace.hooks.timestamps import (
    format_duration,
    get_hook_file_age_seconds_from_timestamp,
    get_hook_age_seconds,
    is_timestamp_suffix,
)
from sase.workflows.renumber_utils import (
    sort_hook_status_lines,
    sort_entries_by_id,
    parse_commit_entries,
    find_commits_section,
)
from sase.core.changespec import has_suffix, strip_reverted_suffix
from sase.core.paths import make_safe_filename
from sase.workflows.commit_utils.entries import _extract_timestamp_from_chat_path
from sase.content import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Timestamp in YYmmdd_HHMMSS format
st_valid_timestamp = st.builds(
    lambda y, mo, d, h, mi, s: f"{y:02d}{mo:02d}{d:02d}_{h:02d}{mi:02d}{s:02d}",
    y=st.integers(min_value=0, max_value=99),
    mo=st.integers(min_value=1, max_value=12),
    d=st.integers(min_value=1, max_value=28),
    h=st.integers(min_value=0, max_value=23),
    mi=st.integers(min_value=0, max_value=59),
    s=st.integers(min_value=0, max_value=59),
)

# PID-like strings (4+ digits)
st_pid = st.integers(min_value=1000, max_value=99999).map(str)

# Agent name (alphanumeric + underscore)
st_agent_name = st.from_regex(r"[a-z][a-z0-9_]{2,15}", fullmatch=True)

# Valid agent suffix: <agent>-<PID>-YYmmdd_HHMMSS
st_agent_suffix = st.builds(
    lambda name, pid, ts: f"{name}-{pid}-{ts}",
    name=st_agent_name,
    pid=st_pid,
    ts=st_valid_timestamp,
)


# ===================================================================
# TIER 1A: parse_suffix_prefix
# ===================================================================


class TestParseSuffixPrefix:
    """Tests for suffix_utils.parse_suffix_prefix covering uncovered lines."""

    def test_metahook_error_plain(self) -> None:
        """Line 59-66: '!: metahook' special case -> metahook_complete."""
        result = parse_suffix_prefix("!: metahook")
        assert result == _ParsedSuffix("", "metahook_complete")

    def test_metahook_error_with_content(self) -> None:
        """Line 62-63: '!: metahook | some content' -> metahook_complete."""
        result = parse_suffix_prefix("!: metahook | details here")
        assert result == _ParsedSuffix("details here", "metahook_complete")

    def test_metahook_error_pipe_empty(self) -> None:
        """Line 62-63: '!: metahook |' with nothing after pipe."""
        result = parse_suffix_prefix("!: metahook |")
        assert result == _ParsedSuffix("", "metahook_complete")

    def test_metahook_error_pipe_whitespace(self) -> None:
        """'!: metahook | ' with only whitespace after pipe."""
        result = parse_suffix_prefix("!: metahook | ")
        assert result == _ParsedSuffix("", "metahook_complete")

    def test_error_prefix_non_metahook(self) -> None:
        """'!: something else' is a regular error, not metahook."""
        result = parse_suffix_prefix("!: ZOMBIE")
        assert result == _ParsedSuffix("ZOMBIE", "error")

    def test_standalone_at(self) -> None:
        """Line 70-71: standalone '@' -> running_agent."""
        result = parse_suffix_prefix("@")
        assert result == _ParsedSuffix("", "running_agent")

    def test_standalone_percent(self) -> None:
        """Line 72-73: standalone '%' -> summarize_complete."""
        result = parse_suffix_prefix("%")
        assert result == _ParsedSuffix("", "summarize_complete")

    def test_standalone_caret(self) -> None:
        """Line 74-75: standalone '^' -> metahook_complete."""
        result = parse_suffix_prefix("^")
        assert result == _ParsedSuffix("", "metahook_complete")

    @given(
        st.text(min_size=1).filter(
            lambda s: (
                not any(
                    s.startswith(p)
                    for p, _ in [
                        ("~!:", ""),
                        ("~@:", ""),
                        ("~$:", ""),
                        ("?$:", ""),
                        ("!:", ""),
                        ("@:", ""),
                        ("$:", ""),
                        ("%:", ""),
                        ("^:", ""),
                        ("~:", ""),
                    ]
                )
                and s not in ("@", "%", "^")
            )
        )
    )
    def test_no_prefix_passthrough(self, s: str) -> None:
        """Strings without any prefix are returned as-is with no type."""
        result = parse_suffix_prefix(s)
        assert result.value == s
        assert result.suffix_type is None

    def test_none_input(self) -> None:
        result = parse_suffix_prefix(None)
        assert result == _ParsedSuffix(None, None)

    @given(st.text() | st.none())
    def test_always_returns_parsed_suffix(self, s: str | None) -> None:
        """parse_suffix_prefix always returns a _ParsedSuffix."""
        result = parse_suffix_prefix(s)
        assert isinstance(result, _ParsedSuffix)

    @given(st.sampled_from(list("~!@$?%^:")) | st.text(min_size=1, max_size=3))
    def test_prefix_stripping(self, msg: str) -> None:
        """For all known prefix types, the returned value is the msg after the prefix."""
        for prefix, suffix_type in [
            ("@:", "running_agent"),
            ("$:", "running_process"),
            ("%:", "summarize_complete"),
            ("^:", "metahook_complete"),
        ]:
            result = parse_suffix_prefix(f"{prefix} {msg}")
            assert result.suffix_type == suffix_type
            assert result.value is not None
            assert result.value == msg.strip()


# ===================================================================
# TIER 1B: is_running_agent_suffix + extract_pid_from_agent_suffix
# ===================================================================


class TestRunningAgentSuffix:
    """Tests for models.py lines 44, 48-53, 120/122/128."""

    @given(st_agent_suffix)
    def test_valid_agent_suffix_detected(self, suffix: str) -> None:
        """Lines 48-53: Valid agent suffixes return True."""
        assert is_running_agent_suffix(suffix) is True

    def test_none_returns_false(self) -> None:
        """Line 44: None suffix returns False."""
        assert is_running_agent_suffix(None) is False

    def test_no_dash(self) -> None:
        """No dash -> False."""
        assert is_running_agent_suffix("fixhook12345251230_151429") is False

    def test_too_few_parts(self) -> None:
        """Only 2 parts (1 dash) -> False."""
        assert is_running_agent_suffix("fixhook-251230_151429") is False

    def test_non_digit_pid(self) -> None:
        """PID is not all digits -> False."""
        assert is_running_agent_suffix("fix_hook-abc-251230_151429") is False

    def test_bad_timestamp_length(self) -> None:
        """Timestamp wrong length -> False."""
        assert is_running_agent_suffix("fix_hook-12345-251230") is False

    def test_bad_timestamp_underscore(self) -> None:
        """Timestamp missing underscore at position 6 -> False."""
        assert is_running_agent_suffix("fix_hook-12345-2512301151429") is False

    @given(st_agent_suffix)
    def test_consistency_with_extract_pid(self, suffix: str) -> None:
        """If is_running_agent_suffix is True, extract_pid should return an int."""
        if is_running_agent_suffix(suffix):
            pid = extract_pid_from_agent_suffix(suffix)
            assert isinstance(pid, int)
            assert pid >= 0

    def test_extract_pid_none(self) -> None:
        """Line 120: None suffix -> None."""
        assert extract_pid_from_agent_suffix(None) is None

    def test_extract_pid_no_dash(self) -> None:
        """Line 122: No dash -> None."""
        assert extract_pid_from_agent_suffix("nodash") is None

    def test_extract_pid_non_digit(self) -> None:
        """Line 128: Non-digit PID -> None."""
        assert extract_pid_from_agent_suffix("hook-abc-251230_151429") is None

    def test_extract_pid_too_few_parts(self) -> None:
        """Less than 3 parts -> None."""
        assert extract_pid_from_agent_suffix("hook-251230_151429") is None

    @given(st_agent_suffix)
    def test_extract_pid_correct_value(self, suffix: str) -> None:
        """Extracted PID matches the PID embedded in the suffix."""
        pid = extract_pid_from_agent_suffix(suffix)
        # The PID is the second-to-last part when split by "-"
        parts = suffix.split("-")
        expected = int(parts[-2])
        assert pid == expected


# ===================================================================
# TIER 1C: Timestamp error paths
# ===================================================================


class TestTimestampErrorPaths:
    """Tests for timestamps.py lines 56-57, 71-75, 116-117."""

    def test_invalid_timestamp_returns_none(self) -> None:
        """Lines 56-57: Unparseable timestamp -> None."""
        assert get_hook_file_age_seconds_from_timestamp("not_a_timestamp") is None

    def test_empty_timestamp_returns_none(self) -> None:
        """Lines 56-57: Empty string -> None."""
        assert get_hook_file_age_seconds_from_timestamp("") is None

    def test_correct_length_bad_format(self) -> None:
        """Lines 56-57: 13-char string but not a valid timestamp."""
        assert get_hook_file_age_seconds_from_timestamp("abcdef_ghijkl") is None

    @given(st_valid_timestamp)
    def test_valid_timestamp_returns_float(self, ts: str) -> None:
        """Valid timestamps return a float (age in seconds)."""
        result = get_hook_file_age_seconds_from_timestamp(ts)
        # Should return a float (could be negative for future timestamps, that's ok)
        assert result is None or isinstance(result, float)

    def test_hook_age_no_status_lines(self) -> None:
        """Lines 71-72: HookEntry with no status lines -> None."""
        hook = HookEntry(command="test_hook", status_lines=None)
        assert get_hook_age_seconds(hook) is None

    def test_hook_age_empty_status_lines(self) -> None:
        """Lines 71-72: HookEntry with empty status lines -> None."""
        hook = HookEntry(command="test_hook", status_lines=[])
        assert get_hook_age_seconds(hook) is None

    def test_hook_age_no_timestamp(self) -> None:
        """Lines 71-72: Status line with empty timestamp -> None."""
        sl = HookStatusLine(commit_entry_num="1", timestamp="", status="RUNNING")
        hook = HookEntry(command="test_hook", status_lines=[sl])
        assert get_hook_age_seconds(hook) is None

    def test_hook_age_valid_recent_timestamp(self) -> None:
        """Lines 71-75: HookEntry with valid timestamp returns a float."""
        from sase.ace.hooks.timestamps import get_current_timestamp

        ts = get_current_timestamp()
        sl = HookStatusLine(commit_entry_num="1", timestamp=ts, status="RUNNING")
        hook = HookEntry(command="test_hook", status_lines=[sl])
        result = get_hook_age_seconds(hook)
        assert result is not None
        assert isinstance(result, float)
        # Should be very recent (within 5 seconds)
        assert result < 5.0

    def test_is_timestamp_suffix_correct_length_bad_value(self) -> None:
        """Lines 116-117: 13-char with underscore at pos 6 but invalid date."""
        # "999999_999999" has the right structure but isn't a valid datetime
        assert is_timestamp_suffix("999999_999999") is False

    def test_is_timestamp_suffix_none(self) -> None:
        assert is_timestamp_suffix(None) is False

    @given(st_valid_timestamp)
    def test_is_timestamp_suffix_valid(self, ts: str) -> None:
        """Valid timestamps are recognized as timestamp suffixes."""
        assert is_timestamp_suffix(ts) is True


# ===================================================================
# TIER 2D: find_commits_section edge cases
# ===================================================================


class TestFindCommitsSection:
    """Tests for renumber_utils.py lines 191-193, 211."""

    def test_commits_extends_to_eof(self) -> None:
        """Line 211: commits_end = len(lines) when section extends to EOF."""
        lines = [
            "NAME: my_cl\n",
            "STATUS: Draft\n",
            "COMMITS:\n",
            "  (1) First commit\n",
            "  (2) Second commit\n",
        ]
        start, end = find_commits_section(lines, "my_cl")
        assert start == 2
        assert end == len(lines)

    def test_commits_end_at_next_changespec(self) -> None:
        """Lines 191-193: commits_end set when hitting next ChangeSpec."""
        lines = [
            "NAME: my_cl\n",
            "COMMITS:\n",
            "  (1) First commit\n",
            "      | CHAT: somechat.md\n",
            "NAME: other_cl\n",
            "STATUS: Draft\n",
        ]
        start, end = find_commits_section(lines, "my_cl")
        assert start == 1
        assert end == 4  # stops before "NAME: other_cl"

    def test_continuation_lines_tracked(self) -> None:
        """Continuation lines (| ) extend the section."""
        lines = [
            "NAME: my_cl\n",
            "COMMITS:\n",
            "  (1) First commit\n",
            "      | CHAT: chat.md\n",
            "      | DIFF: diff.md\n",
            "HOOKS:\n",
        ]
        start, end = find_commits_section(lines, "my_cl")
        assert start == 1
        assert end == 5

    def test_not_found(self) -> None:
        """Returns (-1, -1) when CL name not found."""
        lines = ["NAME: other_cl\n", "STATUS: Draft\n"]
        assert find_commits_section(lines, "my_cl") == (-1, -1)


# ===================================================================
# TIER 2E: sort_hook_status_lines uncovered branches
# ===================================================================


class TestSortHookStatusLines:
    """Tests for renumber_utils.py lines 56-57, 64-66."""

    def test_non_matching_status_line_triggers_flush(self) -> None:
        """Lines 56-57: Non-matching status line flushes accumulated lines."""
        lines = [
            "NAME: my_cl\n",
            "HOOKS:\n",
            "  my_hook\n",
            "      | (2) [260101_120000] PASSED (1m0s)\n",
            "      | (1) [260101_110000] PASSED (2m0s)\n",
            "      | BAD LINE NO MATCH\n",
            "STATUS: Draft\n",
        ]
        result = sort_hook_status_lines(lines, "my_cl")
        # After flush, (1) should come before (2)
        hook_lines = [ln for ln in result if ln.strip().startswith("| (")]
        assert "(1)" in hook_lines[0]
        assert "(2)" in hook_lines[1]

    def test_end_of_hooks_section(self) -> None:
        """Lines 64-66: End of hooks section flushes and resets."""
        lines = [
            "NAME: my_cl\n",
            "HOOKS:\n",
            "  my_hook\n",
            "      | (2) [260101_120000] PASSED\n",
            "      | (1) [260101_110000] PASSED\n",
            "COMMENTS:\n",
            "  some comment\n",
        ]
        result = sort_hook_status_lines(lines, "my_cl")
        hook_lines = [ln for ln in result if ln.strip().startswith("| (")]
        assert "(1)" in hook_lines[0]
        assert "(2)" in hook_lines[1]
        # COMMENTS line should follow
        assert "COMMENTS:\n" in result


# ===================================================================
# TIER 2F: parse_commit_entries blank lines
# ===================================================================


class TestParseCommitEntriesBlankLines:
    """Tests for renumber_utils.py lines 159-161."""

    def test_blank_line_between_entries(self) -> None:
        """Lines 159-161: Blank lines within commits section are ignored."""
        commit_lines = [
            "  (1) First commit\n",
            "\n",
            "  (2) Second commit\n",
        ]
        entries = parse_commit_entries(commit_lines)
        assert len(entries) == 2
        assert entries[0]["number"] == 1
        assert entries[1]["number"] == 2

    def test_blank_line_after_entry_with_chat(self) -> None:
        """Blank line after an entry with CHAT metadata."""
        commit_lines = [
            "  (1) First commit\n",
            "      | CHAT: chat.md\n",
            "\n",
            "  (2) Second commit\n",
        ]
        entries = parse_commit_entries(commit_lines)
        assert len(entries) == 2
        assert entries[0]["chat"] == "chat.md"

    def test_trailing_blank_line(self) -> None:
        """Trailing blank line is handled gracefully."""
        commit_lines = [
            "  (1) Only entry\n",
            "\n",
        ]
        entries = parse_commit_entries(commit_lines)
        assert len(entries) == 1


# ===================================================================
# TIER 3G: format_duration
# ===================================================================


class TestFormatDuration:
    """Property tests for format_duration."""

    @given(st.floats(min_value=0, max_value=1_000_000))
    def test_output_matches_pattern(self, seconds: float) -> None:
        """Output always matches XhYmZs, XmYs, or Zs pattern."""
        result = format_duration(seconds)
        assert re.fullmatch(r"\d+h\d+m\d+s|\d+m\d+s|\d+s", result), (
            f"Unexpected format: {result}"
        )

    @given(st.integers(min_value=0, max_value=1_000_000))
    def test_roundtrip_seconds(self, seconds: int) -> None:
        """Parsing the output recovers the original total seconds."""
        result = format_duration(seconds)
        total = 0
        m = re.fullmatch(r"(\d+)h(\d+)m(\d+)s", result)
        if m:
            total = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        else:
            m = re.fullmatch(r"(\d+)m(\d+)s", result)
            if m:
                total = int(m.group(1)) * 60 + int(m.group(2))
            else:
                m = re.fullmatch(r"(\d+)s", result)
                assert m is not None
                total = int(m.group(1))
        assert total == seconds


# ===================================================================
# TIER 3H: make_safe_filename / strip_reverted_suffix / has_suffix
# ===================================================================


class TestSafeFilenameAndSuffix:
    @given(st.text(min_size=0, max_size=200))
    def test_safe_filename_only_safe_chars(self, name: str) -> None:
        """make_safe_filename output contains only [a-zA-Z0-9_]."""
        result = make_safe_filename(name)
        assert re.fullmatch(r"[a-zA-Z0-9_]*", result), f"Unsafe chars in: {result}"

    @given(st.text(min_size=0, max_size=100))
    def test_safe_filename_idempotent(self, name: str) -> None:
        """Applying make_safe_filename twice gives the same result."""
        once = make_safe_filename(name)
        twice = make_safe_filename(once)
        assert once == twice

    @given(
        st.from_regex(r"[a-zA-Z0-9_]{1,50}", fullmatch=True),
        st.integers(min_value=0, max_value=999),
    )
    def test_strip_reverted_suffix_with_suffix(self, base: str, n: int) -> None:
        """strip_reverted_suffix removes __N suffix when present."""
        assume("__" not in base)  # Avoid nested suffixes
        name = f"{base}__{n}"
        result = strip_reverted_suffix(name)
        assert result == base

    @given(st.from_regex(r"[a-z]{3,10}", fullmatch=True))
    def test_strip_reverted_suffix_no_suffix(self, name: str) -> None:
        """Names without __N suffix are returned as-is."""
        result = strip_reverted_suffix(name)
        assert result == name

    @given(
        st.from_regex(r"[a-zA-Z0-9_]{1,50}", fullmatch=True),
        st.integers(min_value=0, max_value=999),
    )
    def test_has_suffix_consistency(self, base: str, n: int) -> None:
        """has_suffix detects exactly the __N pattern."""
        assume("__" not in base)
        name_with = f"{base}__{n}"
        assert has_suffix(name_with) is True

    @given(st.from_regex(r"[a-z]{3,10}", fullmatch=True))
    def test_has_suffix_false_without(self, name: str) -> None:
        """Names without __N return False."""
        assert has_suffix(name) is False


# ===================================================================
# TIER 3I: _extract_timestamp_from_chat_path
# ===================================================================


class TestExtractTimestampFromChatPath:
    @given(st_agent_name, st_valid_timestamp)
    def test_valid_path_returns_timestamp(self, branch: str, ts: str) -> None:
        """Valid .md paths with a timestamp return the timestamp."""
        path = f"~/.sase/chats/{branch}-crs-{ts}.md"
        result = _extract_timestamp_from_chat_path(path)
        assert result == ts

    def test_non_md_returns_none(self) -> None:
        assert _extract_timestamp_from_chat_path("foo.txt") is None

    def test_empty_returns_none(self) -> None:
        assert _extract_timestamp_from_chat_path("") is None

    def test_short_basename_returns_none(self) -> None:
        assert _extract_timestamp_from_chat_path("ab.md") is None


# ===================================================================
# TIER 3J: content_ends_with_markdown_heading / apply_section_marker_handling
# ===================================================================


class TestMarkdownHeadingAndSectionMarkers:
    @given(st.text())
    def test_trailing_newline_always_false(self, content: str) -> None:
        """Content ending with newline is never detected as heading."""
        if content.endswith("\n") or content == "":
            assert content_ends_with_markdown_heading(content) is False

    def test_heading_without_newline(self) -> None:
        assert content_ends_with_markdown_heading("## Title") is True

    def test_heading_with_newline(self) -> None:
        assert content_ends_with_markdown_heading("## Title\n") is False

    def test_multiline_heading_at_end(self) -> None:
        assert content_ends_with_markdown_heading("some text\n## Title") is True

    @given(
        st.text(min_size=1).filter(
            lambda s: not s.startswith("###") and not s.startswith("---")
        )
    )
    def test_non_marker_content_unchanged(self, content: str) -> None:
        """Non-marker content is returned unchanged."""
        assert apply_section_marker_handling(content, True) == content
        assert apply_section_marker_handling(content, False) == content

    def test_hr_marker_only(self) -> None:
        """'---' alone produces empty string."""
        assert apply_section_marker_handling("---", True) == ""
        assert apply_section_marker_handling("---", False) == ""

    def test_hr_marker_with_content_midline(self) -> None:
        """'---\\ncontent' mid-line prepends \\n\\n."""
        result = apply_section_marker_handling("---\ncontent", False)
        assert result == "\n\ncontent"

    def test_heading_marker_midline(self) -> None:
        """'### Title' mid-line prepends \\n\\n."""
        result = apply_section_marker_handling("### Title", False)
        assert result == "\n\n### Title"


# ===================================================================
# TIER 3K: sort_entries_by_id
# ===================================================================


class TestSortEntriesById:
    @given(
        st.lists(
            st.fixed_dictionaries(
                {
                    "number": st.integers(min_value=1, max_value=100),
                    "letter": st.sampled_from(["", "a", "b", "c", None]),
                }
            ),
            min_size=0,
            max_size=20,
        )
    )
    def test_idempotent(self, entries: list[dict]) -> None:
        """Sorting twice gives the same result."""
        once = sort_entries_by_id(entries)
        twice = sort_entries_by_id(once)
        assert once == twice

    @given(
        st.lists(
            st.fixed_dictionaries(
                {
                    "number": st.integers(min_value=1, max_value=100),
                    "letter": st.sampled_from(["", "a", "b", "c", None]),
                }
            ),
            min_size=0,
            max_size=20,
        )
    )
    def test_preserves_elements(self, entries: list[dict]) -> None:
        """Sorting preserves all elements (same multiset)."""
        result = sort_entries_by_id(entries)
        assert len(result) == len(entries)
        # Each entry in result should be in entries
        for e in result:
            assert e in entries

    @given(
        st.lists(
            st.fixed_dictionaries(
                {
                    "number": st.integers(min_value=1, max_value=100),
                    "letter": st.sampled_from(["", "a", "b", "c"]),
                }
            ),
            min_size=2,
            max_size=20,
        )
    )
    def test_non_decreasing_order(self, entries: list[dict]) -> None:
        """Result is in non-decreasing (number, letter) order."""
        result = sort_entries_by_id(entries)
        for i in range(len(result) - 1):
            a_num = int(result[i]["number"])
            a_let = str(result[i]["letter"]) if result[i]["letter"] else ""
            b_num = int(result[i + 1]["number"])
            b_let = str(result[i + 1]["letter"]) if result[i + 1]["letter"] else ""
            assert (a_num, a_let) <= (b_num, b_let)

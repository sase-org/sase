"""Snapshot tests for renumber_utils — covers sort, build, and parse functions."""

from inline_snapshot import snapshot

from sase.workflows.renumber_utils import (
    build_commits_section,
    find_commits_section,
    parse_commit_entries,
    sort_entries_by_id,
    sort_hook_status_lines,
)


# ---------------------------------------------------------------------------
# sort_hook_status_lines
# ---------------------------------------------------------------------------


class TestSortHookStatusLines:
    def test_sorts_status_lines_by_entry_id(self) -> None:
        lines = [
            "NAME: my_cl\n",
            "HOOKS:\n",
            "  some_hook\n",
            "      | (3) [250101_120000] PASSED (1m)\n",
            "      | (1) [250101_120000] PASSED (2m)\n",
            "      | (2) [250101_120000] FAILED (3m)\n",
        ]
        result = sort_hook_status_lines(lines, "my_cl")
        assert result == snapshot(
            [
                "NAME: my_cl\n",
                "HOOKS:\n",
                "  some_hook\n",
                "      | (1) [250101_120000] PASSED (2m)\n",
                "      | (2) [250101_120000] FAILED (3m)\n",
                "      | (3) [250101_120000] PASSED (1m)\n",
            ]
        )

    def test_sorts_with_letter_suffixes(self) -> None:
        lines = [
            "NAME: my_cl\n",
            "HOOKS:\n",
            "  hook_cmd\n",
            "      | (1b) [250101_120000] PASSED (1m)\n",
            "      | (1a) [250101_120000] FAILED (2m)\n",
            "      | (2) [250101_120000] PASSED (3m)\n",
        ]
        result = sort_hook_status_lines(lines, "my_cl")
        assert result == snapshot(
            [
                "NAME: my_cl\n",
                "HOOKS:\n",
                "  hook_cmd\n",
                "      | (1a) [250101_120000] FAILED (2m)\n",
                "      | (1b) [250101_120000] PASSED (1m)\n",
                "      | (2) [250101_120000] PASSED (3m)\n",
            ]
        )

    def test_sorts_archive_format(self) -> None:
        lines = [
            "NAME: my_cl\n",
            "HOOKS:\n",
            "  hook_cmd\n",
            "      | (1b-3) [250101_120000] PASSED (1m)\n",
            "      | (1a-3) [250101_120000] FAILED (2m)\n",
            "      | (2) [250101_120000] PASSED (3m)\n",
        ]
        result = sort_hook_status_lines(lines, "my_cl")
        assert result == snapshot(
            [
                "NAME: my_cl\n",
                "HOOKS:\n",
                "  hook_cmd\n",
                "      | (1a-3) [250101_120000] FAILED (2m)\n",
                "      | (1b-3) [250101_120000] PASSED (1m)\n",
                "      | (2) [250101_120000] PASSED (3m)\n",
            ]
        )

    def test_ignores_other_changespecs(self) -> None:
        lines = [
            "NAME: other_cl\n",
            "HOOKS:\n",
            "  hook_cmd\n",
            "      | (2) [250101_120000] PASSED (1m)\n",
            "      | (1) [250101_120000] PASSED (2m)\n",
            "NAME: my_cl\n",
            "HOOKS:\n",
            "  hook_cmd\n",
            "      | (2) [250101_120000] PASSED (1m)\n",
            "      | (1) [250101_120000] PASSED (2m)\n",
        ]
        result = sort_hook_status_lines(lines, "my_cl")
        # other_cl lines untouched (still unsorted), my_cl sorted
        assert result == snapshot(
            [
                "NAME: other_cl\n",
                "HOOKS:\n",
                "  hook_cmd\n",
                "      | (2) [250101_120000] PASSED (1m)\n",
                "      | (1) [250101_120000] PASSED (2m)\n",
                "NAME: my_cl\n",
                "HOOKS:\n",
                "  hook_cmd\n",
                "      | (1) [250101_120000] PASSED (2m)\n",
                "      | (2) [250101_120000] PASSED (1m)\n",
            ]
        )

    def test_non_matching_status_line_flushes(self) -> None:
        """Status lines that don't match the regex pattern flush accumulated lines."""
        lines = [
            "NAME: my_cl\n",
            "HOOKS:\n",
            "  hook_cmd\n",
            "      | (2) [250101_120000] PASSED\n",
            "      | no_match_line\n",
            "      | (1) [250101_120000] PASSED\n",
        ]
        result = sort_hook_status_lines(lines, "my_cl")
        # (2) is flushed before no_match_line, then (1) comes after
        assert result == snapshot(
            [
                "NAME: my_cl\n",
                "HOOKS:\n",
                "  hook_cmd\n",
                "      | (2) [250101_120000] PASSED\n",
                "      | no_match_line\n",
                "      | (1) [250101_120000] PASSED\n",
            ]
        )


# ---------------------------------------------------------------------------
# build_commits_section
# ---------------------------------------------------------------------------


class TestBuildCommitsSection:
    def test_basic_entries(self) -> None:
        entries = [
            {
                "number": 1,
                "letter": None,
                "note": "First commit",
                "chat": None,
                "diff": None,
            },
            {
                "number": 2,
                "letter": None,
                "note": "Second commit",
                "chat": None,
                "diff": None,
            },
        ]
        result = build_commits_section(entries)
        assert result == snapshot(
            [
                "COMMITS:\n",
                "  (1) First commit\n",
                "  (2) Second commit\n",
            ]
        )

    def test_with_letter(self) -> None:
        entries = [
            {
                "number": 1,
                "letter": "a",
                "note": "Proposed fix",
                "chat": None,
                "diff": None,
            },
        ]
        result = build_commits_section(entries)
        assert result == snapshot(["COMMITS:\n", "  (1a) Proposed fix\n"])

    def test_with_chat_and_diff(self) -> None:
        entries = [
            {
                "number": 1,
                "letter": None,
                "note": "Some change",
                "chat": "/tmp/chat.md",
                "diff": "/tmp/diff.txt",
            },
        ]
        result = build_commits_section(entries)
        assert result == snapshot(
            [
                "COMMITS:\n",
                "  (1) Some change\n",
                "      | CHAT: /tmp/chat.md\n",
                "      | DIFF: /tmp/diff.txt\n",
            ]
        )


# ---------------------------------------------------------------------------
# sort_entries_by_id
# ---------------------------------------------------------------------------


class TestSortEntriesById:
    def test_sorts_by_number(self) -> None:
        entries = [
            {"number": 3, "letter": None},
            {"number": 1, "letter": None},
            {"number": 2, "letter": None},
        ]
        result = sort_entries_by_id(entries)
        assert [e["number"] for e in result] == snapshot([1, 2, 3])

    def test_sorts_by_number_then_letter(self) -> None:
        entries = [
            {"number": 1, "letter": "b"},
            {"number": 2, "letter": None},
            {"number": 1, "letter": "a"},
            {"number": 1, "letter": None},
        ]
        result = sort_entries_by_id(entries)
        assert [(e["number"], e["letter"]) for e in result] == snapshot(
            [(1, None), (1, "a"), (1, "b"), (2, None)]
        )

    def test_none_number_treated_as_zero(self) -> None:
        entries = [
            {"number": 1, "letter": None},
            {"number": None, "letter": None},
        ]
        result = sort_entries_by_id(entries)
        assert [e["number"] for e in result] == snapshot([None, 1])


# ---------------------------------------------------------------------------
# parse_commit_entries
# ---------------------------------------------------------------------------


class TestParseCommitEntries:
    def test_multiple_entries(self) -> None:
        lines = [
            "  (1) First commit\n",
            "  (2) Second commit\n",
            "  (3) Third commit\n",
        ]
        result = parse_commit_entries(lines)
        assert len(result) == snapshot(3)
        assert result[0]["note"] == snapshot("First commit")
        assert result[2]["number"] == snapshot(3)

    def test_entry_with_letter(self) -> None:
        lines = ["  (1a) Proposed fix\n"]
        result = parse_commit_entries(lines)
        assert result[0]["letter"] == snapshot("a")
        assert result[0]["number"] == snapshot(1)

    def test_include_raw_lines(self) -> None:
        lines = [
            "  (1) First commit\n",
            "      | CHAT: /tmp/chat.md\n",
            "      | DIFF: /tmp/diff.txt\n",
        ]
        result = parse_commit_entries(lines, include_raw_lines=True)
        assert len(result) == snapshot(1)
        assert result[0]["raw_lines"] == snapshot(
            [
                "  (1) First commit\n",
                "      | CHAT: /tmp/chat.md\n",
                "      | DIFF: /tmp/diff.txt\n",
            ]
        )

    def test_blank_lines_between_entries(self) -> None:
        lines = [
            "  (1) First\n",
            "\n",
            "  (2) Second\n",
        ]
        result = parse_commit_entries(lines)
        assert len(result) == snapshot(2)

    def test_empty_input(self) -> None:
        result = parse_commit_entries([])
        assert result == snapshot([])


# ---------------------------------------------------------------------------
# find_commits_section
# ---------------------------------------------------------------------------


class TestFindCommitsSection:
    def test_finds_section(self) -> None:
        lines = [
            "NAME: test_cl\n",
            "STATUS: Ready\n",
            "COMMITS:\n",
            "  (1) First commit\n",
            "  (2) Second commit\n",
        ]
        start, end = find_commits_section(lines, "test_cl")
        assert (start, end) == snapshot((2, 5))

    def test_section_bounded_by_next_changespec(self) -> None:
        lines = [
            "NAME: test_cl\n",
            "COMMITS:\n",
            "  (1) First commit\n",
            "NAME: other_cl\n",
            "COMMITS:\n",
        ]
        start, end = find_commits_section(lines, "test_cl")
        assert (start, end) == snapshot((1, 3))

    def test_section_with_metadata_lines(self) -> None:
        lines = [
            "NAME: test_cl\n",
            "COMMITS:\n",
            "  (1) First commit\n",
            "      | CHAT: /tmp/chat.md\n",
        ]
        start, end = find_commits_section(lines, "test_cl")
        assert (start, end) == snapshot((1, 4))

    def test_no_commits_section(self) -> None:
        lines = [
            "NAME: test_cl\n",
            "STATUS: Ready\n",
        ]
        assert find_commits_section(lines, "test_cl") == snapshot((-1, -1))

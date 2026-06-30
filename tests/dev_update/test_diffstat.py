"""Tests for dev-update git diff-stat parsing."""

from __future__ import annotations

from sase.dev_update.diffstat import parse_git_numstat
from sase.dev_update.models import RepoDiffStat


def test_parse_git_numstat_sums_added_and_removed_lines() -> None:
    text = "10\t2\tsrc/sase/a.py\n3\t0\ttests/test_a.py\n"

    assert parse_git_numstat(text) == RepoDiffStat(
        files_changed=2,
        insertions=13,
        deletions=2,
    )


def test_parse_git_numstat_counts_binary_and_mode_only_files() -> None:
    text = "-\t-\tassets/logo.png\n0\t0\tscripts/run.sh\n"

    stat = parse_git_numstat(text)

    assert stat == RepoDiffStat(files_changed=2, insertions=0, deletions=0)
    assert stat is not None
    assert stat.has_line_changes is False
    assert stat.is_empty is False


def test_parse_git_numstat_handles_renames_and_empty_diff() -> None:
    assert parse_git_numstat("1\t2\tsrc/{old => new}.py\n") == RepoDiffStat(
        files_changed=1,
        insertions=1,
        deletions=2,
    )
    assert parse_git_numstat("") == RepoDiffStat(
        files_changed=0,
        insertions=0,
        deletions=0,
    )


def test_parse_git_numstat_rejects_malformed_rows() -> None:
    assert parse_git_numstat("1\t2\n") is None
    assert parse_git_numstat("one\t2\tpath.py\n") is None
    assert parse_git_numstat("-\t2\tpath.py\n") is None

"""Helpers for parsing git diff line statistics."""

from __future__ import annotations

from sase.dev_update.models import RepoDiffStat


def parse_git_numstat(text: str) -> RepoDiffStat | None:
    """Parse ``git diff --numstat`` output into aggregate repo stats."""
    files_changed = 0
    insertions = 0
    deletions = 0
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t", 2)
        if len(parts) != 3:
            return None
        added, removed, _path = parts
        if added == "-" and removed == "-":
            files_changed += 1
            continue
        if added == "-" or removed == "-":
            return None
        try:
            added_count = int(added)
            removed_count = int(removed)
        except ValueError:
            return None
        if added_count < 0 or removed_count < 0:
            return None
        files_changed += 1
        insertions += added_count
        deletions += removed_count
    return RepoDiffStat(
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )

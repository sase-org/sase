"""Utilities for extracting changed file paths from unified diffs."""

from __future__ import annotations

import shlex


def _normalize_diff_path(path: str) -> str | None:
    p = path.strip()
    if not p or p == "/dev/null":
        return None
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return p or None


def _split_diff_header(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def changed_files_from_diff(diff_text: str) -> list[str]:
    """Return sorted paths touched by a git/hg-style unified diff."""
    files: set[str] = set()

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = _split_diff_header(line)
            if len(parts) >= 4:
                candidate = _normalize_diff_path(parts[3])
                if candidate:
                    files.add(candidate)
            continue

        if line.startswith("diff -r "):
            parts = _split_diff_header(line)
            if len(parts) >= 4:
                candidate = _normalize_diff_path(parts[-1])
                if candidate:
                    files.add(candidate)
            continue

        if line.startswith("rename to "):
            candidate = _normalize_diff_path(line.removeprefix("rename to "))
            if candidate:
                files.add(candidate)
            continue

        if line.startswith("+++ "):
            candidate = _normalize_diff_path(line.removeprefix("+++ "))
            if candidate:
                files.add(candidate)
            continue

        if line.startswith("Index: "):
            candidate = _normalize_diff_path(line.removeprefix("Index: "))
            if candidate:
                files.add(candidate)

    return sorted(files)

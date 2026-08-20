"""Doctor helpers for committed Referenced By index files."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._git import run_sdd_git
from sase.sdd.referenced_by_index import (
    document_has_referenced_by_block,
    referenced_by_index_relpath,
)


def missing_referenced_by_indexes(repo_root: Path) -> tuple[str, ...]:
    """Return committed Markdown paths whose ``links/`` index is absent from HEAD.

    A document counts only when HEAD contains an unfenced managed
    ``Referenced By`` block. Fenced examples in design docs are ignored.
    """

    listed = _head_paths(repo_root)
    if listed is None:
        return ()
    missing: list[str] = []
    for relpath in _grep_block_candidates(repo_root):
        if relpath not in listed or not relpath.endswith(".md"):
            continue
        try:
            index_relpath = referenced_by_index_relpath(relpath)
        except ValueError:
            continue
        if index_relpath in listed:
            continue
        text = _head_text(repo_root, relpath)
        if text is None:
            continue
        if document_has_referenced_by_block(text):
            missing.append(relpath)
    return tuple(missing)


def _grep_block_candidates(repo_root: Path) -> tuple[str, ...]:
    result = run_sdd_git(
        [
            "grep",
            "-l",
            "--fixed-strings",
            "-e",
            "<!-- sase:referenced-by:start -->",
            "HEAD",
            "--",
            "*.md",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        op="sdd.referenced_by.head_grep",
    )
    if result.returncode not in {0, 1}:
        return ()
    candidates: list[str] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if line.startswith("HEAD:"):
            line = line[5:]
        if line:
            candidates.append(line)
    return tuple(sorted(candidates))


def _head_paths(repo_root: Path) -> frozenset[str] | None:
    result = run_sdd_git(
        ["ls-tree", "-r", "--name-only", "-z", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        op="sdd.referenced_by.head_paths",
    )
    if result.returncode != 0:
        return None
    return frozenset(path for path in result.stdout.split("\0") if path)


def _head_text(repo_root: Path, relpath: str) -> str | None:
    result = run_sdd_git(
        ["show", f"HEAD:{relpath}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        op="sdd.referenced_by.head_text",
    )
    if result.returncode != 0:
        return None
    return result.stdout


__all__ = ["missing_referenced_by_indexes"]

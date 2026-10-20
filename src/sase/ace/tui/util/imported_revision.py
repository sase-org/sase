"""Cheap imported git revision for TUI telemetry.

Read ``.git/HEAD`` and resolve the ref through a loose ref file or
``packed-refs``, following a ``.git`` file (worktrees) and ``commondir``.
No subprocess. The value is captured once at import so a long-running TUI
keeps reporting the snapshot it actually imported.
"""

from __future__ import annotations

from pathlib import Path

_snapshot: str | None = None
_taken = False


def _resolve_git_dir(root: Path) -> Path | None:
    """Return the git directory for *root*, following a worktree pointer."""
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        return None
    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "gitdir:"
    if not text.lower().startswith(prefix):
        return None
    raw = text[len(prefix) :].strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if path.is_dir() else None


def _common_dir(git_dir: Path) -> Path:
    """Return the shared git dir (worktree ``commondir``), else *git_dir*."""
    try:
        raw = (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return git_dir
    if not raw:
        return git_dir
    path = Path(raw)
    if not path.is_absolute():
        path = git_dir / path
    try:
        return path.resolve()
    except OSError:
        return git_dir


def _read_text(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _read_packed_ref(packed_refs: Path, ref_name: str) -> str | None:
    try:
        lines = packed_refs.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        sha, sep, name = line.partition(" ")
        if sep and name.strip() == ref_name:
            sha = sha.strip()
            if sha:
                return sha
    return None


def _read_git_head_sha(checkout: Path) -> str | None:
    """Return *checkout*'s HEAD SHA, or ``None`` when it is not a git tree."""
    git_dir = _resolve_git_dir(checkout)
    if git_dir is None:
        return None
    head = _read_text(git_dir / "HEAD")
    if head is None:
        return None
    if not head.startswith("ref:"):
        return head
    ref_name = head.removeprefix("ref:").strip()
    if not ref_name:
        return None
    common = _common_dir(git_dir)
    for base in (git_dir, common):
        sha = _read_text(base / ref_name)
        if sha is not None:
            return sha
        sha = _read_packed_ref(base / "packed-refs", ref_name)
        if sha is not None:
            return sha
    return None


def _sase_checkout_root() -> Path | None:
    """Return the git checkout ``sase`` was imported from, if any."""
    import sase

    source_file = getattr(sase, "__file__", None)
    if not source_file:
        return None
    try:
        root = Path(source_file).resolve().parents[2]
    except (IndexError, OSError):
        return None
    return root if (root / ".git").exists() else None


def imported_source_revision() -> str | None:
    """Return the SHA this process imported, captured once.

    ``None`` for a non-git install. Repeat calls never re-read the checkout,
    so a later ``sase dev update`` cannot change the recorded snapshot.
    """
    global _snapshot, _taken
    if not _taken:
        root = _sase_checkout_root()
        _snapshot = None if root is None else _read_git_head_sha(root)
        _taken = True
    return _snapshot


# Capture at import so the value is the snapshot this process loaded.
imported_source_revision()

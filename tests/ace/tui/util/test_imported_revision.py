"""Tests for the subprocess-free imported git revision reader."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.util.imported_revision import (
    _read_git_head_sha,
    imported_source_revision,
)


def test_read_head_sha_from_loose_ref(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text("abc123def456\n", encoding="utf-8")
    assert _read_git_head_sha(tmp_path) == "abc123def456"


def test_read_head_sha_from_packed_refs(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "deadbeef0001 refs/heads/other\n"
        "cafebabef00d refs/heads/topic\n",
        encoding="utf-8",
    )
    assert _read_git_head_sha(tmp_path) == "cafebabef00d"


def test_read_head_sha_detached(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text(
        "0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8"
    )
    assert _read_git_head_sha(tmp_path) == "0123456789abcdef0123456789abcdef01234567"


def test_read_head_sha_follows_worktree_gitdir(tmp_path: Path) -> None:
    real_git = tmp_path / "real.git"
    (real_git / "refs" / "heads").mkdir(parents=True)
    (real_git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (real_git / "refs" / "heads" / "main").write_text("aa11bb22\n", encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {real_git}\n", encoding="utf-8")
    assert _read_git_head_sha(worktree) == "aa11bb22"


def test_read_head_sha_uses_commondir_packed_refs(tmp_path: Path) -> None:
    common = tmp_path / "common.git"
    common.mkdir()
    (common / "packed-refs").write_text("ff00ff00 refs/heads/main\n", encoding="utf-8")
    worktree_git = tmp_path / "worktrees" / "wt"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (worktree_git / "commondir").write_text(str(common) + "\n", encoding="utf-8")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")
    assert _read_git_head_sha(checkout) == "ff00ff00"


def test_non_git_checkout_returns_none(tmp_path: Path) -> None:
    assert _read_git_head_sha(tmp_path) is None


def test_imported_source_revision_is_stable() -> None:
    first = imported_source_revision()
    second = imported_source_revision()
    assert first == second
    assert first is None or (isinstance(first, str) and first)

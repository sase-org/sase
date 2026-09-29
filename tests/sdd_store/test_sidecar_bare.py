"""Bare partial clone coverage for the ``attachments-private`` sidecar role."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.sdd._sidecar_bare import (
    ATTACHMENTS_INIT_COMMIT_MESSAGE,
    ensure_attachments_private_bare_clone,
    is_bare_sidecar_clone,
)
from sase.sdd._store_types import SddMaterializationError


def _init_bare_remote(path: Path) -> None:
    subprocess.run(
        ["git", "init", "--bare", "-q", str(path)],
        check=True,
    )
    subprocess.run(
        ["git", "--git-dir", str(path), "config", "uploadpack.allowFilter", "true"],
        check=True,
    )


def _git_count(remote: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--git-dir", str(remote), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_bare_clone_reserves_store_with_pushed_root_commit(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    _init_bare_remote(remote)
    clone = tmp_path / "hidden" / "repos" / "attachments-private"

    ensure_attachments_private_bare_clone(clone, str(remote))

    assert is_bare_sidecar_clone(clone)
    assert not (clone / ".git").exists()
    head = _git_count(clone, "rev-parse", "HEAD")
    assert head
    message = _git_count(clone, "log", "-1", "--format=%s")
    assert message == ATTACHMENTS_INIT_COMMIT_MESSAGE
    # The init commit carries an empty tree: no filenames, no content.
    assert _git_count(clone, "show", "--name-only", "--format=", head) == ""
    # The init commit reached the remote.
    assert _git_count(remote, "rev-parse", "HEAD") == head

    # A second ensure converges without a new commit.
    ensure_attachments_private_bare_clone(clone, str(remote))
    assert _git_count(remote, "rev-list", "--count", "HEAD") == "1"
    assert _git_count(clone, "rev-parse", "HEAD") == head


def test_bare_clone_is_predicate_only_for_bare_layouts(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    subprocess.run(["git", "init", "-q", str(worktree)], check=True)
    assert not is_bare_sidecar_clone(worktree)
    assert not is_bare_sidecar_clone(tmp_path / "missing")


def test_bare_clone_refuses_non_bare_destination(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    _init_bare_remote(remote)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("user content", encoding="utf-8")

    with pytest.raises(SddMaterializationError, match="not a bare repository"):
        ensure_attachments_private_bare_clone(occupied, str(remote))


def test_bare_clone_refuses_origin_mismatch(tmp_path: Path) -> None:
    first = tmp_path / "first.git"
    second = tmp_path / "second.git"
    _init_bare_remote(first)
    _init_bare_remote(second)
    clone = tmp_path / "clone"

    ensure_attachments_private_bare_clone(clone, str(first))

    with pytest.raises(SddMaterializationError, match="has origin"):
        ensure_attachments_private_bare_clone(clone, str(second))

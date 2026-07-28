"""Repository resolution coverage for ACE scoped bead-store commits."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sase.ace.tui.actions.artifacts_plans import _commit_scoped_bead_store
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    BEADS_DIRNAME_ROOT,
    BeadProject,
)

_GIT_AVAILABLE = shutil.which("git") is not None


def _git(repo: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "tester@example.com")
    _git(repo, "config", "user.name", "Tester")


def _make_store(root: Path, beads_dirname: str) -> Path:
    with BeadProject.init(root, beads_dirname=beads_dirname):
        pass
    if beads_dirname == BEADS_DIRNAME_ROOT:
        return root
    return root / beads_dirname


def _committed_paths(repo: Path) -> list[str]:
    return _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.splitlines()


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_commit_scoped_bead_store_commits_root_layout_beads_clone(
    tmp_path: Path,
) -> None:
    """A dedicated beads sidecar is its own repository root."""
    clone = tmp_path / "sase" / "repos" / "beads"
    _init_repo(clone)
    beads_dir = _make_store(clone, BEADS_DIRNAME_ROOT)

    _commit_scoped_bead_store(beads_dir, "chore(beads): update sase-1")

    assert _git(clone, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(beads): update sase-1"
    )
    assert _committed_paths(clone)


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_commit_scoped_bead_store_commits_legacy_plans_embedded_layout(
    tmp_path: Path,
) -> None:
    """A `<plans clone>/beads` store still commits in the plans clone."""
    clone = tmp_path / "sase" / "repos" / "plans"
    _init_repo(clone)
    (clone / "202607").mkdir()
    (clone / "202607" / "note.md").write_text("plan\n", encoding="utf-8")
    beads_dir = _make_store(clone, BEADS_DIRNAME_NON_VC)

    _commit_scoped_bead_store(beads_dir, "chore(beads): update sase-1")

    assert _git(clone, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(beads): update sase-1"
    )
    committed = _committed_paths(clone)
    assert committed
    # The commit stays scoped to bead state, so the untracked plan is left alone.
    assert all(path.startswith("beads/") for path in committed)


def test_commit_scoped_bead_store_skips_store_without_git_root(tmp_path: Path) -> None:
    """An in-tree store with no owning repository is left to its code change."""
    beads_dir = _make_store(tmp_path, BEADS_DIRNAME)

    _commit_scoped_bead_store(beads_dir, "chore(beads): update sase-1")

    assert not (tmp_path / ".git").exists()

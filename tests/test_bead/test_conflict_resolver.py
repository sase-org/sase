"""Tests for bead conflict resolver command behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.bead.conflict_resolver import resolve_bead_conflicts


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--initial-branch=master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def test_resolve_bead_conflicts_noops_without_conflicts(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True
    assert result.message == "no conflicted bead files"


def test_resolve_bead_conflicts_rejects_nonmergeable_bead_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config = tmp_path / "sdd/beads/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"owner":"base"}\n', encoding="utf-8")
    _git(tmp_path, "add", "sdd/beads/config.json")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    config.write_text('{"owner":"other"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    config.write_text('{"owner":"local"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "unsupported bead conflicts: sdd/beads/config.json"


def test_resolve_bead_conflicts_rejects_only_non_bead_conflicts(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "sdd/beads").mkdir(parents=True)
    notes = tmp_path / "notes.txt"
    notes.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "notes.txt")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    notes.write_text("other\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    notes.write_text("local\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: notes.txt"

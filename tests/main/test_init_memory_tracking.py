"""Tracking guarantees: untracked/ignored managed files fail --check."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.main.init_memory.tracking import (
    tracking_blockers_for_root,
    verify_publish_guard_for_root,
)


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
    )


def _init_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")


def _managed_memory_note() -> str:
    return "---\ntype: reference\nparent: AGENTS.md\ndescription: Fixture.\n---\n# Fixture\n"


def test_untracked_managed_memory_file_is_a_check_blocker(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "sase" / "memory").mkdir(parents=True)
    project.mkdir(exist_ok=True)
    _init_repo(project)
    note = project / "sase" / "memory" / "extra.md"
    note.write_text(_managed_memory_note(), encoding="utf-8")
    (project / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    _git(project, "add", "AGENTS.md")
    _git(project, "commit", "-m", "init", "--no-gpg-sign")

    blockers = tracking_blockers_for_root(project)

    assert any("UNTRACKED" in blocker and "extra.md" in blocker for blocker in blockers)


def test_ignored_managed_memory_file_is_a_check_blocker(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "sase" / "memory").mkdir(parents=True)
    project.mkdir(exist_ok=True)
    _init_repo(project)
    note = project / "sase" / "memory" / "extra.md"
    note.write_text(_managed_memory_note(), encoding="utf-8")
    (project / ".gitignore").write_text("sase/memory/extra.md\n", encoding="utf-8")
    (project / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    _git(project, "add", "AGENTS.md", ".gitignore")
    _git(project, "commit", "-m", "init", "--no-gpg-sign")

    blockers = tracking_blockers_for_root(project)

    assert any("IGNORED" in blocker and "extra.md" in blocker for blocker in blockers)


def test_publish_guard_triggers_for_ignored_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "sase" / "memory").mkdir(parents=True)
    project.mkdir(exist_ok=True)
    _init_repo(project)
    note = project / "sase" / "memory" / "extra.md"
    note.write_text(_managed_memory_note(), encoding="utf-8")
    (project / ".gitignore").write_text("sase/memory/extra.md\n", encoding="utf-8")
    (project / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    _git(project, "add", "AGENTS.md", ".gitignore")
    _git(project, "commit", "-m", "init", "--no-gpg-sign")

    problems = verify_publish_guard_for_root(project)

    assert any("extra.md" in problem and "ignored" in problem for problem in problems)

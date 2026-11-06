"""Worktree recovery snapshot wrap and monitor-path compatibility."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from sase.monitor.worktree_recovery import (
    WORKTREE_RECOVERY_DIFF_FIELD,
    WORKTREE_RECOVERY_DIFF_LOCATOR,
    snapshot_owner_worktree_diffs,
    snapshot_worktree_recovery_diff,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_dirty_repo(path: Path, contents: str) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "sase-test@example.invalid")
    _git(path, "config", "user.name", "SASE Test")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "init")
    (path / "tracked.txt").write_text(contents, encoding="utf-8")
    (path / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    return path


def test_monitor_snapshot_keeps_historical_path(tmp_path: Path) -> None:
    workspace = _init_dirty_repo(tmp_path / "monitor-ws", "dirty tracked\n")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    meta: dict[str, Any] = {"monitor_cwd": str(workspace)}

    snapshot = snapshot_worktree_recovery_diff(str(artifacts), meta)

    expected = artifacts / WORKTREE_RECOVERY_DIFF_LOCATOR
    assert snapshot == str(expected)
    assert expected.is_file()
    text = expected.read_text(encoding="utf-8")
    assert "dirty tracked" in text
    assert "untracked" in text
    assert meta[WORKTREE_RECOVERY_DIFF_FIELD] == str(expected)
    again = snapshot_worktree_recovery_diff(str(artifacts), meta)
    assert again == snapshot


def test_owner_snapshots_disambiguate_shared_repo_ids(tmp_path: Path) -> None:
    first = _init_dirty_repo(tmp_path / "first", "first dirty\n")
    second = _init_dirty_repo(tmp_path / "second", "second dirty\n")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    paths = snapshot_owner_worktree_diffs(
        str(artifacts),
        (("sibling:plans", str(first)), ("sibling:plans", str(second))),
    )

    assert len(paths) == 2
    assert paths[0] != paths[1]
    assert Path(paths[0]).is_file()
    assert Path(paths[1]).is_file()
    assert "first dirty" in Path(paths[0]).read_text(encoding="utf-8")
    assert "second dirty" in Path(paths[1]).read_text(encoding="utf-8")


def test_owner_snapshots_cover_linked_checkouts(tmp_path: Path) -> None:
    primary = _init_dirty_repo(tmp_path / "primary", "primary dirty\n")
    linked = _init_dirty_repo(tmp_path / "linked", "linked dirty\n")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    paths = snapshot_owner_worktree_diffs(
        str(artifacts),
        (("primary", str(primary)), ("linked", str(linked))),
        primary_locator=WORKTREE_RECOVERY_DIFF_LOCATOR,
    )

    assert len(paths) == 2
    assert Path(paths[0]) == artifacts / WORKTREE_RECOVERY_DIFF_LOCATOR
    assert Path(paths[1]).parent.name == "worktree_recovery"
    assert "primary dirty" in Path(paths[0]).read_text(encoding="utf-8")
    assert "linked dirty" in Path(paths[1]).read_text(encoding="utf-8")

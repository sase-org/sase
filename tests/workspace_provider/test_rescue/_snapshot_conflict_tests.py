from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider.snapshot import PreservationError, restore_git_snapshot
from tests.workspace_provider.test_rescue._helpers import (
    commit_file,
    git,
    redirect_state,
    seed_remote_clone,
)
from tests.workspace_provider.test_rescue._snapshot_helpers import (
    assert_source_unchanged,
    head,
    ls_stage,
    restore_dest,
    snapshot,
    source_probe,
)


def _stage_lines(repo: Path, rel: str) -> list[str]:
    return [
        line
        for line in git(repo, "ls-files", "--stage", "--", rel).stdout.splitlines()
        if line
    ]


def _stage_numbers(repo: Path, rel: str) -> set[int]:
    numbers: set[int] = set()
    for line in _stage_lines(repo, rel):
        numbers.add(int(line.split()[2]))
    return numbers


def _write_delete_modify_conflict(clone: Path, *, deleted_on: str) -> bytes:
    """Create a real-Git DU/UD conflict and overwrite it with unique bytes."""
    commit_file(clone, "conflict.txt", "base\n", "base conflict")
    git(clone, "checkout", "-b", "theirs")
    commit_file(clone, "conflict.txt", "theirs\n", "theirs change")
    git(clone, "checkout", "-q", "main")
    if deleted_on == "ours":
        git(clone, "rm", "--", "conflict.txt")
        git(clone, "commit", "-m", "delete on main")
    else:
        commit_file(clone, "conflict.txt", "ours\n", "ours change")
        git(clone, "checkout", "-q", "theirs")
        git(clone, "rm", "--", "conflict.txt")
        git(clone, "commit", "-m", "delete on theirs")
        git(clone, "checkout", "-q", "main")
    merge = subprocess.run(
        ["git", "merge", "theirs"],
        cwd=clone,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
    unique = b"unique manual conflict edits\n"
    (clone / "conflict.txt").write_bytes(unique)
    return unique


def _write_both_added_conflict(clone: Path) -> bytes:
    git(clone, "checkout", "-b", "theirs")
    commit_file(clone, "added.txt", "theirs-add\n", "theirs add")
    git(clone, "checkout", "-q", "main")
    commit_file(clone, "added.txt", "ours-add\n", "ours add")
    merge = subprocess.run(
        ["git", "merge", "theirs"],
        cwd=clone,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
    unique = b"unique both-added conflict edits\n"
    (clone / "added.txt").write_bytes(unique)
    return unique


def test_snapshot_restores_conflict_stages_and_worktree_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "file.txt", "base\n", "base file")
    git(clone, "checkout", "-b", "feature")
    commit_file(clone, "file.txt", "feature\n", "feature change")
    git(clone, "checkout", "-q", "main")
    commit_file(clone, "file.txt", "main\n", "main change")
    merge = subprocess.run(
        ["git", "merge", "feature"],
        cwd=clone,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
    conflict_bytes = (clone / "file.txt").read_bytes()
    stage_before = ls_stage(clone)
    assert "file.txt" in stage_before
    before = source_probe(clone)
    git_dir = Path(git(clone, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (git_dir / "MERGE_HEAD").is_file()

    record = snapshot(clone, workspace, reason="conflict")
    assert record is not None
    assert record.unmerged is True
    assert_source_unchanged(clone, before)

    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "file.txt").read_bytes() == conflict_bytes
    dest_stage = git(dest, "ls-files", "--stage", "--", "file.txt").stdout
    src_stage = git(clone, "ls-files", "--stage", "--", "file.txt").stdout
    assert dest_stage == src_stage
    dest_git = Path(git(dest, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (dest_git / "MERGE_HEAD").is_file()


@pytest.mark.parametrize(
    ("kind", "rel", "expected_stages"),
    [
        ("du", "conflict.txt", {1, 3}),
        ("ud", "conflict.txt", {1, 2}),
        ("aa", "added.txt", {2, 3}),
    ],
)
def test_snapshot_restores_delete_modify_and_add_conflict_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    rel: str,
    expected_stages: set[int],
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    if kind == "du":
        unique = _write_delete_modify_conflict(clone, deleted_on="ours")
    elif kind == "ud":
        unique = _write_delete_modify_conflict(clone, deleted_on="theirs")
    else:
        unique = _write_both_added_conflict(clone)
    src_stage = _stage_lines(clone, rel)
    assert _stage_numbers(clone, rel) == expected_stages
    before = source_probe(clone)
    git_dir = Path(git(clone, "rev-parse", "--absolute-git-dir").stdout.strip())
    merge_head = (git_dir / "MERGE_HEAD").is_file()

    record = snapshot(clone, workspace, reason=f"conflict-{kind}")
    assert record is not None
    assert record.unmerged is True
    assert_source_unchanged(clone, before)

    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / rel).read_bytes() == unique
    assert _stage_lines(dest, rel) == src_stage
    dest_git = Path(git(dest, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (dest_git / "MERGE_HEAD").is_file() is merge_head

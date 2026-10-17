"""Worktree patch, conflict, cap, and worktree-only rescue tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider import _rescue_git_worktree as rescue_worktree_module
from sase.workspace_provider.rescue import rescue_git_repo
from tests.workspace_provider.test_rescue._helpers import (
    commit_file,
    git,
    redirect_state,
    rescue_tmp_refs,
    seed_clone_with_off_branch_tag,
    seed_remote_clone,
)


def test_rescue_patch_captures_staged_unstaged_and_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "tracked.txt", "base\n", "tracked base")
    git(clone, "push")
    (clone / "tracked.txt").write_text("staged-plus-unstaged\n", encoding="utf-8")
    git(clone, "add", "--", "tracked.txt")
    (clone / "tracked.txt").write_text("staged-plus-unstaged\nmore\n", encoding="utf-8")
    (clone / "new.txt").write_text("untracked\n", encoding="utf-8")
    staged_before = git(clone, "diff", "--cached", "--name-only").stdout

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="patch rescue",
        include_worktree=True,
    )

    assert record is not None and record.patch_path is not None
    patch = record.patch_path.read_text(encoding="utf-8")
    assert "more" in patch
    assert "new.txt" in patch
    # The real index is untouched: rescue staged into a temporary index.
    assert git(clone, "diff", "--cached", "--name-only").stdout == staged_before
    # The patch applies cleanly against a fresh checkout of the base.
    applier = tmp_path / "applier"
    subprocess.run(
        ["git", "clone", str(clone), str(applier)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(applier, "checkout", "-q", "HEAD", "--", ".")
    assert (
        subprocess.run(
            ["git", "apply", "--check", str(record.patch_path)],
            cwd=applier,
            capture_output=True,
        ).returncode
        == 0
    )


def test_rescue_patch_captures_conflicted_worktree(
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

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="conflict rescue",
        include_worktree=True,
    )

    assert record is not None
    assert record.bundle_path is not None
    assert record.patch_path is not None
    assert record.patch_path.stat().st_size > 0
    manifest = json.loads((record.rescue_dir / "manifest.json").read_text())
    assert "MERGE_HEAD" in manifest["operation_markers"]
    assert "UU file.txt" in manifest["status_porcelain"]


def test_worktree_only_rescue_writes_no_tag_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_clone_with_off_branch_tag(tmp_path)
    (clone / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="worktree only",
        include_worktree=True,
    )

    assert record is not None
    assert record.patch_path is not None
    assert record.bundle_path is None
    assert len(notified) == 1
    notes = notified[0][3]
    assert any("worktree changes" in note for note in notes)
    assert all("local commits" not in note for note in notes)
    assert rescue_tmp_refs(clone) == ""


def test_rescue_patch_cap_is_honored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    local_sha = commit_file(clone, "local.txt", "local\n", "unpushed work")
    (clone / "big.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setattr(rescue_worktree_module, "RESCUE_PATCH_MAX_BYTES", 4)

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="cap",
        include_worktree=True,
    )

    assert record is not None
    assert record.patch_path is None
    assert record.bundle_path is not None
    assert record.note is not None and "cap" in record.note
    manifest = json.loads((record.rescue_dir / "manifest.json").read_text())
    assert "patch_note" in manifest
    assert manifest["head"] == local_sha

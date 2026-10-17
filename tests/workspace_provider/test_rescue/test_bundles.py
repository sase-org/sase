"""Bundle tests for local commits, stash entries, and offline repos."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider.rescue import rescue_git_repo
from tests.workspace_provider.test_rescue._helpers import (
    bundle_lists_sha,
    clone_and_fetch,
    commit_file,
    git,
    holds_object,
    init_repo,
    redirect_state,
    seed_remote_clone,
)


def test_rescue_bundles_local_commits_restorable_by_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    local_sha = commit_file(clone, "local.txt", "local\n", "unpushed work")

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="test rescue",
        include_worktree=False,
    )

    assert record is not None
    assert record.bundle_path is not None and record.bundle_path.is_file()
    assert record.patch_path is None
    assert record.rescue_dir.parent.parent == home / "rescue"
    assert workspace not in record.rescue_dir.parents
    assert (record.rescue_dir / "manifest.json").is_file()
    manifest = json.loads((record.rescue_dir / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["workspace_num"] == 7
    assert manifest["label"] == "plans"
    assert manifest["reason"] == "test rescue"
    assert manifest["head"] == local_sha
    assert manifest["branch"] == "main"
    assert "bundle" in manifest["restore"]

    assert bundle_lists_sha(record.bundle_path, local_sha)
    fresh = clone_and_fetch(
        record.bundle_path, tmp_path / "origin.git", tmp_path / "fresh"
    )
    fetched = git(fresh, "rev-parse", "refs/sase/rescued/x/heads/main").stdout.strip()
    assert fetched == local_sha

    assert len(notified) == 1
    sender, _cl, _ok, notes, kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert any(str(record.rescue_dir) in note for note in notes)
    assert kwargs["extra_files"] == [str(record.rescue_dir)]


def test_rescue_includes_every_stash_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "tracked.txt", "v1\n", "tracked base")
    git(clone, "push")
    (clone / "tracked.txt").write_text("stash-one\n", encoding="utf-8")
    git(clone, "stash", "push", "-m", "one")
    (clone / "tracked.txt").write_text("stash-two\n", encoding="utf-8")
    git(clone, "stash", "push", "-m", "two")
    stash_shas = [
        line.strip()
        for line in git(clone, "stash", "list", "--format=%H").stdout.splitlines()
        if line.strip()
    ]
    assert len(stash_shas) == 2

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="stash rescue",
        include_worktree=True,
    )

    assert record is not None and record.bundle_path is not None
    # Temporary stash refs are cleaned up afterwards.
    assert (
        git(
            clone, "for-each-ref", "--format=%(refname)", "refs/sase/rescue-tmp"
        ).stdout.strip()
        == ""
    )
    for sha in stash_shas:
        assert bundle_lists_sha(record.bundle_path, sha)
    fresh = clone_and_fetch(
        record.bundle_path, tmp_path / "origin.git", tmp_path / "fresh"
    )
    for sha in stash_shas:
        assert holds_object(fresh, sha)


def test_rescue_bundles_everything_without_remote_tracking_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "project_7"
    repo = workspace / "sase" / "repos" / "plans"
    init_repo(repo)
    sha = commit_file(repo, "solo.txt", "solo\n", "offline work")
    git(repo, "tag", "-a", "v-offline", "-m", "offline release")

    record = rescue_git_repo(
        repo,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="offline",
        include_worktree=False,
    )

    assert record is not None and record.bundle_path is not None
    assert bundle_lists_sha(record.bundle_path, sha)
    heads = subprocess.run(
        ["git", "bundle", "list-heads", str(record.bundle_path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "refs/tags/v-offline" in heads
    fresh = clone_and_fetch(record.bundle_path, repo, tmp_path / "fresh")
    assert holds_object(fresh, sha)

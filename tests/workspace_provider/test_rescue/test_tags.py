"""Tag and detached-HEAD rescue tests."""

from __future__ import annotations

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
    redirect_state,
    rescue_entries,
    rescue_tmp_refs,
    seed_clone_with_off_branch_tag,
    seed_remote_clone,
)


def test_rescue_ignores_annotated_tags_already_on_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    git(clone, "tag", "-a", "v1.0", "-m", "release 1.0")
    git(clone, "tag", "-a", "v2.0", "-m", "release 2.0")
    git(clone, "tag", "v-light")
    git(clone, "push", "origin", "--tags")

    assert (
        rescue_git_repo(
            clone,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="pushed tags",
            include_worktree=True,
        )
        is None
    )
    assert rescue_entries(home) == []
    assert notified == []


def test_rescue_bundles_local_tags_but_not_published_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    git(clone, "tag", "-a", "v-pushed", "-m", "pushed release")
    git(clone, "push", "origin", "--tags")
    local_sha = commit_file(clone, "local.txt", "local\n", "unpushed work")
    git(clone, "tag", "-a", "v-local", "-m", "local release")

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="mixed tags",
        include_worktree=True,
    )

    assert record is not None and record.bundle_path is not None
    heads = subprocess.run(
        ["git", "bundle", "list-heads", str(record.bundle_path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "refs/heads/main" in heads
    assert "refs/tags/v-local" in heads
    assert "refs/tags/v-pushed" not in heads
    fresh = clone_and_fetch(record.bundle_path, clone, tmp_path / "fresh")
    peeled = git(
        fresh, "rev-parse", "refs/sase/rescued/x/tags/v-local^{commit}"
    ).stdout.strip()
    assert peeled == local_sha


def test_rescue_ignores_upstream_tags_off_every_remote_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_clone_with_off_branch_tag(tmp_path)

    assert (
        rescue_git_repo(
            clone,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="upstream off-branch tag",
            include_worktree=True,
        )
        is None
    )
    assert rescue_entries(home) == []
    assert notified == []
    assert rescue_tmp_refs(clone) == ""


def test_rescue_bundle_omits_upstream_off_branch_tags_when_rescuing_branch_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_clone_with_off_branch_tag(tmp_path, "v-upstream")
    local_sha = commit_file(clone, "local.txt", "local\n", "unpushed work")
    git(clone, "tag", "-a", "v-local", "-m", "local release")

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="branch work plus off-branch tag",
        include_worktree=True,
    )

    assert record is not None and record.bundle_path is not None
    heads = subprocess.run(
        ["git", "bundle", "list-heads", str(record.bundle_path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "refs/heads/main" in heads
    assert "refs/tags/v-local" in heads
    assert "refs/tags/v-upstream" not in heads
    fresh = clone_and_fetch(record.bundle_path, clone, tmp_path / "fresh")
    peeled = git(
        fresh, "rev-parse", "refs/sase/rescued/x/tags/v-local^{commit}"
    ).stdout.strip()
    assert peeled == local_sha
    assert rescue_tmp_refs(clone) == ""


def test_rescue_ignores_detached_checkout_of_upstream_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_clone_with_off_branch_tag(tmp_path)
    git(clone, "checkout", "v1.0")

    assert (
        rescue_git_repo(
            clone,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="detached tag",
            include_worktree=True,
        )
        is None
    )
    assert rescue_entries(home) == []
    assert notified == []
    assert rescue_tmp_refs(clone) == ""


def test_rescue_bundles_new_commit_on_detached_upstream_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_clone_with_off_branch_tag(tmp_path)
    git(clone, "checkout", "v1.0")
    orphan_sha = commit_file(clone, "orphan.txt", "orphan\n", "detached work")

    record = rescue_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="detached work",
        include_worktree=True,
    )

    assert record is not None and record.bundle_path is not None
    assert bundle_lists_sha(record.bundle_path, orphan_sha)
    fresh = clone_and_fetch(record.bundle_path, clone, tmp_path / "fresh")
    assert holds_object(fresh, orphan_sha)
    assert rescue_tmp_refs(clone) == ""

"""Linked and external repo clones are rescued before workspace eviction."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sase.axe.runner_workspace import prepare_launch_workspace_repos
from sase.axe.runner_workspace_protection import rescue_repo_clones_before_eviction
from sase.workspace_provider import _utils_checkout


WORKSPACE_NUM = 7


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _seed_remote_clone(tmp_path: Path, clone: Path) -> tuple[Path, Path]:
    remote = tmp_path / f"{clone.name}-origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / f"{clone.name}-seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "commit.gpgsign", "false")
    (seed / "base.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "base.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    clone.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "config", "commit.gpgsign", "false")
    return clone, remote


def _commit_file(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _redirect_rescue_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[object, ...]]]:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    notified: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )
    return home, notified


def _rescue_entries(home: Path) -> list[Path]:
    return sorted(path.parent for path in home.rglob("manifest.json"))


def _configure_launch(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> None:
    monkeypatch.setattr(
        "sase.axe.runner_workspace_protection.protect_unpushed_sidecar_commits",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.sdd._paths.get_primary_workspace_dir", lambda *_args: str(workspace)
    )
    monkeypatch.setattr(
        "sase.sdd._store_records.is_materialized_record", lambda _r: False
    )
    monkeypatch.setattr(
        "sase.sdd._store_records.read_sdd_store_record", lambda _p: None
    )
    monkeypatch.setattr("sase.sdd.store.auto_connect_sdd_store", lambda *_args: False)
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_a, **_k: None
    )


def test_launch_rescues_unpushed_linked_commit_then_evicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    clone = workspace / "sase" / "repos" / "linked" / "tooling"
    _seed_remote_clone(tmp_path, clone)
    local_sha = _commit_file(clone, "local.txt", "local work\n", "local work")
    home, notified = _redirect_rescue_state(tmp_path, monkeypatch)
    _configure_launch(monkeypatch, workspace)

    prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM)

    assert not (workspace / "sase" / "repos").exists()
    entries = _rescue_entries(home)
    assert len(entries) == 1
    manifest = json.loads((entries[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["label"] == "linked-tooling"
    bundle = entries[0] / "local-commits.bundle"
    assert (
        local_sha
        in subprocess.run(
            ["git", "bundle", "list-heads", str(bundle)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert len(notified) == 1


def test_rescues_linked_worktree_changes_and_nested_external_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    linked, _ = _seed_remote_clone(
        tmp_path, workspace / "sase" / "repos" / "linked" / "tooling"
    )
    (linked / "base.txt").write_text("modified\n", encoding="utf-8")
    (linked / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    external, _ = _seed_remote_clone(
        tmp_path,
        workspace / "sase" / "repos" / "external" / "gh" / "owner" / "repo",
    )
    _commit_file(external, "external.txt", "external work\n", "external work")
    home, _notified = _redirect_rescue_state(tmp_path, monkeypatch)

    rescue_repo_clones_before_eviction(workspace, WORKSPACE_NUM)

    entries = _rescue_entries(home)
    manifests = {
        entry: json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
        for entry in entries
    }
    linked_entry = next(
        entry
        for entry, manifest in manifests.items()
        if manifest["label"] == "linked-tooling"
    )
    linked_manifest = manifests[linked_entry]
    patch = (linked_entry / "worktree.patch").read_text(encoding="utf-8")
    assert linked_manifest["label"] == "linked-tooling"
    assert "modified" in patch
    assert "untracked" in patch
    assert any(
        manifest["label"].startswith("external-gh-owner-repo")
        for manifest in manifests.values()
    )


def test_clean_fully_pushed_linked_clone_needs_no_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    _seed_remote_clone(tmp_path, workspace / "sase" / "repos" / "linked" / "tooling")
    home, _notified = _redirect_rescue_state(tmp_path, monkeypatch)

    rescue_repo_clones_before_eviction(workspace, WORKSPACE_NUM)

    assert _rescue_entries(home) == []


def test_linked_clone_with_only_pushed_release_tags_needs_no_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    clone, _remote = _seed_remote_clone(
        tmp_path, workspace / "sase" / "repos" / "linked" / "tooling"
    )
    _git(clone, "tag", "-a", "v1.0", "-m", "release 1.0")
    _git(clone, "tag", "-a", "v2.0", "-m", "release 2.0")
    _git(clone, "push", "origin", "--tags")
    home, notified = _redirect_rescue_state(tmp_path, monkeypatch)

    rescue_repo_clones_before_eviction(workspace, WORKSPACE_NUM)

    assert _rescue_entries(home) == []
    assert notified == []


def test_external_clone_with_only_upstream_off_branch_tag_needs_no_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    clone, remote = _seed_remote_clone(
        tmp_path,
        workspace / "sase" / "repos" / "external" / "gh" / "owner" / "repo",
    )
    work = tmp_path / "off-branch-tag-work"
    subprocess.run(
        ["git", "clone", str(remote), str(work)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "config", "commit.gpgsign", "false")
    _git(work, "checkout", "-b", "tmp-release")
    _commit_file(work, "release.txt", "off-branch\n", "release bump")
    _git(work, "tag", "-a", "v1.0", "-m", "release 1.0")
    _git(work, "push", "origin", "refs/tags/v1.0")
    shutil.rmtree(clone)
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    home, notified = _redirect_rescue_state(tmp_path, monkeypatch)

    rescue_repo_clones_before_eviction(workspace, WORKSPACE_NUM)

    assert _rescue_entries(home) == []
    assert notified == []


@pytest.mark.parametrize("failure", ["raise", "none"])
def test_launch_evicts_even_when_clone_rescue_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    workspace = tmp_path / "workspace"
    clone = workspace / "sase" / "repos" / "linked" / "tooling"
    _seed_remote_clone(tmp_path, clone)
    _commit_file(clone, "local.txt", "local work\n", "local work")
    _redirect_rescue_state(tmp_path, monkeypatch)
    _configure_launch(monkeypatch, workspace)

    def fail_or_skip(*_args: object, **_kwargs: object) -> None:
        if failure == "raise":
            raise RuntimeError("rescue unavailable")
        return None

    monkeypatch.setattr("sase.workspace_provider.rescue.rescue_git_repo", fail_or_skip)

    prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM)

    assert not (workspace / "sase" / "repos").exists()


@pytest.mark.parametrize("eviction", ["corrupt", "recreate"])
def test_checkout_replacement_rescues_linked_clones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eviction: str,
) -> None:
    workspace = tmp_path / "workspace"
    clone = workspace / "sase" / "repos" / "linked" / "tooling"
    _seed_remote_clone(tmp_path, clone)
    local_sha = _commit_file(clone, "local.txt", "local work\n", "local work")
    home, _notified = _redirect_rescue_state(tmp_path, monkeypatch)

    if eviction == "corrupt":
        monkeypatch.setattr(
            "sase._linked_repo_workspaces.move_aside_for_background_delete",
            lambda *_args, **_kwargs: None,
        )
        _utils_checkout._remove_corrupt_checkout(str(workspace), WORKSPACE_NUM)
    else:
        _git(workspace, "init", "-b", "main")
        _git(workspace, "config", "user.email", "test@example.com")
        _git(workspace, "config", "user.name", "Test")
        _git(workspace, "config", "commit.gpgsign", "false")
        (workspace / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
        _git(workspace, "add", ".gitignore")
        _git(workspace, "commit", "-m", "ignore nested repos")
        monkeypatch.setattr(
            "sase.axe.runner_workspace_prepare.rescue_sidecars_before_eviction",
            lambda *_args, **_kwargs: True,
        )
        monkeypatch.setattr(
            "sase._linked_repo_workspaces.move_aside_for_background_delete",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            _utils_checkout,
            "ensure_workspace_checkout",
            lambda *_args, **_kwargs: "fresh",
        )
        monkeypatch.setattr(
            "sase.sdd._paths.get_primary_workspace_dir", lambda *_args: str(workspace)
        )
        assert (
            _utils_checkout.recreate_managed_workspace(str(workspace), WORKSPACE_NUM)
            == "fresh"
        )

    entries = _rescue_entries(home)
    bundles = [
        entry / "local-commits.bundle"
        for entry in entries
        if (entry / "local-commits.bundle").is_file()
    ]
    assert bundles
    bundle_text = "\n".join(
        subprocess.run(
            ["git", "bundle", "list-heads", str(bundle)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for bundle in bundles
    )
    assert local_sha in bundle_text

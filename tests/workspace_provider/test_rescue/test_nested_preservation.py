"""Strict nested-repository preservation before destructive removal."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sase.axe.runner_workspace_errors import WorkspacePreparationError
from sase.axe.runner_workspace_protection import prepare_launch_workspace_repos
from sase.workspace_provider import _snapshot_capture_payload as payload_module
from sase.workspace_provider._snapshot_nested import discover_nested_git_repos
from sase.workspace_provider.snapshot import (
    NestedPreservationError,
    PreservationError,
    preserve_nested_repositories,
    restore_git_snapshot,
)
from sase.workspace_provider.utils import recreate_managed_workspace
from tests.workspace_provider.test_rescue._helpers import (
    commit_file,
    git,
    init_repo,
    redirect_state,
    rescue_entries,
)


WORKSPACE_NUM = 7


def _clone(origin: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(dest, "config", "user.email", "test@test.com")
    git(dest, "config", "user.name", "Test")
    git(dest, "config", "commit.gpgsign", "false")
    return dest


def _seed_origin(path: Path, text: str) -> Path:
    init_repo(path)
    commit_file(path, "tracked.txt", text, "tracked")
    return path


def _seed_large_published_origin(tmp_path: Path) -> Path:
    remote = tmp_path / "large-origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = _seed_origin(tmp_path / "large-seed", "base tracked\n")
    (seed / "large.bin").write_bytes(b"published large content\n" * 12_000)
    git(seed, "add", "--", "large.bin")
    git(seed, "commit", "-m", "large published file")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    return remote


def _dirty_nested(origin: Path, dest: Path, name: str) -> Path:
    _clone(origin, dest)
    git(dest, "add", "--", "tracked.txt")
    (dest / "tracked.txt").write_text(f"{name}-staged\n", encoding="utf-8")
    git(dest, "add", "--", "tracked.txt")
    (dest / "tracked.txt").write_text(f"{name}-working\n", encoding="utf-8")
    (dest / "untracked.txt").write_text(f"{name}-untracked\n", encoding="utf-8")
    return dest


def _ignored_parent(path: Path) -> Path:
    init_repo(path)
    (path / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
    git(path, "add", "--", ".gitignore")
    git(path, "commit", "-m", "ignore nested repos")
    return path


def _snapshot_manifests(home: Path) -> list[Path]:
    manifests: list[Path] = []
    for entry in rescue_entries(home):
        path = entry / "manifest.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("kind") == "verified-snapshot":
            manifests.append(path)
    return manifests


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


def _stage_for(repo: Path, rel: str) -> str:
    return git(repo, "ls-files", "--stage", "--", rel).stdout


def test_preserve_nested_sidecar_linked_and_external(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = redirect_state(tmp_path, monkeypatch)
    parent = _ignored_parent(tmp_path / "parent")
    sidecar = _dirty_nested(
        _seed_origin(tmp_path / "plans-origin", "plans-head\n"),
        parent / "sase" / "repos" / "plans",
        "plans",
    )
    linked = _dirty_nested(
        _seed_origin(tmp_path / "linked-origin", "linked-head\n"),
        parent / "sase" / "repos" / "linked" / "plugin",
        "linked",
    )
    external = _dirty_nested(
        _seed_origin(tmp_path / "ext-origin", "external-head\n"),
        parent / "sase" / "repos" / "external" / "gh" / "owner" / "repo",
        "external",
    )
    sidecar_stage = _stage_for(sidecar, "tracked.txt")
    linked_stage = _stage_for(linked, "tracked.txt")
    external_stage = _stage_for(external, "tracked.txt")

    result = preserve_nested_repositories(
        parent,
        workspace_dir=parent,
        workspace_num=WORKSPACE_NUM,
        reason="nested preservation",
    )
    assert len(result.roots) == 3
    assert len(result.locations) == 3
    restored: dict[str, Path] = {}
    for location in result.locations:
        dest = tmp_path / f"restore-{Path(location).parent.name}"
        dest.mkdir()
        restore_git_snapshot(location, dest)
        if (dest / "untracked.txt").is_file():
            restored[(dest / "untracked.txt").read_text(encoding="utf-8")] = dest

    plans = restored["plans-untracked\n"]
    assert (plans / "tracked.txt").read_text(encoding="utf-8") == "plans-working\n"
    assert _stage_for(plans, "tracked.txt") == sidecar_stage
    plugin = restored["linked-untracked\n"]
    assert (plugin / "tracked.txt").read_text(encoding="utf-8") == "linked-working\n"
    assert _stage_for(plugin, "tracked.txt") == linked_stage
    ext = restored["external-untracked\n"]
    assert (ext / "tracked.txt").read_text(encoding="utf-8") == "external-working\n"
    assert _stage_for(ext, "tracked.txt") == external_stage
    assert _snapshot_manifests(home)


def test_preserve_nested_large_published_clone_under_snapshot_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = redirect_state(tmp_path, monkeypatch)
    parent = _ignored_parent(tmp_path / "parent")
    remote = _seed_large_published_origin(tmp_path)
    external = _clone(
        remote,
        parent / "sase" / "repos" / "external" / "projects" / "owner" / "repo",
    )
    git(external, "remote", "set-url", "origin", os.path.relpath(remote, external))
    (external / "tracked.txt").write_text("small local edit\n", encoding="utf-8")
    monkeypatch.setattr(payload_module, "SNAPSHOT_MAX_BYTES", 64 * 1024)

    result = preserve_nested_repositories(
        parent,
        workspace_dir=parent,
        workspace_num=WORKSPACE_NUM,
        reason="large published external clone",
    )
    assert len(result.locations) == 1
    manifest = json.loads(Path(result.locations[0]).read_text(encoding="utf-8"))
    assert manifest["base"]["mode"] == "published"
    assert manifest["base"]["remotes"][0]["fetch_url"] == str(remote.resolve())
    assert (
        Path(result.locations[0]).parent / "snapshot.pack"
    ).stat().st_size < 64 * 1024

    restored = tmp_path / "restored-large-external"
    restored.mkdir()
    restore_git_snapshot(result.locations[0], restored)
    assert (restored / "tracked.txt").read_text(
        encoding="utf-8"
    ) == "small local edit\n"
    assert (restored / "large.bin").read_bytes() == (
        external / "large.bin"
    ).read_bytes()


def test_launch_eviction_preserves_large_published_external_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = redirect_state(tmp_path, monkeypatch)
    parent = _ignored_parent(tmp_path / "workspace")
    remote = _seed_large_published_origin(tmp_path)
    external = _clone(
        remote,
        parent / "sase" / "repos" / "external" / "projects" / "owner" / "large-repo",
    )
    (external / "tracked.txt").write_text("edited before eviction\n", encoding="utf-8")
    monkeypatch.setattr(payload_module, "SNAPSHOT_MAX_BYTES", 64 * 1024)
    _configure_launch(monkeypatch, parent)

    prepare_launch_workspace_repos(str(parent), WORKSPACE_NUM)

    assert not (parent / "sase" / "repos").exists()
    manifests = _snapshot_manifests(home)
    assert manifests
    snapshot_manifest = next(
        path
        for path in manifests
        if json.loads(path.read_text(encoding="utf-8")).get("kind")
        == "verified-snapshot"
    )
    restored = tmp_path / "restored-launch-large"
    restored.mkdir()
    restore_git_snapshot(snapshot_manifest, restored)
    assert (restored / "tracked.txt").read_text(encoding="utf-8") == (
        "edited before eviction\n"
    )
    assert (
        restored / "large.bin"
    ).read_bytes() == b"published large content\n" * 12_000


def test_preserve_nested_git_file_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    parent = _ignored_parent(tmp_path / "parent")
    origin = _seed_origin(tmp_path / "wt-origin", "worktree-head\n")
    work = tmp_path / "wt-main"
    _clone(origin, work)
    dest = parent / "sase" / "repos" / "linked" / "plugin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(work, "worktree", "add", "-b", "plugin-wt", str(dest))
    git(dest, "config", "user.email", "test@test.com")
    git(dest, "config", "user.name", "Test")
    (dest / "tracked.txt").write_text("worktree-working\n", encoding="utf-8")
    (dest / "untracked.txt").write_text("worktree-untracked\n", encoding="utf-8")
    assert dest.joinpath(".git").is_file()

    result = preserve_nested_repositories(
        parent,
        workspace_dir=parent,
        workspace_num=WORKSPACE_NUM,
        reason="worktree nested",
    )
    assert len(result.locations) == 1
    restored = tmp_path / "restore-wt"
    restored.mkdir()
    restore_git_snapshot(result.locations[0], restored)
    assert (restored / "tracked.txt").read_text(encoding="utf-8") == (
        "worktree-working\n"
    )
    assert (restored / "untracked.txt").read_text(encoding="utf-8") == (
        "worktree-untracked\n"
    )


def test_invalid_git_file_is_refused_without_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    parent = _ignored_parent(tmp_path / "parent")
    broken = parent / "sase" / "repos" / "linked" / "broken"
    broken.mkdir(parents=True)
    (broken / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
    marker = broken / "keep.txt"
    marker.write_text("must remain\n", encoding="utf-8")

    with pytest.raises(NestedPreservationError, match="nested repository"):
        preserve_nested_repositories(
            parent,
            workspace_dir=parent,
            workspace_num=WORKSPACE_NUM,
            reason="invalid git file",
        )
    assert marker.read_text(encoding="utf-8") == "must remain\n"


def test_enumeration_failure_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    parent = _ignored_parent(tmp_path / "parent")
    repos = parent / "sase" / "repos"
    repos.mkdir(parents=True, exist_ok=True)
    os.chmod(repos, 0)
    try:
        try:
            list(repos.iterdir())
        except OSError:
            pass
        else:
            pytest.skip("listing a mode-0 directory succeeded")
        with pytest.raises(PreservationError, match="enumerate"):
            discover_nested_git_repos(parent)
    finally:
        os.chmod(repos, 0o755)


def test_injected_nested_capture_failure_keeps_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    parent = _ignored_parent(tmp_path / "parent")
    first = _dirty_nested(
        _seed_origin(tmp_path / "plans-origin", "plans-head\n"),
        parent / "sase" / "repos" / "plans",
        "plans",
    )
    second = _dirty_nested(
        _seed_origin(tmp_path / "linked-origin", "linked-head\n"),
        parent / "sase" / "repos" / "linked" / "plugin",
        "linked",
    )
    import sase.workspace_provider._snapshot_nested as nested_mod

    real = nested_mod.snapshot_git_repo
    calls = {"n": 0}

    def fail_second(repo_root: str | Path, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise PreservationError("injected nested capture failure")
        return real(repo_root, **kwargs)

    monkeypatch.setattr(nested_mod, "snapshot_git_repo", fail_second)
    with pytest.raises(NestedPreservationError) as exc_info:
        preserve_nested_repositories(
            parent,
            workspace_dir=parent,
            workspace_num=WORKSPACE_NUM,
            reason="injected failure",
        )
    assert exc_info.value.locations
    assert "injected nested capture failure" in str(exc_info.value)
    assert (first / "tracked.txt").read_text(encoding="utf-8") == "plans-working\n"
    assert (second / "untracked.txt").read_text(encoding="utf-8") == (
        "linked-untracked\n"
    )


def test_launch_eviction_restores_dirty_nested_from_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    linked = _dirty_nested(
        _seed_origin(tmp_path / "linked-origin", "linked-head\n"),
        workspace / "sase" / "repos" / "linked" / "plugin",
        "linked",
    )
    linked_stage = _stage_for(linked, "tracked.txt")
    _configure_launch(monkeypatch, workspace)

    prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM)

    assert not (workspace / "sase" / "repos").exists()
    manifests = _snapshot_manifests(home)
    assert manifests
    restored = tmp_path / "restore-launch"
    restored.mkdir()
    restore_git_snapshot(manifests[0], restored)
    assert (restored / "tracked.txt").read_text(encoding="utf-8") == "linked-working\n"
    assert (restored / "untracked.txt").read_text(encoding="utf-8") == (
        "linked-untracked\n"
    )
    assert _stage_for(restored, "tracked.txt") == linked_stage


def test_launch_evicts_after_snapshot_when_legacy_rescue_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    linked = _dirty_nested(
        _seed_origin(tmp_path / "linked-origin", "linked-head\n"),
        workspace / "sase" / "repos" / "linked" / "plugin",
        "linked",
    )
    linked_stage = _stage_for(linked, "tracked.txt")
    _configure_launch(monkeypatch, workspace)
    monkeypatch.setattr(
        "sase.workspace_provider.rescue.rescue_git_repo",
        lambda *_args, **_kwargs: None,
    )

    prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM)

    assert not (workspace / "sase" / "repos").exists()
    manifests = _snapshot_manifests(home)
    assert manifests
    restored = tmp_path / "restore-rescue-none"
    restored.mkdir()
    restore_git_snapshot(manifests[0], restored)
    assert (restored / "tracked.txt").read_text(encoding="utf-8") == "linked-working\n"
    assert (restored / "untracked.txt").read_text(encoding="utf-8") == (
        "linked-untracked\n"
    )
    assert _stage_for(restored, "tracked.txt") == linked_stage


def test_launch_eviction_refuses_when_nested_snapshot_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    linked = _dirty_nested(
        _seed_origin(tmp_path / "linked-origin", "linked-head\n"),
        workspace / "sase" / "repos" / "linked" / "plugin",
        "linked",
    )
    _configure_launch(monkeypatch, workspace)
    import sase.workspace_provider._snapshot_nested as nested_mod

    def boom(*_args: object, **_kwargs: object) -> object:
        raise PreservationError("injected nested capture failure")

    monkeypatch.setattr(nested_mod, "snapshot_git_repo", boom)
    with pytest.raises(WorkspacePreparationError) as exc_info:
        prepare_launch_workspace_repos(str(workspace), WORKSPACE_NUM)
    assert exc_info.value.reclone_eligible is False
    assert (linked / "untracked.txt").read_text(encoding="utf-8") == (
        "linked-untracked\n"
    )
    assert (workspace / "sase" / "repos" / "linked" / "plugin").is_dir()


def test_recreate_restores_dirty_nested_after_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _ = redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    init_repo(origin)
    (origin / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
    (origin / "README.md").write_text("origin v1\n", encoding="utf-8")
    git(origin, "add", ".")
    git(origin, "commit", "-m", "init")
    primary = _clone(origin, tmp_path / "primary")
    workspace = _clone(primary, tmp_path / "primary_7")
    sidecar = _dirty_nested(
        _seed_origin(tmp_path / "plans-origin", "plans-head\n"),
        workspace / "sase" / "repos" / "plans",
        "plans",
    )
    linked = _dirty_nested(
        _seed_origin(tmp_path / "linked-origin", "linked-head\n"),
        workspace / "sase" / "repos" / "linked" / "plugin",
        "linked",
    )
    sidecar_stage = _stage_for(sidecar, "tracked.txt")
    linked_stage = _stage_for(linked, "tracked.txt")

    recreate_managed_workspace(
        str(workspace),
        WORKSPACE_NUM,
        config={"workspace": {"root": "adjacent"}},
        env={},
    )

    assert not (workspace / "sase" / "repos" / "plans").exists()
    assert not (workspace / "sase" / "repos" / "linked" / "plugin").exists()
    restored: dict[str, Path] = {}
    for manifest in _snapshot_manifests(home):
        dest = tmp_path / f"restore-{manifest.parent.name}"
        dest.mkdir()
        restore_git_snapshot(manifest, dest)
        untracked = dest / "untracked.txt"
        if untracked.is_file():
            restored[untracked.read_text(encoding="utf-8")] = dest
    plans = restored["plans-untracked\n"]
    plugin = restored["linked-untracked\n"]
    assert (plans / "tracked.txt").read_text(encoding="utf-8") == "plans-working\n"
    assert _stage_for(plans, "tracked.txt") == sidecar_stage
    assert (plugin / "tracked.txt").read_text(encoding="utf-8") == "linked-working\n"
    assert _stage_for(plugin, "tracked.txt") == linked_stage


def test_recreate_refuses_when_nested_snapshot_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    origin = tmp_path / "origin"
    init_repo(origin)
    (origin / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
    (origin / "README.md").write_text("origin v1\n", encoding="utf-8")
    git(origin, "add", ".")
    git(origin, "commit", "-m", "init")
    primary = _clone(origin, tmp_path / "primary")
    workspace = _clone(primary, tmp_path / "primary_7")
    linked = _dirty_nested(
        _seed_origin(tmp_path / "linked-origin", "linked-head\n"),
        workspace / "sase" / "repos" / "linked" / "plugin",
        "linked",
    )
    import sase.workspace_provider._snapshot_nested as nested_mod

    def boom(*_args: object, **_kwargs: object) -> object:
        raise PreservationError("injected nested capture failure")

    monkeypatch.setattr(nested_mod, "snapshot_git_repo", boom)
    with pytest.raises(RuntimeError, match="nested preservation") as exc_info:
        recreate_managed_workspace(
            str(workspace),
            WORKSPACE_NUM,
            config={"workspace": {"root": "adjacent"}},
            env={},
        )
    assert "injected nested capture failure" in str(exc_info.value)
    assert (linked / "untracked.txt").read_text(encoding="utf-8") == (
        "linked-untracked\n"
    )
    assert workspace.is_dir()

"""Real-git unit tests for the durable rescue store."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from sase.workspace_provider import rescue as rescue_module
from sase.workspace_provider.rescue import (
    _reap_rescue_store,
    quarantine_directory,
    rescue_git_repo,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    _git(path, "commit", "--allow-empty", "-m", "init")


def _commit_file(repo: Path, relpath: str, text: str, message: str) -> str:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(repo, "add", "--", relpath)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _redirect_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[object, ...]]]:
    """Point SASE_HOME and notifications at tmp; return home and sent notes."""
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    notified: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )
    return home, notified


def _seed_remote_clone(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (workspace, clone, remote) with the clone tracking a bare remote."""
    remote = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "seed"
    _init_repo(seed)
    _commit_file(seed, "base.txt", "base\n", "seed base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    workspace = tmp_path / "project_7"
    workspace.mkdir()
    clone = workspace / "sase" / "repos" / "plans"
    clone.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(clone, "config", "user.email", "test@test.com")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "config", "commit.gpgsign", "false")
    return workspace, clone, remote


def _bundle_lists_sha(bundle: Path, sha: str) -> bool:
    """Return whether the bundle advertises *sha* as a head."""
    listing = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sha in listing


def _clone_and_fetch(bundle: Path, base: Path, dest: Path) -> Path:
    """Clone *base* (which holds the bundle's prerequisites) and fetch it."""
    subprocess.run(
        ["git", "clone", "-q", str(base), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", str(bundle), "refs/*:refs/sase/rescued/x/*"],
        cwd=dest,
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def _holds_object(repo: Path, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", sha], cwd=repo, capture_output=True
        ).returncode
        == 0
    )


def _rescue_entries(home: Path) -> list[Path]:
    root = home / "rescue"
    if not root.is_dir():
        return []
    return sorted(
        entry
        for month in root.iterdir()
        if month.is_dir()
        for entry in month.iterdir()
        if entry.is_dir()
    )


def test_rescue_bundles_local_commits_restorable_by_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = _redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = _seed_remote_clone(tmp_path)
    local_sha = _commit_file(clone, "local.txt", "local\n", "unpushed work")

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

    assert _bundle_lists_sha(record.bundle_path, local_sha)
    fresh = _clone_and_fetch(
        record.bundle_path, tmp_path / "origin.git", tmp_path / "fresh"
    )
    fetched = _git(fresh, "rev-parse", "refs/sase/rescued/x/heads/main").stdout.strip()
    assert fetched == local_sha

    assert len(notified) == 1
    sender, _cl, _ok, notes, kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert any(str(record.rescue_dir) in note for note in notes)
    assert kwargs["extra_files"] == [str(record.rescue_dir)]


def test_rescue_includes_every_stash_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = _seed_remote_clone(tmp_path)
    _commit_file(clone, "tracked.txt", "v1\n", "tracked base")
    _git(clone, "push")
    (clone / "tracked.txt").write_text("stash-one\n", encoding="utf-8")
    _git(clone, "stash", "push", "-m", "one")
    (clone / "tracked.txt").write_text("stash-two\n", encoding="utf-8")
    _git(clone, "stash", "push", "-m", "two")
    stash_shas = [
        line.strip()
        for line in _git(clone, "stash", "list", "--format=%H").stdout.splitlines()
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
        _git(
            clone, "for-each-ref", "--format=%(refname)", "refs/sase/rescue-tmp"
        ).stdout.strip()
        == ""
    )
    for sha in stash_shas:
        assert _bundle_lists_sha(record.bundle_path, sha)
    fresh = _clone_and_fetch(
        record.bundle_path, tmp_path / "origin.git", tmp_path / "fresh"
    )
    for sha in stash_shas:
        assert _holds_object(fresh, sha)


def test_rescue_patch_captures_staged_unstaged_and_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = _seed_remote_clone(tmp_path)
    _commit_file(clone, "tracked.txt", "base\n", "tracked base")
    _git(clone, "push")
    (clone / "tracked.txt").write_text("staged-plus-unstaged\n", encoding="utf-8")
    _git(clone, "add", "--", "tracked.txt")
    (clone / "tracked.txt").write_text("staged-plus-unstaged\nmore\n", encoding="utf-8")
    (clone / "new.txt").write_text("untracked\n", encoding="utf-8")
    staged_before = _git(clone, "diff", "--cached", "--name-only").stdout

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
    assert _git(clone, "diff", "--cached", "--name-only").stdout == staged_before
    # The patch applies cleanly against a fresh checkout of the base.
    applier = tmp_path / "applier"
    subprocess.run(
        ["git", "clone", str(clone), str(applier)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(applier, "checkout", "-q", "HEAD", "--", ".")
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
    _redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = _seed_remote_clone(tmp_path)
    _commit_file(clone, "file.txt", "base\n", "base file")
    _git(clone, "checkout", "-b", "feature")
    _commit_file(clone, "file.txt", "feature\n", "feature change")
    _git(clone, "checkout", "-q", "main")
    _commit_file(clone, "file.txt", "main\n", "main change")
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


def test_rescue_returns_none_when_nothing_to_rescue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = _redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = _seed_remote_clone(tmp_path)

    assert (
        rescue_git_repo(
            clone,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="clean",
            include_worktree=True,
        )
        is None
    )
    assert (
        rescue_git_repo(
            tmp_path,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="not a repo",
            include_worktree=True,
        )
        is None
    )
    assert _rescue_entries(home) == []
    assert notified == []


def test_rescue_bundles_everything_without_remote_tracking_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "project_7"
    repo = workspace / "sase" / "repos" / "plans"
    _init_repo(repo)
    sha = _commit_file(repo, "solo.txt", "solo\n", "offline work")

    record = rescue_git_repo(
        repo,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="offline",
        include_worktree=False,
    )

    assert record is not None and record.bundle_path is not None
    assert _bundle_lists_sha(record.bundle_path, sha)
    fresh = _clone_and_fetch(record.bundle_path, repo, tmp_path / "fresh")
    assert _holds_object(fresh, sha)


def test_rescue_patch_cap_is_honored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = _seed_remote_clone(tmp_path)
    local_sha = _commit_file(clone, "local.txt", "local\n", "unpushed work")
    (clone / "big.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setattr(rescue_module, "RESCUE_PATCH_MAX_BYTES", 4)

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


def test_reap_deletes_only_aged_entries(tmp_path: Path) -> None:
    root = tmp_path / "rescue"
    month = root / "202601"
    young = month / "young"
    old_bundle = month / "old-bundle"
    old_quarantine = month / "old-quarantine"
    young_quarantine = month / "young-quarantine"
    for entry in (young, old_bundle, old_quarantine, young_quarantine):
        entry.mkdir(parents=True)
        (entry / "manifest.json").write_text("{}\n", encoding="utf-8")
    for entry in (old_quarantine, young_quarantine):
        (entry / "quarantined-clone").mkdir()
    now = time.time()
    aged_bundle = now - 31 * 86400
    aged_quarantine = now - 8 * 86400
    os.utime(old_bundle, (aged_bundle, aged_bundle))
    os.utime(old_quarantine, (aged_quarantine, aged_quarantine))

    _reap_rescue_store(rescue_roots=[root], now=now)

    assert young.is_dir()
    assert young_quarantine.is_dir()
    assert not old_bundle.exists()
    assert not old_quarantine.exists()


def test_quarantine_directory_moves_clone_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = _redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = _seed_remote_clone(tmp_path)

    record = quarantine_directory(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason="damaged",
    )

    assert record is not None
    assert record.quarantined_path is not None
    assert not clone.exists()
    assert (record.quarantined_path / ".git").is_dir()
    assert record.quarantined_path.parent == record.rescue_dir
    assert workspace not in record.rescue_dir.parents
    assert (record.rescue_dir / "manifest.json").is_file()
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"

    assert (
        quarantine_directory(
            tmp_path / "missing",
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="missing",
        )
        is None
    )
    assert _rescue_entries(home) != []

from __future__ import annotations

import json
import subprocess

import pytest

from sase.workspace_provider.snapshot import (
    PreservationError,
    restore_git_snapshot,
    snapshot_git_repo,
    snapshot_source_fingerprint,
)
from tests.workspace_provider.test_rescue._helpers import (
    commit_file,
    git,
    init_repo,
    redirect_state,
    rescue_entries,
    seed_remote_clone,
)
from tests.workspace_provider.test_rescue._snapshot_helpers import (
    assert_source_unchanged,
    head,
    make_dirty_wiring,
    restore_dest,
    snapshot,
    worktree_map,
    ls_stage,
)


def test_snapshot_returns_none_when_checkout_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)

    assert snapshot(clone, workspace, reason="clean") is None
    assert rescue_entries(home) == []
    assert notified == []


def test_snapshot_refuses_non_git_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, _clone, _remote = seed_remote_clone(tmp_path)
    empty = tmp_path / "not-a-repo"
    empty.mkdir()

    with pytest.raises(PreservationError, match="git"):
        snapshot_git_repo(
            empty,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="not a repo",
        )


def test_snapshot_restores_tracked_and_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    make_dirty_wiring(clone)
    (clone / "docs" / "naïve file.txt").parent.mkdir(parents=True, exist_ok=True)
    (clone / "docs" / "naïve file.txt").write_text("unusual\n", encoding="utf-8")
    before = source_probe(clone)

    record = snapshot(clone, workspace)
    assert record is not None
    assert record.manifest_path.is_absolute()
    assert record.manifest_path.is_file()
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == "verified-snapshot"
    assert manifest["snapshot_id"] == record.snapshot_id
    assert manifest["source_fingerprint"] == snapshot_source_fingerprint(clone)
    assert_source_unchanged(clone, before)

    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "src" / "dispatch.py").read_text(encoding="utf-8") == (
        "dispatch-dirty\n"
    )
    assert (dest / "src" / "new_impl.py").read_text(encoding="utf-8") == (
        "untracked-impl\n"
    )
    assert (dest / "docs" / "naïve file.txt").read_text(encoding="utf-8") == (
        "unusual\n"
    )
    assert "src/new_impl.py" not in git(dest, "ls-files").stdout
    assert "src/dispatch.py" in git(dest, "diff", "--name-only", "HEAD").stdout


def test_published_snapshot_thins_a_large_checkout_and_restores_exact_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, remote = seed_remote_clone(tmp_path)
    commit_file(clone, "modified.txt", "before\n", "modified base")
    commit_file(clone, "staged.txt", "staged base\n", "staged base")
    (clone / "large.bin").write_bytes(b"large-published-content" * (256 * 1024 // 23))
    git(clone, "add", "--", "large.bin")
    git(clone, "commit", "-m", "large published file")
    git(clone, "push")

    (clone / "modified.txt").write_text("modified locally\n", encoding="utf-8")
    (clone / "staged.txt").write_text("staged locally\n", encoding="utf-8")
    git(clone, "add", "--", "staged.txt")
    (clone / "untracked.txt").write_bytes(b"new local bytes\x00\xff")
    before = source_probe(clone)
    cap = 64 * 1024
    monkeypatch.setattr(payload_objects_module, "SNAPSHOT_MAX_BYTES", cap)

    record = snapshot(clone, workspace, reason="thin published base")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["base"]["mode"] == "published"
    assert manifest["base"]["boundary_commits"] == [head(clone)]
    assert any(
        remote_info["name"] == "origin" for remote_info in manifest["base"]["remotes"]
    )
    assert record.pack_path.stat().st_size < cap
    assert record.pack_path.stat().st_size < 16 * 1024
    assert_source_unchanged(clone, before)

    empty_dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, empty_dest)
    assert worktree_map(empty_dest) == worktree_map(clone)
    assert ls_stage(empty_dest) == ls_stage(clone)

    fresh_dest = tmp_path / "fresh-remote-clone"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(fresh_dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    restore_git_snapshot(record.manifest_path, fresh_dest)
    assert worktree_map(fresh_dest) == worktree_map(clone)
    assert ls_stage(fresh_dest) == ls_stage(clone)


def test_published_snapshot_carries_local_commits_and_dirty_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, remote = seed_remote_clone(tmp_path)
    pushed_tip = head(clone)
    commit_file(clone, "local-commit.txt", "local commit\n", "unpushed commit")
    (clone / "local-commit.txt").write_text("working edit\n", encoding="utf-8")
    (clone / "staged.txt").write_text("staged edit\n", encoding="utf-8")
    git(clone, "add", "--", "staged.txt")
    before = source_probe(clone)

    record = snapshot(clone, workspace, reason="local-only commit and edits")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["base"]["mode"] == "published"
    assert manifest["base"]["boundary_commits"] == [pushed_tip]
    assert_source_unchanged(clone, before)

    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert head(dest) == head(clone)
    assert worktree_map(dest) == worktree_map(clone)
    assert ls_stage(dest) == ls_stage(clone)
    assert git(remote, "rev-parse", "refs/heads/main").stdout.strip() == pushed_tip


def test_snapshot_without_remote_is_self_contained_and_legacy_manifest_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    clone = tmp_path / "standalone"
    init_repo(clone)
    commit_file(clone, "tracked.txt", "base\n", "standalone file")
    (clone / "tracked.txt").write_text("working bytes\n", encoding="utf-8")
    (clone / "new.txt").write_text("untracked\n", encoding="utf-8")

    record = snapshot(clone, workspace, reason="self-contained")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["base"] == {
        "mode": "self-contained",
        "boundary_commits": [],
        "remotes": [],
        "remote_tracking_refs": [],
    }

    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert head(dest) == head(clone)
    assert worktree_map(dest) == worktree_map(clone)
    assert ls_stage(dest) == ls_stage(clone)

    del manifest["base"]
    record.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    legacy_dest = tmp_path / "legacy-dest"
    legacy_dest.mkdir()
    restore_git_snapshot(record.manifest_path, legacy_dest)
    assert head(legacy_dest) == head(clone)
    assert worktree_map(legacy_dest) == worktree_map(clone)
    assert ls_stage(legacy_dest) == ls_stage(clone)


def test_published_snapshot_fails_before_worktree_write_when_base_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, remote = seed_remote_clone(tmp_path)
    (clone / "base.txt").write_text("dirty bytes\n", encoding="utf-8")
    record = snapshot(clone, workspace, reason="unavailable base")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    boundary = manifest["base"]["boundary_commits"][0]
    recorded_url = manifest["base"]["remotes"][0]["fetch_url"]
    remote.rename(tmp_path / "moved-origin.git")

    dest = restore_dest(tmp_path)
    with pytest.raises(PreservationError) as exc_info:
        restore_git_snapshot(record.manifest_path, dest)
    assert boundary in str(exc_info.value)
    assert recorded_url in str(exc_info.value)
    assert not (dest / "base.txt").exists()
    assert [path.name for path in dest.iterdir()] == [".git"]

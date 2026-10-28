"""Verified snapshot capture and restore tests."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.workspace_provider import (
    _snapshot_capture_payload as payload_module,
    _snapshot_capture_source as source_module,
)
from sase.workspace_provider._snapshot_model import SourceState
from sase.workspace_provider.snapshot import (
    PreservationError,
    SnapshotRecord,
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


def _ls_stage(repo: Path) -> str:
    return git(repo, "ls-files", "-z", "--stage").stdout


def _worktree_map(repo: Path) -> dict[str, bytes]:
    mapping: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(repo).as_posix()
            if path.is_symlink():
                mapping[rel] = b"symlink:" + os.fsencode(os.readlink(path))
            else:
                mapping[rel] = path.read_bytes()
    return mapping


def _index_bytes(repo: Path) -> bytes:
    git_dir = git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()
    index = Path(git_dir) / "index"
    return index.read_bytes() if index.is_file() else b""


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _source_probe(repo: Path) -> tuple[str, bytes, str, dict[str, bytes]]:
    return _head(repo), _index_bytes(repo), _ls_stage(repo), _worktree_map(repo)


def _assert_source_unchanged(
    repo: Path, before: tuple[str, bytes, str, dict[str, bytes]]
) -> None:
    assert _source_probe(repo) == before


def _make_dirty_wiring(clone: Path) -> None:
    commit_file(clone, "src/dispatch.py", "dispatch-base\n", "tracked wiring")
    git(clone, "push")
    (clone / "src" / "dispatch.py").write_text("dispatch-dirty\n", encoding="utf-8")
    (clone / "src" / "new_impl.py").write_text("untracked-impl\n", encoding="utf-8")


def _restore_dest(tmp_path: Path) -> Path:
    dest = tmp_path / "restore-dest"
    dest.mkdir()
    return dest


def _snapshot(
    clone: Path, workspace: Path, *, reason: str = "verified snapshot"
) -> SnapshotRecord | None:
    return snapshot_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason=reason,
    )


def test_snapshot_returns_none_when_checkout_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)

    assert _snapshot(clone, workspace, reason="clean") is None
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
    _make_dirty_wiring(clone)
    (clone / "docs" / "naïve file.txt").parent.mkdir(parents=True, exist_ok=True)
    (clone / "docs" / "naïve file.txt").write_text("unusual\n", encoding="utf-8")
    before = _source_probe(clone)

    record = _snapshot(clone, workspace)
    assert record is not None
    assert record.manifest_path.is_absolute()
    assert record.manifest_path.is_file()
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == "verified-snapshot"
    assert manifest["snapshot_id"] == record.snapshot_id
    assert manifest["source_fingerprint"] == snapshot_source_fingerprint(clone)
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
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
    before = _source_probe(clone)
    cap = 64 * 1024
    monkeypatch.setattr(payload_module, "SNAPSHOT_MAX_BYTES", cap)

    record = _snapshot(clone, workspace, reason="thin published base")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["base"]["mode"] == "published"
    assert manifest["base"]["boundary_commits"] == [_head(clone)]
    assert any(
        remote_info["name"] == "origin" for remote_info in manifest["base"]["remotes"]
    )
    assert record.pack_path.stat().st_size < cap
    assert record.pack_path.stat().st_size < 16 * 1024
    _assert_source_unchanged(clone, before)

    empty_dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, empty_dest)
    assert _worktree_map(empty_dest) == _worktree_map(clone)
    assert _ls_stage(empty_dest) == _ls_stage(clone)

    fresh_dest = tmp_path / "fresh-remote-clone"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(fresh_dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    restore_git_snapshot(record.manifest_path, fresh_dest)
    assert _worktree_map(fresh_dest) == _worktree_map(clone)
    assert _ls_stage(fresh_dest) == _ls_stage(clone)


def test_published_snapshot_carries_local_commits_and_dirty_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, remote = seed_remote_clone(tmp_path)
    pushed_tip = _head(clone)
    commit_file(clone, "local-commit.txt", "local commit\n", "unpushed commit")
    (clone / "local-commit.txt").write_text("working edit\n", encoding="utf-8")
    (clone / "staged.txt").write_text("staged edit\n", encoding="utf-8")
    git(clone, "add", "--", "staged.txt")
    before = _source_probe(clone)

    record = _snapshot(clone, workspace, reason="local-only commit and edits")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["base"]["mode"] == "published"
    assert manifest["base"]["boundary_commits"] == [pushed_tip]
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert _head(dest) == _head(clone)
    assert _worktree_map(dest) == _worktree_map(clone)
    assert _ls_stage(dest) == _ls_stage(clone)
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

    record = _snapshot(clone, workspace, reason="self-contained")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["base"] == {
        "mode": "self-contained",
        "boundary_commits": [],
        "remotes": [],
        "remote_tracking_refs": [],
    }

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert _head(dest) == _head(clone)
    assert _worktree_map(dest) == _worktree_map(clone)
    assert _ls_stage(dest) == _ls_stage(clone)

    del manifest["base"]
    record.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    legacy_dest = tmp_path / "legacy-dest"
    legacy_dest.mkdir()
    restore_git_snapshot(record.manifest_path, legacy_dest)
    assert _head(legacy_dest) == _head(clone)
    assert _worktree_map(legacy_dest) == _worktree_map(clone)
    assert _ls_stage(legacy_dest) == _ls_stage(clone)


def test_published_snapshot_fails_before_worktree_write_when_base_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, remote = seed_remote_clone(tmp_path)
    (clone / "base.txt").write_text("dirty bytes\n", encoding="utf-8")
    record = _snapshot(clone, workspace, reason="unavailable base")
    assert record is not None
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    boundary = manifest["base"]["boundary_commits"][0]
    recorded_url = manifest["base"]["remotes"][0]["fetch_url"]
    remote.rename(tmp_path / "moved-origin.git")

    dest = _restore_dest(tmp_path)
    with pytest.raises(PreservationError) as exc_info:
        restore_git_snapshot(record.manifest_path, dest)
    assert boundary in str(exc_info.value)
    assert recorded_url in str(exc_info.value)
    assert not (dest / "base.txt").exists()
    assert [path.name for path in dest.iterdir()] == [".git"]


def test_snapshot_hashes_only_dirty_candidates_in_a_large_clean_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    for index in range(300):
        path = clone / "tracked" / f"{index:03}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"clean {index}\n", encoding="utf-8")
    git(clone, "add", "--", "tracked")
    git(clone, "commit", "-m", "many clean files")
    git(clone, "push")
    (clone / "tracked" / "100.txt").write_text("one dirty file\n", encoding="utf-8")

    hash_object_calls: list[tuple[str, ...]] = []
    real_run_git_bytes = payload_module.run_git_bytes

    def count_hash_objects(
        repo: Path, *args: str, **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        if args and args[0] == "hash-object":
            hash_object_calls.append(args)
        return real_run_git_bytes(repo, *args, **kwargs)

    monkeypatch.setattr(payload_module, "run_git_bytes", count_hash_objects)
    record = _snapshot(clone, workspace, reason="hash only dirty candidate")
    assert record is not None
    assert len(hash_object_calls) <= 2


def test_snapshot_captures_assume_unchanged_and_skip_worktree_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "assume.txt", "assume base\n", "assume base")
    commit_file(clone, "skip.txt", "skip base\n", "skip base")
    git(clone, "push")
    git(clone, "update-index", "--assume-unchanged", "assume.txt")
    git(clone, "update-index", "--skip-worktree", "skip.txt")
    (clone / "assume.txt").write_text("assume dirty\n", encoding="utf-8")
    (clone / "skip.txt").write_text("skip dirty\n", encoding="utf-8")

    record = _snapshot(clone, workspace, reason="special index flags")
    assert record is not None
    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "assume.txt").read_text(encoding="utf-8") == "assume dirty\n"
    assert (dest / "skip.txt").read_text(encoding="utf-8") == "skip dirty\n"


def test_snapshot_excludes_gitlink_commits_from_pack_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    submodule = tmp_path / "submodule"
    init_repo(submodule)
    submodule_sha = _head(submodule)
    clone = tmp_path / "superproject"
    init_repo(clone)
    commit_file(clone, "tracked.txt", "base\n", "tracked base")
    git(clone, "update-index", "--add", "--cacheinfo", f"160000,{submodule_sha},module")
    git(clone, "commit", "-m", "record gitlink")
    (clone / "tracked.txt").write_text("working edit\n", encoding="utf-8")

    record = _snapshot(clone, workspace, reason="gitlink preservation")
    assert record is not None
    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "tracked.txt").read_text(encoding="utf-8") == "working edit\n"
    assert (
        git(dest, "ls-files", "--stage", "--", "module").stdout
        == git(clone, "ls-files", "--stage", "--", "module").stdout
    )
    assert not (dest / "module").exists()


def test_snapshot_restores_staged_only_and_distinct_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "tracked.txt", "head-bytes\n", "base tracked")
    git(clone, "push")
    (clone / "tracked.txt").write_text("staged-bytes\n", encoding="utf-8")
    git(clone, "add", "--", "tracked.txt")
    (clone / "tracked.txt").write_text("head-bytes\n", encoding="utf-8")
    staged_only = git(clone, "diff", "--cached", "--binary", "HEAD").stdout
    worktree_after_stage = (clone / "tracked.txt").read_text(encoding="utf-8")
    assert worktree_after_stage == "head-bytes\n"
    assert "staged-bytes" in staged_only
    before = _source_probe(clone)

    record = _snapshot(clone, workspace, reason="staged-only")
    assert record is not None
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "tracked.txt").read_text(encoding="utf-8") == "head-bytes\n"
    assert git(dest, "diff", "--cached", "--binary", "HEAD").stdout == staged_only

    (clone / "tracked.txt").write_text("unstaged-bytes\n", encoding="utf-8")
    distinct = _snapshot(clone, workspace, reason="distinct")
    assert distinct is not None
    dest2 = tmp_path / "restore-distinct"
    dest2.mkdir()
    restore_git_snapshot(distinct.manifest_path, dest2)
    assert (dest2 / "tracked.txt").read_text(encoding="utf-8") == "unstaged-bytes\n"
    assert "staged-bytes" in git(dest2, "diff", "--cached", "--binary", "HEAD").stdout
    assert "unstaged-bytes" in git(dest2, "diff", "--binary", "HEAD").stdout


def test_snapshot_restores_deletion_binary_and_tracked_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "keep.txt", "keep\n", "keep")
    commit_file(clone, "delete-me.txt", "gone-soon\n", "to delete")
    commit_file(clone, "build/out.bin", "tracked-ignored\n", "tracked build")
    git(clone, "push")
    (clone / ".gitignore").write_text("build/\n", encoding="utf-8")
    git(clone, "add", "--", ".gitignore")
    git(clone, "commit", "-m", "ignore build")
    git(clone, "push")
    (clone / "delete-me.txt").unlink()
    git(clone, "add", "--", "delete-me.txt")
    (clone / "keep.txt").unlink()
    (clone / "build" / "out.bin").write_bytes(b"tracked-ignored-dirty\x00\xff")
    (clone / "payload.bin").write_bytes(b"\x00\xffbinary-untracked")
    before = _source_probe(clone)

    record = _snapshot(clone, workspace, reason="delete-binary-ignored")
    assert record is not None
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert not (dest / "keep.txt").exists()
    assert not (dest / "delete-me.txt").exists()
    assert "delete-me.txt" in git(dest, "diff", "--cached", "--name-only").stdout
    assert (dest / "build" / "out.bin").read_bytes() == b"tracked-ignored-dirty\x00\xff"
    assert (dest / "payload.bin").read_bytes() == b"\x00\xffbinary-untracked"
    mode = (dest / "build" / "out.bin").stat().st_mode
    assert not stat.S_ISDIR(mode)


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
    stage_before = _ls_stage(clone)
    assert "file.txt" in stage_before
    before = _source_probe(clone)
    git_dir = Path(git(clone, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (git_dir / "MERGE_HEAD").is_file()

    record = _snapshot(clone, workspace, reason="conflict")
    assert record is not None
    assert record.unmerged is True
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
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
    before = _source_probe(clone)
    git_dir = Path(git(clone, "rev-parse", "--absolute-git-dir").stdout.strip())
    merge_head = (git_dir / "MERGE_HEAD").is_file()

    record = _snapshot(clone, workspace, reason=f"conflict-{kind}")
    assert record is not None
    assert record.unmerged is True
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / rel).read_bytes() == unique
    assert _stage_lines(dest, rel) == src_stage
    dest_git = Path(git(dest, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (dest_git / "MERGE_HEAD").is_file() is merge_head


def test_snapshot_capture_failure_leaves_source_and_prior_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    first = _snapshot(clone, workspace, reason="first")
    assert first is not None
    first_manifest = first.manifest_path.read_text(encoding="utf-8")
    before = _source_probe(clone)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("injected pack failure")

    monkeypatch.setattr(payload_module, "_write_pack", boom)
    with pytest.raises(PreservationError, match="injected pack failure"):
        _snapshot(clone, workspace, reason="second")
    _assert_source_unchanged(clone, before)
    assert first.rescue_dir.is_dir()
    assert first.manifest_path.read_text(encoding="utf-8") == first_manifest
    published = [
        entry for entry in rescue_entries(home) if (entry / "manifest.json").is_file()
    ]
    assert published == [first.rescue_dir]


def test_snapshot_manifest_failure_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    before = _source_probe(clone)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("injected manifest failure")

    monkeypatch.setattr(payload_module, "publish_manifest", boom)
    with pytest.raises(PreservationError, match="injected manifest failure"):
        _snapshot(clone, workspace)
    _assert_source_unchanged(clone, before)
    assert rescue_entries(home) == []


def test_snapshot_size_cap_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    (clone / "src" / "dispatch.py").write_text("x" * 200, encoding="utf-8")
    before = _source_probe(clone)
    monkeypatch.setattr(payload_module, "SNAPSHOT_MAX_BYTES", 16)

    with pytest.raises(PreservationError, match="cap"):
        _snapshot(clone, workspace, reason="cap")
    _assert_source_unchanged(clone, before)
    assert rescue_entries(home) == []


def test_snapshot_detects_source_change_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    before = _source_probe(clone)
    original = source_module.read_source_state
    calls = {"n": 0}

    def flipped(repo: Path) -> SourceState:
        calls["n"] += 1
        state = original(repo)
        if calls["n"] >= 2:
            (repo / "src" / "dispatch.py").write_text(
                "changed-during-capture\n", encoding="utf-8"
            )
            return original(repo)
        return state

    monkeypatch.setattr(source_module, "read_source_state", flipped)
    with pytest.raises(PreservationError, match="changed during snapshot"):
        _snapshot(clone, workspace, reason="race")
    assert calls["n"] >= 2
    assert rescue_entries(home) == []
    assert (clone / "src" / "dispatch.py").read_text(encoding="utf-8") == (
        "changed-during-capture\n"
    )
    assert _head(clone) == before[0]
    assert _index_bytes(clone) == before[1]


def test_snapshot_source_fingerprint_tracks_untracked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    _workspace, clone, _remote = seed_remote_clone(tmp_path)
    untracked = clone / "src" / "new.py"
    untracked.parent.mkdir()
    untracked.write_bytes(b"first version\n")

    first = snapshot_source_fingerprint(clone)
    untracked.write_bytes(b"second version\n")
    second = snapshot_source_fingerprint(clone)

    assert first != second


def test_snapshot_detects_untracked_source_change_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    untracked = clone / "src" / "new.py"
    untracked.parent.mkdir()
    untracked.write_bytes(b"before capture\n")
    original = source_module.read_source_state
    calls = {"n": 0}

    def flipped(repo: Path) -> SourceState:
        calls["n"] += 1
        state = original(repo)
        if calls["n"] >= 2:
            (repo / "src" / "new.py").write_bytes(b"changed during capture\n")
            return original(repo)
        return state

    monkeypatch.setattr(source_module, "read_source_state", flipped)
    with pytest.raises(PreservationError, match="changed during snapshot"):
        _snapshot(clone, workspace, reason="untracked-race")

    assert calls["n"] >= 2
    assert rescue_entries(home) == []
    assert untracked.read_bytes() == b"changed during capture\n"


def test_snapshot_ids_are_unique_for_same_head_and_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    first = _snapshot(clone, workspace, reason="one")
    second = _snapshot(clone, workspace, reason="two")
    assert first is not None and second is not None
    assert first.snapshot_id != second.snapshot_id
    assert first.rescue_dir != second.rescue_dir
    assert first.manifest_path != second.manifest_path
    assert first.rescue_dir.is_dir()
    assert second.rescue_dir.is_dir()

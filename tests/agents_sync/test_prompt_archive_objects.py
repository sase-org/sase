from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import sase_core_rs

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.models import TargetSelection
from sase.agents_sync.prompt_archive.archive_objects import (
    ARCHIVE_OBJECT_ROOT,
    quarantine_invalid_pending_objects,
)
from sase.agents_sync.prompt_archive.git_ops import (
    PUBLISHED_ARCHIVE_PATHS,
    REGENERABLE_ARCHIVE_PATHS,
    clean_prompt_archive_worktree,
    publish_pending_archive_objects,
)
from sase.agents_sync.prompt_archive.publish import publish_prompt_archive
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.git_sync_fixtures import (
    git,
    patch_payload_pass,
    setup_repo,
    target,
)


def _write_object(repo: Path, content: bytes) -> str:
    relpath = sase_core_rs.artifact_object_relpath(hashlib.sha256(content).hexdigest())
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return relpath


def _status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "-uall").stdout


def _tracked(repo: Path) -> set[str]:
    return set(git(repo, "ls-files", "--", ARCHIVE_OBJECT_ROOT).stdout.split())


def test_published_object_root_matches_rust_layout() -> None:
    digest = hashlib.sha256(b"layout pin").hexdigest()
    relpath = sase_core_rs.artifact_object_relpath(digest)

    assert relpath.startswith(f"{ARCHIVE_OBJECT_ROOT}/")
    assert ARCHIVE_OBJECT_ROOT in PUBLISHED_ARCHIVE_PATHS
    assert set(REGENERABLE_ARCHIVE_PATHS) < set(PUBLISHED_ARCHIVE_PATHS)
    assert ARCHIVE_OBJECT_ROOT not in REGENERABLE_ARCHIVE_PATHS


def test_rust_layout_object_is_a_valid_pending_object(tmp_path: Path) -> None:
    _remote, _seed, sidecar = setup_repo(tmp_path)
    relpath = _write_object(sidecar, b"canonical bytes")

    assert quarantine_invalid_pending_objects(sidecar, run_git) == (relpath,)


def test_publish_pending_objects_commits_valid_and_quarantines_invalid(
    tmp_path: Path,
) -> None:
    _remote, _seed, sidecar = setup_repo(tmp_path)
    valid = _write_object(sidecar, b"good object")
    mismatch = _write_object(sidecar, b"claimed bytes")
    (sidecar / mismatch).write_bytes(b"different bytes")
    stray = sidecar / ARCHIVE_OBJECT_ROOT / "stray.txt"
    stray.write_text("not an object\n")
    wrong_prefix = "0" * 64
    misfiled = sidecar / ARCHIVE_OBJECT_ROOT / "sha256/ff" / wrong_prefix
    misfiled.parent.mkdir(parents=True)
    misfiled.write_bytes(b"misfiled")
    link = sidecar / ARCHIVE_OBJECT_ROOT / "sha256/aa" / ("a" * 64)
    link.parent.mkdir(parents=True)
    link.symlink_to(sidecar / valid)

    assert publish_pending_archive_objects(sidecar, run_git) is True

    assert _tracked(sidecar) == {valid}
    assert _status(sidecar) == ""
    assert git(sidecar, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(agents): publish pending prompt-archive objects"
    )
    quarantine_root = sidecar / ".git/sase-quarantine/objects"
    (batch,) = quarantine_root.iterdir()
    quarantined = {
        path.relative_to(batch).as_posix(): path
        for path in batch.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    assert set(quarantined) == {
        mismatch,
        f"{ARCHIVE_OBJECT_ROOT}/stray.txt",
        f"{ARCHIVE_OBJECT_ROOT}/sha256/ff/{wrong_prefix}",
        f"{ARCHIVE_OBJECT_ROOT}/sha256/aa/{'a' * 64}",
    }
    assert quarantined[mismatch].read_bytes() == b"different bytes"
    assert quarantined[f"{ARCHIVE_OBJECT_ROOT}/stray.txt"].read_text() == (
        "not an object\n"
    )
    assert quarantined[f"{ARCHIVE_OBJECT_ROOT}/sha256/aa/{'a' * 64}"].is_symlink()
    assert publish_pending_archive_objects(sidecar, run_git) is False


def test_quarantine_of_invalid_only_leaves_worktree_clean_without_commit(
    tmp_path: Path,
) -> None:
    _remote, _seed, sidecar = setup_repo(tmp_path)
    head = git(sidecar, "rev-parse", "HEAD").stdout
    stray = sidecar / ARCHIVE_OBJECT_ROOT / "junk.bin"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"junk")

    assert publish_pending_archive_objects(sidecar, run_git) is False

    assert _status(sidecar) == ""
    assert git(sidecar, "rev-parse", "HEAD").stdout == head
    assert not stray.exists()


def test_quarantine_returns_only_the_valid_pending_paths(tmp_path: Path) -> None:
    _remote, _seed, sidecar = setup_repo(tmp_path)
    valid = _write_object(sidecar, b"valid")
    (sidecar / ARCHIVE_OBJECT_ROOT / "junk.bin").write_bytes(b"junk")

    assert quarantine_invalid_pending_objects(sidecar, run_git) == (valid,)
    assert (sidecar / valid).is_file()


def test_prompt_archive_clean_never_resets_or_deletes_objects(
    tmp_path: Path,
) -> None:
    _remote, _seed, sidecar = setup_repo(tmp_path)
    tracked = _write_object(sidecar, b"tracked object")
    git(sidecar, "add", "--", tracked)
    git(sidecar, "commit", "-m", "track object")
    pending = _write_object(sidecar, b"pending object")
    (sidecar / "prompts").mkdir()
    (sidecar / "prompts/stale.md").write_text("regenerable\n")

    assert clean_prompt_archive_worktree(sidecar, run_git) is None

    assert not (sidecar / "prompts/stale.md").exists()
    assert (sidecar / tracked).read_bytes() == b"tracked object"
    assert (sidecar / pending).read_bytes() == b"pending object"


def test_pending_object_the_remote_already_tracks_does_not_block_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(remote), str(other))
    git(other, "config", "user.name", "Other")
    git(other, "config", "user.email", "other@example.test")
    content = b"published from another machine"
    relpath = _write_object(other, content)
    git(other, "add", "--", relpath)
    git(other, "commit", "-m", "publish object elsewhere")
    git(other, "push")
    _write_object(sidecar, content)
    pull = run_git(sidecar, ["pull", "--rebase", "--no-autostash"], network=True)
    assert pull.returncode != 0
    assert "would be overwritten" in pull.stderr

    sync_target = target(tmp_path, remote, sidecar)
    patch_payload_pass(monkeypatch)
    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error is None
    assert _status(sidecar) == ""
    assert _tracked(sidecar) == {relpath}
    assert (sidecar / relpath).read_bytes() == content
    assert not (sidecar / ".git/rebase-merge").exists()
    assert not (sidecar / ".git/rebase-apply").exists()


def test_prompt_archive_publication_survives_remote_tracked_pending_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(remote), str(other))
    git(other, "config", "user.name", "Other")
    git(other, "config", "user.email", "other@example.test")
    content = b"published from another machine"
    relpath = _write_object(other, content)
    git(other, "add", "--", relpath)
    git(other, "commit", "-m", "publish object elsewhere")
    git(other, "push")
    _write_object(sidecar, content)

    sync_target = target(tmp_path, remote, sidecar)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish.resolve_sync_targets",
        lambda _projects: TargetSelection((sync_target,), ()),
    )
    artifacts_dir = tmp_path / "runs/20260801130000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "raw_xprompt.md").write_text("Archive this prompt.\n")
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish._hosted_resolver",
        lambda *_args: None,
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    outcome = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=sync_target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert outcome.error is None and outcome.published
    assert _status(sidecar) == ""
    assert _tracked(sidecar) == {relpath}
    assert git(sidecar, "rev-list", "--count", "@{upstream}..HEAD").stdout == "0\n"

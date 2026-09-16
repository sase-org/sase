"""Real-Git tests for managed workspace object sharing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import sase.workspace_provider.git_objects as git_objects
from sase.core.git_object_sharing import OBSERVATION_CLEAR
from sase.workspace_provider.git_objects import (
    GitObjectSharingError,
    classify_alternate_state,
    dissociate_checkout,
    ensure_sase_alternate,
    git_object_dir,
)
from sase.workspace_provider.utils import (
    ensure_git_clone_at,
    ensure_workspace_checkout,
    non_interactive_git_env,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
    )
    return result.stdout.strip()


def _git_config_missing(cwd: Path, key: str) -> bool:
    result = subprocess.run(
        ["git", "config", "--local", "--get", key],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
    )
    return result.returncode != 0


def _make_primary(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    primary = tmp_path / "primary"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "clone", str(remote), str(primary))
    _git(primary, "config", "user.email", "test@example.com")
    _git(primary, "config", "user.name", "Test User")
    (primary / "file.txt").write_text("one\n", encoding="utf-8")
    _git(primary, "add", "file.txt")
    _git(primary, "commit", "-m", "initial")
    _git(primary, "branch", "-M", "main")
    _git(primary, "push", "-u", "origin", "main")
    return primary, remote


def _make_replacement_primary_without_objects(tmp_path: Path, remote: Path) -> Path:
    replacement = tmp_path / "replacement-primary"
    _git(tmp_path, "init", str(replacement))
    _git(replacement, "config", "user.email", "test@example.com")
    _git(replacement, "config", "user.name", "Test User")
    _git(replacement, "remote", "add", "origin", str(remote))
    return replacement


def test_shared_clone_installs_sase_alternate_and_survives_repack(
    tmp_path: Path,
) -> None:
    primary, remote = _make_primary(tmp_path)
    target = tmp_path / "managed" / "primary_10"

    result = ensure_git_clone_at(
        str(primary),
        10,
        str(target),
        share_git_objects=True,
    )

    assert result == str(target)
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    assert alternates.read_text(encoding="utf-8") == f"{git_object_dir(str(primary))}\n"
    assert _git(primary, "config", "--local", "--get", "gc.pruneExpire") == "never"
    assert _git(target, "config", "--local", "--get", "gc.auto") == "0"
    assert _git(target, "config", "--local", "--get", "maintenance.auto") == "false"
    assert _git(target, "remote", "get-url", "origin") == str(remote)

    _git(primary, "repack", "-a", "-d")
    _git(target, "fsck", "--connectivity-only")
    _git(target, "fetch", "--quiet")


def test_direct_clone_keeps_standalone_behavior_when_sharing_disabled(
    tmp_path: Path,
) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "primary_11"

    ensure_git_clone_at(
        str(primary),
        11,
        str(target),
        share_git_objects=False,
    )

    assert not (git_object_dir(str(target)) / "info" / "alternates").exists()


def test_workspace_checkout_passes_disabled_share_choice(tmp_path: Path) -> None:
    primary, _remote = _make_primary(tmp_path)
    managed_root = tmp_path / "managed-root"
    config = {
        "workspace": {
            "root": str(managed_root),
            "project_key": "demo",
            "share_git_objects": False,
        }
    }

    checkout = Path(ensure_workspace_checkout(str(primary), 12, config=config, env={}))

    assert checkout.is_dir()
    assert not (git_object_dir(str(checkout)) / "info" / "alternates").exists()


def test_relative_alternate_is_resolved_from_object_database(
    tmp_path: Path,
) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "primary_13"
    ensure_git_clone_at(str(primary), 13, str(target), share_git_objects=False)
    primary_objects = git_object_dir(str(primary))
    target_objects = git_object_dir(str(target))
    relative = Path(*Path(primary_objects).resolve().relative_to(tmp_path).parts)
    alternates = target_objects / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(
        f"../../../{relative.as_posix()}\n",
        encoding="utf-8",
    )

    state = classify_alternate_state(str(target), primary_checkout_dir=str(primary))

    assert state.status == "expected"
    assert state.alternates == (str(primary_objects),)


def test_repoint_preserves_foreign_alternates(tmp_path: Path) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "primary_14"
    ensure_git_clone_at(str(primary), 14, str(target), share_git_objects=False)
    old_objects = tmp_path / "old-primary-objects"
    foreign_objects = tmp_path / "foreign-objects"
    old_objects.mkdir()
    foreign_objects.mkdir()
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(
        f"{foreign_objects}\n{old_objects}\n",
        encoding="utf-8",
    )
    _git(target, "config", "--local", "sase.workspaceGitObjects", "true")
    _git(
        target,
        "config",
        "--local",
        "sase.workspaceGitObjectsPrimary",
        str(old_objects),
    )

    ensure_sase_alternate(str(primary), str(target))

    assert alternates.read_text(encoding="utf-8") == (
        f"{foreign_objects}\n{git_object_dir(str(primary))}\n"
    )
    _git(target, "fsck", "--connectivity-only")


def test_primary_among_foreign_alternates_is_not_claimed(
    tmp_path: Path,
) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "primary_15"
    ensure_git_clone_at(str(primary), 15, str(target), share_git_objects=False)
    foreign_objects = tmp_path / "foreign-objects"
    foreign_objects.mkdir()
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    original = f"{foreign_objects}\n{git_object_dir(str(primary))}\n"
    alternates.write_text(original, encoding="utf-8")

    state = classify_alternate_state(str(target), primary_checkout_dir=str(primary))

    assert state.status == "unexpected"
    assert not state.sase_owned
    with pytest.raises(GitObjectSharingError, match="non-SASE alternate"):
        ensure_sase_alternate(str(primary), str(target))
    assert alternates.read_text(encoding="utf-8") == original


def test_dissociate_repoints_then_preserves_foreign_alternates(
    tmp_path: Path,
) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "primary_16"
    ensure_git_clone_at(str(primary), 16, str(target), share_git_objects=False)
    old_objects = tmp_path / "missing-old-primary-objects"
    foreign_objects = tmp_path / "foreign-objects"
    foreign_objects.mkdir()
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(
        f"{foreign_objects}\n{old_objects}\n",
        encoding="utf-8",
    )
    _git(target, "config", "--local", "sase.workspaceGitObjects", "true")
    _git(
        target,
        "config",
        "--local",
        "sase.workspaceGitObjectsPrimary",
        str(old_objects),
    )

    dissociate_checkout(
        str(primary),
        str(target),
        fresh_claim_status=OBSERVATION_CLEAR,
        fresh_occupant_status=OBSERVATION_CLEAR,
    )

    assert alternates.read_text(encoding="utf-8") == f"{foreign_objects}\n"
    assert _git_config_missing(target, "sase.workspaceGitObjects")
    _git(target, "fsck", "--connectivity-only")


def test_failed_repoint_rolls_back_alternate_and_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "primary_17"
    ensure_git_clone_at(str(primary), 17, str(target), share_git_objects=False)
    old_objects = tmp_path / "old-primary-objects"
    old_objects.mkdir()
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    original_alternates = f"{old_objects}\n"
    alternates.write_text(original_alternates, encoding="utf-8")
    _git(target, "config", "--local", "sase.workspaceGitObjects", "true")
    _git(
        target,
        "config",
        "--local",
        "sase.workspaceGitObjectsPrimary",
        str(old_objects),
    )

    def fail_checkout_fsck(checkout_dir: str) -> None:
        if Path(checkout_dir).resolve() == target.resolve():
            raise GitObjectSharingError("simulated checkout fsck failure")

    monkeypatch.setattr(git_objects, "fsck_connectivity", fail_checkout_fsck)

    with pytest.raises(GitObjectSharingError, match="simulated checkout"):
        git_objects.repair_shared_checkout(
            str(primary),
            str(target),
            fresh_claim_status=OBSERVATION_CLEAR,
            fresh_occupant_status=OBSERVATION_CLEAR,
        )

    assert alternates.read_text(encoding="utf-8") == original_alternates
    assert _git(
        target, "config", "--local", "--get", "sase.workspaceGitObjectsPrimary"
    ) == str(old_objects)


def test_reuses_broken_sase_borrower_without_deleting_local_work(
    tmp_path: Path,
) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "managed" / "primary_18"
    ensure_git_clone_at(str(primary), 18, str(target), share_git_objects=True)
    (target / "local-work.txt").write_text("keep me\n", encoding="utf-8")
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    alternates.write_text(
        f"{tmp_path / 'missing-primary' / '.git' / 'objects'}\n",
        encoding="utf-8",
    )

    result = ensure_git_clone_at(str(primary), 18, str(target), share_git_objects=True)

    assert result == str(target)
    assert (target / "local-work.txt").read_text(encoding="utf-8") == "keep me\n"
    assert alternates.read_text(encoding="utf-8") == f"{git_object_dir(str(primary))}\n"
    _git(target, "status", "--porcelain")


def test_reuses_broken_sase_borrower_by_dissociating_when_sharing_disabled(
    tmp_path: Path,
) -> None:
    primary, _remote = _make_primary(tmp_path)
    target = tmp_path / "managed" / "primary_19"
    ensure_git_clone_at(str(primary), 19, str(target), share_git_objects=True)
    (target / "local-work.txt").write_text("keep me\n", encoding="utf-8")
    missing_objects = tmp_path / "missing-primary" / ".git" / "objects"
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    alternates.write_text(f"{missing_objects}\n", encoding="utf-8")
    _git(
        target,
        "config",
        "--local",
        "sase.workspaceGitObjectsPrimary",
        str(missing_objects),
    )

    result = ensure_git_clone_at(str(primary), 19, str(target), share_git_objects=False)

    assert result == str(target)
    assert (target / "local-work.txt").read_text(encoding="utf-8") == "keep me\n"
    assert not alternates.exists()
    assert _git_config_missing(target, "sase.workspaceGitObjects")
    _git(target, "fsck", "--connectivity-only")


def test_dirty_healthy_reuse_refuses_dependency_repoint(
    tmp_path: Path,
) -> None:
    primary, remote = _make_primary(tmp_path)
    target = tmp_path / "managed" / "primary_20"
    ensure_git_clone_at(str(primary), 20, str(target), share_git_objects=True)
    replacement = _make_replacement_primary_without_objects(tmp_path, remote)
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    original_alternates = alternates.read_text(encoding="utf-8")
    original_primary_config = _git(
        target,
        "config",
        "--local",
        "--get",
        "sase.workspaceGitObjectsPrimary",
    )
    (target / "file.txt").write_text("dirty edit\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="clean status"):
        ensure_git_clone_at(
            str(replacement),
            20,
            str(target),
            share_git_objects=True,
        )

    assert alternates.read_text(encoding="utf-8") == original_alternates
    assert (
        _git(
            target,
            "config",
            "--local",
            "--get",
            "sase.workspaceGitObjectsPrimary",
        )
        == original_primary_config
    )
    assert _git(target, "status", "--porcelain") == "M file.txt"


def test_clean_reuse_rolls_back_when_replacement_primary_lacks_objects(
    tmp_path: Path,
) -> None:
    primary, remote = _make_primary(tmp_path)
    target = tmp_path / "managed" / "primary_21"
    ensure_git_clone_at(str(primary), 21, str(target), share_git_objects=True)
    replacement = _make_replacement_primary_without_objects(tmp_path, remote)
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    original_alternates = alternates.read_text(encoding="utf-8")
    original_primary_config = _git(
        target,
        "config",
        "--local",
        "--get",
        "sase.workspaceGitObjectsPrimary",
    )

    with pytest.raises(RuntimeError, match="fsck --connectivity-only failed"):
        ensure_git_clone_at(
            str(replacement),
            21,
            str(target),
            share_git_objects=True,
        )

    assert alternates.read_text(encoding="utf-8") == original_alternates
    assert (
        _git(
            target,
            "config",
            "--local",
            "--get",
            "sase.workspaceGitObjectsPrimary",
        )
        == original_primary_config
    )
    assert _git(target, "status", "--porcelain") == ""
    _git(target, "fsck", "--connectivity-only")


def test_clean_reuse_preserves_unique_local_history_when_repoint_fails(
    tmp_path: Path,
) -> None:
    primary, remote = _make_primary(tmp_path)
    target = tmp_path / "managed" / "primary_22"
    ensure_git_clone_at(str(primary), 22, str(target), share_git_objects=True)
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Test User")
    (target / "local.txt").write_text("local history\n", encoding="utf-8")
    _git(target, "add", "local.txt")
    _git(target, "commit", "-m", "local history")
    local_head = _git(target, "rev-parse", "HEAD")
    replacement = _make_replacement_primary_without_objects(tmp_path, remote)
    alternates = git_object_dir(str(target)) / "info" / "alternates"
    original_alternates = alternates.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError, match="fsck --connectivity-only failed"):
        ensure_git_clone_at(
            str(replacement),
            22,
            str(target),
            share_git_objects=True,
        )

    assert alternates.read_text(encoding="utf-8") == original_alternates
    assert _git(target, "rev-parse", "HEAD") == local_head
    assert _git(target, "status", "--porcelain") == ""
    _git(target, "log", "--oneline", "-1")

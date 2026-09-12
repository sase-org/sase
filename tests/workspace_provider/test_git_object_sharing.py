"""Real-Git tests for managed workspace object sharing."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.workspace_provider.git_objects import git_object_dir
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

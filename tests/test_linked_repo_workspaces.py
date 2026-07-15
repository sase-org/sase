"""Tests for linked repository workspace clone lifecycle behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.linked_repos import (
    clear_workspace_repos,
    materialize_linked_repo_workspace,
)
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


def test_clear_workspace_repos_renames_whole_tree_and_defers_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos = tmp_path / "sase" / "repos"
    (repos / "linked" / "core").mkdir(parents=True)
    (repos / "plans").mkdir()
    (repos / "legacy-junk.txt").write_text("remove", encoding="utf-8")
    popen_calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        "sase.linked_repos.subprocess.Popen",
        lambda args, **kwargs: popen_calls.append((args, kwargs)),
    )

    clear_workspace_repos(tmp_path, 10)

    assert not repos.exists()
    trashed = list((tmp_path / ".sase" / "trash").glob("repos-*"))
    assert len(trashed) == 1
    assert (trashed[0] / "plans").is_dir()
    assert (trashed[0] / "legacy-junk.txt").is_file()
    assert len(popen_calls) == 1
    assert str(trashed[0]) in popen_calls[0][0]
    assert popen_calls[0][1]["start_new_session"] is True


def test_clear_workspace_repos_sweeps_stale_trash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = tmp_path / ".sase" / "trash" / "repos-stale"
    stale.mkdir(parents=True)
    launched: list[list[str]] = []
    monkeypatch.setattr(
        "sase.linked_repos.subprocess.Popen",
        lambda args, **_kwargs: launched.append(args),
    )

    clear_workspace_repos(tmp_path, 10)

    assert launched and str(stale) in launched[0]


@pytest.mark.parametrize("workspace_num", [0, 1])
def test_clear_workspace_repos_preserves_primary_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workspace_num: int
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    plans.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.linked_repos.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("primary guard spawned deletion"),
    )

    clear_workspace_repos(tmp_path, workspace_num)

    assert plans.is_dir()


@pytest.mark.parametrize("shape", ["file", "symlink"])
def test_clear_workspace_repos_removes_non_directory_shapes(
    tmp_path: Path, shape: str
) -> None:
    repos = tmp_path / "sase" / "repos"
    repos.parent.mkdir(parents=True)
    if shape == "file":
        repos.write_text("junk", encoding="utf-8")
    else:
        target = tmp_path / "outside"
        target.mkdir()
        repos.symlink_to(target, target_is_directory=True)

    clear_workspace_repos(tmp_path, 10)

    assert not repos.exists()
    if shape == "symlink":
        assert target.is_dir()


def test_clear_workspace_repos_falls_back_to_synchronous_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos = tmp_path / "sase" / "repos"
    repos.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.linked_repos.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("spawn failed")),
    )

    clear_workspace_repos(tmp_path, 10)

    assert not repos.exists()
    assert list((tmp_path / ".sase" / "trash").iterdir()) == []


def test_clear_workspace_repos_is_noop_when_root_is_absent(tmp_path: Path) -> None:
    clear_workspace_repos(tmp_path, 10)

    assert not (tmp_path / "sase" / "repos").exists()
    assert not (tmp_path / ".sase").exists()


def test_materialize_creates_fresh_linked_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "main_10"
    (host / ".git" / "info").mkdir(parents=True)
    target = host / "sase" / "repos" / "linked" / "core"
    ensured: list[str] = []

    def ensure_clone(_primary: str, _num: int, path: str) -> str:
        ensured.append(path)
        (Path(path) / ".git" / "info").mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at",
        ensure_clone,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_args: None
    )

    result = materialize_linked_repo_workspace(
        primary_dir=str(tmp_path / "core"),
        workspace_dir=str(target),
        workspace_num=10,
    )

    assert result == str(target.resolve())
    assert ensured == [str(target.resolve())]
    host_exclude = host / ".git" / "info" / "exclude"
    assert "/sase/repos/" in host_exclude.read_text(encoding="utf-8").splitlines()
    clone_exclude = target / ".git" / "info" / "exclude"
    assert clone_exclude.read_text(encoding="utf-8").splitlines() == [
        ".sase/",
        "/sase/repos/",
    ]

    materialize_linked_repo_workspace(
        primary_dir=str(tmp_path / "core"),
        workspace_dir=str(target),
        workspace_num=10,
    )

    assert clone_exclude.read_text(encoding="utf-8").splitlines() == [
        ".sase/",
        "/sase/repos/",
    ]


def test_sidecar_materialization_uses_remote_not_divergent_primary(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "research.git"
    primary = tmp_path / "primary-research"
    remote_seed = tmp_path / "remote-seed"
    target = tmp_path / "workspace" / "sase" / "repos" / "research"
    wrong_remote = tmp_path / "wrong.git"
    init_bare_repo(remote)
    clone(remote, primary)
    readme = primary / "README.md"
    readme.write_text("initial\n", encoding="utf-8")
    commit_all(primary, "Initialize research")
    git(["push", "-u", "origin", "main"], primary)
    clone(remote, remote_seed)

    readme.write_text("durable primary only\n", encoding="utf-8")
    commit_all(primary, "Unpushed durable-primary research")
    primary_only_head = git(["rev-parse", "HEAD"], primary).stdout.strip()
    (remote_seed / "README.md").write_text("authoritative remote\n", encoding="utf-8")
    commit_all(remote_seed, "Advance research remote incompatibly")
    git(["push"], remote_seed)
    remote_head = git(["rev-parse", "HEAD"], remote_seed).stdout.strip()

    target.mkdir(parents=True)
    git(["init", "-q"], target)
    git(["remote", "add", "origin", str(wrong_remote)], target)
    (target / "stale.txt").write_text("wrong clone\n", encoding="utf-8")
    commit_all(target, "Commit stale workspace content")

    result = materialize_linked_repo_workspace(
        primary_dir=str(primary),
        workspace_dir=str(target),
        workspace_num=10,
        expected_remote_url=str(remote),
    )

    assert result == str(target.resolve())
    assert not (target / "stale.txt").exists()
    assert (target / "README.md").read_text(encoding="utf-8") == (
        "authoritative remote\n"
    )
    assert git(["rev-parse", "HEAD"], target).stdout.strip() == remote_head
    assert (
        primary_only_head not in git(["rev-list", "--all"], target).stdout.splitlines()
    )
    assert git(["status", "--porcelain"], target).stdout == ""
    assert not (target / ".git" / "rebase-merge").exists()
    assert not (target / ".git" / "rebase-apply").exists()
    assert git(["remote", "get-url", "origin"], target).stdout.strip() == str(remote)

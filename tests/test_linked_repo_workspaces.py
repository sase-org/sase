"""Tests for linked repository workspace clone lifecycle behavior."""

from __future__ import annotations

import errno
from pathlib import Path
import shutil

import pytest

from sase.linked_repos import (
    clear_linked_repo_clones,
    materialize_linked_repo_workspace,
)


def test_clear_linked_repo_clones_stashes_directories_and_removes_strays(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "sase" / "repos" / "linked"
    cached = tmp_path / "sase" / "repos" / ".linked-cache" / "core"
    core = linked / "core"
    core.mkdir(parents=True)
    (core / "new.txt").write_text("new", encoding="utf-8")
    cached.mkdir(parents=True)
    (cached / "old.txt").write_text("old", encoding="utf-8")
    (linked / "stray.txt").write_text("remove", encoding="utf-8")

    clear_linked_repo_clones(tmp_path)

    assert list(linked.iterdir()) == []
    assert (cached / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (cached / "old.txt").exists()


def test_clear_linked_repo_clones_is_noop_when_root_is_absent(tmp_path: Path) -> None:
    clear_linked_repo_clones(tmp_path)

    assert not (tmp_path / "sase" / "repos").exists()


def test_materialize_restores_linked_clone_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "main_10"
    (host / ".git" / "info").mkdir(parents=True)
    cached = host / "sase" / "repos" / ".linked-cache" / "core"
    cached.mkdir(parents=True)
    (cached / "cached.txt").write_text("cached", encoding="utf-8")
    target = host / "sase" / "repos" / "linked" / "core"
    ensured: list[str] = []
    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at",
        lambda _primary, _num, path: ensured.append(path) or path,
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
    assert (target / "cached.txt").read_text(encoding="utf-8") == "cached"
    assert not cached.exists()
    exclude = host / ".git" / "info" / "exclude"
    assert "/sase/repos/" in exclude.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "race_error",
    [
        FileNotFoundError(),
        OSError(errno.EEXIST, "parallel destination"),
        OSError(errno.ENOTEMPTY, "parallel destination"),
    ],
)
def test_materialize_cache_restore_rename_race_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race_error: OSError
) -> None:
    host = tmp_path / "main_10"
    cached = host / "sase" / "repos" / ".linked-cache" / "core"
    cached.mkdir(parents=True)
    target = host / "sase" / "repos" / "linked" / "core"
    ensured: list[str] = []

    def racing_rename(source: object, _destination: object) -> None:
        if Path(source) == cached:
            raise race_error
        raise AssertionError(f"unexpected rename source: {source}")

    monkeypatch.setattr("sase.linked_repos.os.rename", racing_rename)
    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at",
        lambda _primary, _num, path: ensured.append(path) or path,
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


def test_materialize_corrupt_cached_clone_is_recreated_by_clone_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "main_10"
    cached = host / "sase" / "repos" / ".linked-cache" / "core"
    cached.mkdir(parents=True)
    (cached / "not-a-repo.txt").write_text("corrupt", encoding="utf-8")
    target = host / "sase" / "repos" / "linked" / "core"

    def recreate_corrupt_clone(_primary: str, _num: int, path: str) -> str:
        clone = Path(path)
        assert (clone / "not-a-repo.txt").is_file()
        shutil.rmtree(clone)
        clone.mkdir(parents=True)
        (clone / ".git").mkdir()
        return path

    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at", recreate_corrupt_clone
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
    assert (target / ".git").is_dir()
    assert not (target / "not-a-repo.txt").exists()

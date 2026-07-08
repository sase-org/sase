"""Tests for ``sase sdd migrate`` helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.sdd.migrate import SddMigrationError, migrate_sdd_to_separate_repo
from sase.sdd.store import _record_cache


def _completed(
    args: list[str] | None = None,
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args or [], returncode, stdout, stderr)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def _clear_record_cache() -> None:
    _record_cache.clear()
    yield
    _record_cache.clear()


def test_migrate_local_store_connects_remote_and_writes_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    local_sdd = tmp_path / ".sase" / "sdd"
    local_sdd.mkdir(parents=True)
    (local_sdd / "research.md").write_text("notes\n", encoding="utf-8")
    git_calls: list[list[str]] = []
    committed: list[Path] = []

    def fake_run_git(
        args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        git_calls.append(args)
        if args == ["config", "--get", "remote.origin.url"]:
            return _completed(args, returncode=1)
        return _completed(args)

    def fake_create_remote(
        primary_workspace_dir: str,
        workspace_dir: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        assert primary_workspace_dir == str(tmp_path)
        assert workspace_dir == str(tmp_path)
        assert options["create"] is True
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": "git@github.com:acme/widget-sdd.git",
            "discovery": "found",
        }

    def fake_commit(store: object, *_args: object, **_kwargs: object) -> bool:
        committed.append(store.sdd_dir)
        return True

    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "local"}},
    )
    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", fake_create_remote)
    monkeypatch.setattr("sase.sdd.migrate.run_sdd_git", fake_run_git)
    monkeypatch.setattr("sase.sdd.migrate._push_with_upstream", lambda _repo: True)
    monkeypatch.setattr(
        "sase.sdd.migrate._ensure_bead_store_initialized", lambda _sdd_dir: []
    )
    monkeypatch.setattr("sase.sdd._commit.commit_sdd_store_files", fake_commit)

    result = migrate_sdd_to_separate_repo(tmp_path, create=True)

    assert result.record.repo == "acme/widget-sdd"
    assert result.pushed is True
    assert committed == [local_sdd]
    assert [
        "remote",
        "add",
        "origin",
        "git@github.com:acme/widget-sdd.git",
    ] in git_calls
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  storage: separate_repo\n"
    )
    raw_record = json.loads((tmp_path / ".sase" / "sdd-store.json").read_text())
    assert raw_record["remote_url"] == "git@github.com:acme/widget-sdd.git"


def test_migrate_rerun_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    local_sdd = tmp_path / ".sase" / "sdd"
    local_sdd.mkdir(parents=True)
    (local_sdd / "research.md").write_text("notes\n", encoding="utf-8")
    git_calls: list[list[str]] = []
    create_calls = 0
    origin_url: str | None = None
    remote_url = "git@github.com:acme/widget-sdd.git"

    def fake_config() -> dict[str, dict[str, str]]:
        config_path = tmp_path / "sase.yml"
        if config_path.exists() and "storage: separate_repo" in config_path.read_text(
            encoding="utf-8"
        ):
            return {"sdd": {"storage": "separate_repo"}}
        return {"sdd": {"storage": "local"}}

    def fake_create_remote(
        _primary_workspace_dir: str,
        _workspace_dir: str,
        _options: dict[str, object],
    ) -> dict[str, object]:
        nonlocal create_calls
        create_calls += 1
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": remote_url,
            "discovery": "found",
        }

    def fake_run_git(
        args: list[str], *, cwd: Path, **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        nonlocal origin_url
        git_calls.append(args)
        if args == ["init"]:
            (cwd / ".git").mkdir(parents=True)
            return _completed(args)
        if args == ["config", "--get", "remote.origin.url"]:
            if origin_url is None:
                return _completed(args, returncode=1)
            return _completed(args, stdout=f"{origin_url}\n")
        if args == ["remote", "add", "origin", remote_url]:
            origin_url = remote_url
            return _completed(args)
        return _completed(args)

    monkeypatch.setattr("sase.sdd.store.load_merged_config", fake_config)
    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", fake_create_remote)
    monkeypatch.setattr("sase.sdd.migrate.run_sdd_git", fake_run_git)
    monkeypatch.setattr("sase.sdd.migrate._push_with_upstream", lambda _repo: True)
    monkeypatch.setattr(
        "sase.sdd.migrate._ensure_bead_store_initialized", lambda _sdd_dir: []
    )
    monkeypatch.setattr(
        "sase.sdd._commit.commit_sdd_store_files",
        lambda *_args, **_kwargs: False,
    )

    first = migrate_sdd_to_separate_repo(tmp_path, create=True)
    second = migrate_sdd_to_separate_repo(tmp_path, create=True)

    assert first.record == second.record
    assert second.source_storage == "separate_repo"
    assert create_calls == 1
    assert [
        call for call in git_calls if call == ["remote", "add", "origin", remote_url]
    ] == [["remote", "add", "origin", remote_url]]
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  storage: separate_repo\n"
    )
    raw_record = json.loads((tmp_path / ".sase" / "sdd-store.json").read_text())
    assert raw_record["repo"] == "acme/widget-sdd"
    assert raw_record["remote_url"] == remote_url


def test_migrate_in_tree_copies_sdd_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    source = tmp_path / "sdd" / "research"
    source.mkdir(parents=True)
    (source / "note.md").write_text("notes\n", encoding="utf-8")

    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "in_tree"}},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.create_sdd_remote",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": "git@github.com:acme/widget-sdd.git",
            "discovery": "found",
        },
    )
    monkeypatch.setattr(
        "sase.sdd.migrate.run_sdd_git",
        lambda args, **_kwargs: _completed(
            args,
            returncode=1 if args == ["config", "--get", "remote.origin.url"] else 0,
        ),
    )
    monkeypatch.setattr("sase.sdd.migrate._push_with_upstream", lambda _repo: True)
    monkeypatch.setattr(
        "sase.sdd.migrate._ensure_bead_store_initialized", lambda _sdd_dir: []
    )
    monkeypatch.setattr(
        "sase.sdd._commit.commit_sdd_store_files",
        lambda *_args, **_kwargs: True,
    )

    migrate_sdd_to_separate_repo(tmp_path)

    assert (tmp_path / ".sase" / "sdd" / "research" / "note.md").read_text(
        encoding="utf-8"
    ) == "notes\n"


def test_migrate_remove_in_tree_commit_contains_only_sdd_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "sase-test@example.invalid")
    _git(tmp_path, "config", "user.name", "SASE Test")
    source = tmp_path / "sdd" / "research"
    source.mkdir(parents=True)
    (source / "note.md").write_text("notes\n", encoding="utf-8")
    app = tmp_path / "src" / "app.py"
    app.parent.mkdir()
    app.write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", "sdd", "src")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    app.write_text("dirty\n", encoding="utf-8")

    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "in_tree"}},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.create_sdd_remote",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": "git@github.com:acme/widget-sdd.git",
            "discovery": "found",
        },
    )
    monkeypatch.setattr("sase.sdd.migrate._push_with_upstream", lambda _repo: True)
    monkeypatch.setattr(
        "sase.sdd.migrate._ensure_bead_store_initialized", lambda _sdd_dir: []
    )
    monkeypatch.setattr(
        "sase.sdd._commit.commit_sdd_store_files",
        lambda *_args, **_kwargs: True,
    )

    result = migrate_sdd_to_separate_repo(tmp_path, remove_in_tree=True)

    assert result.removed_in_tree is True
    changed_paths = _git(
        tmp_path, "show", "--name-only", "--format=", "HEAD"
    ).stdout.splitlines()
    assert changed_paths == ["sdd/research/note.md"]
    assert (tmp_path / "src" / "app.py").read_text(encoding="utf-8") == "dirty\n"


def test_migrate_without_existing_remote_points_at_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".sase" / "sdd").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "local"}},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.create_sdd_remote",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": "git@github.com:acme/widget-sdd.git",
            "discovery": "not_found",
        },
    )

    with pytest.raises(SddMigrationError, match="--create"):
        migrate_sdd_to_separate_repo(tmp_path)

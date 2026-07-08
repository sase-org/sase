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

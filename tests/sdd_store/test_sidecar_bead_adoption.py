"""Bead-sidecar initialization and record-last adoption coverage."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
import subprocess

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd._sidecar_init import SidecarInitSpec, initialize_sidecars
from sase.sdd._store_records import (
    read_sdd_store_record,
    write_sdd_store_record,
)
from sase.sdd._store_types import SddMaterializationError

from ._sidecar_init_helpers import bare_remote, configure_git_environment, git

_ROLES = ("plans", "research", "beads")


def _git_output(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _configure_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    legacy_state: bool,
) -> tuple[Path, dict[str, Path], dict[str, Path], tuple[SidecarInitSpec, ...]]:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    remotes = {role: bare_remote(tmp_path, f"widget--{role}") for role in _ROLES}
    clones = {role: tmp_path / f"clone-{role}" for role in _ROLES}

    if legacy_state:
        seed = tmp_path / "plans-seed"
        git(tmp_path, "clone", str(remotes["plans"]), str(seed))
        (seed / ".gitignore").write_text(
            "keep-this\nbeads/beads.db\nbeads/beads.db-shm\nbeads/beads.db-wal\n"
        )
        with BeadProject.init(seed, beads_dirname="beads") as bead_project:
            bead_project.create("Migrated issue", IssueType.PLAN)
        git(seed, "add", ".")
        git(seed, "commit", "-m", "Seed plans-owned bead state")
        git(seed, "push", "origin", "HEAD")
        git(tmp_path, "clone", str(remotes["plans"]), str(clones["plans"]))
        (clones["plans"] / "beads" / "beads.db").write_text("local cache\n")

        write_sdd_store_record(
            project,
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "provider": "github",
                "host": "github.com",
                "sidecars": {
                    role: {
                        "repo": f"acme/widget--{role}",
                        "remote_url": str(remotes[role]),
                    }
                    for role in ("plans", "research")
                },
            },
        )

    def create_remote(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        role = str(options["sdd_sidecar_suffix"])
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": f"acme/widget--{role}",
            "remote_url": str(remotes[role]),
            "discovery": "found",
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, role: str(clones[role]),
    )
    specs = tuple(SidecarInitSpec(role=role) for role in _ROLES)
    return project, remotes, clones, specs


def _assert_schema_three(project: Path) -> None:
    record = read_sdd_store_record(project)
    assert record is not None
    assert record.schema_version == 3
    assert record.beads is not None
    persisted = json.loads((project / ".sase" / "sdd-store.json").read_text())
    assert persisted["schema_version"] == 3
    assert set(persisted["sidecars"]) == {"plans", "research", "beads"}


def _fresh_remote_clone(tmp_path: Path, remote: Path, name: str) -> Path:
    clone = tmp_path / name
    git(tmp_path, "clone", str(remote), str(clone))
    return clone


def test_fresh_init_records_and_seeds_root_beads_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _remotes, clones, specs = _configure_transaction(
        tmp_path,
        monkeypatch,
        legacy_state=False,
    )

    initialize_sidecars(project, 1, specs)

    _assert_schema_three(project)
    assert (clones["beads"] / ".gitignore").read_text().splitlines() == [
        "beads.db",
        "beads.db-shm",
        "beads.db-wal",
    ]
    assert not (clones["plans"] / "beads").exists()
    assert not (clones["plans"] / ".gitignore").exists()


def test_migration_imports_pushes_cleans_and_reruns_without_new_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, remotes, clones, specs = _configure_transaction(
        tmp_path,
        monkeypatch,
        legacy_state=True,
    )

    initialize_sidecars(project, 1, specs)

    _assert_schema_three(project)
    assert (clones["beads"] / "config.json").is_file()
    assert (clones["beads"] / "issues.jsonl").is_file()
    assert (clones["beads"] / "events" / "manifest.json").is_file()
    assert not (clones["beads"] / "beads.db").exists()
    assert not (clones["plans"] / "beads").exists()
    assert (clones["plans"] / ".gitignore").read_text() == "keep-this\n"
    import_message = _git_output(clones["beads"], "log", "-1", "--format=%B")
    assert "Import bead state from acme/widget--plans@" in import_message

    remote_beads = _fresh_remote_clone(tmp_path, remotes["beads"], "remote-beads")
    assert (remote_beads / "events" / "manifest.json").is_file()
    heads = {role: _git_output(clones[role], "rev-parse", "HEAD") for role in _ROLES}

    initialize_sidecars(project, 1, specs)

    assert {
        role: _git_output(clones[role], "rev-parse", "HEAD") for role in _ROLES
    } == heads


def test_migration_accepts_minimal_config_and_projection_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _remotes, clones, specs = _configure_transaction(
        tmp_path,
        monkeypatch,
        legacy_state=True,
    )
    shutil.rmtree(clones["plans"] / "beads" / "events")
    metadata = clones["plans"] / "beads" / "metadata.json"
    if metadata.exists():
        metadata.unlink()
    git(clones["plans"], "add", "-A")
    git(clones["plans"], "commit", "-m", "Keep only the minimal bead store")
    git(clones["plans"], "push", "origin", "HEAD")

    initialize_sidecars(project, 1, specs)

    _assert_schema_three(project)
    assert (clones["beads"] / "config.json").is_file()
    assert (clones["beads"] / "issues.jsonl").is_file()
    assert not (clones["beads"] / "events").exists()
    assert not (clones["plans"] / "beads").exists()


def test_failed_import_push_preserves_schema_two_and_rerun_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, _remotes, clones, specs = _configure_transaction(
        tmp_path,
        monkeypatch,
        legacy_state=True,
    )
    from sase.sdd import _bead_adoption

    real_push = _bead_adoption.push_sidecar
    beads_pushes = 0

    def fail_import_push(root: Path) -> None:
        nonlocal beads_pushes
        if root == clones["beads"]:
            beads_pushes += 1
            if beads_pushes == 1:
                raise SddMaterializationError("simulated import push failure")
        real_push(root)

    monkeypatch.setattr(_bead_adoption, "push_sidecar", fail_import_push)

    with pytest.raises(SddMaterializationError, match="simulated import push"):
        initialize_sidecars(project, 1, specs)

    record = read_sdd_store_record(project)
    assert record is not None
    assert record.schema_version == 2
    assert record.beads is None
    assert (clones["plans"] / "beads").is_dir()

    monkeypatch.setattr(_bead_adoption, "push_sidecar", real_push)
    initialize_sidecars(project, 1, specs)

    _assert_schema_three(project)
    assert not (clones["plans"] / "beads").exists()


def test_failed_cleanup_push_warns_and_next_run_pushes_existing_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project, remotes, clones, specs = _configure_transaction(
        tmp_path,
        monkeypatch,
        legacy_state=True,
    )
    from sase.sdd import _bead_adoption

    real_push = _bead_adoption.push_sidecar

    def fail_post_switch_plans_push(root: Path) -> None:
        record = read_sdd_store_record(project)
        if root == clones["plans"] and record is not None and record.has_split_beads:
            raise SddMaterializationError("simulated cleanup push failure")
        real_push(root)

    monkeypatch.setattr(
        _bead_adoption,
        "push_sidecar",
        fail_post_switch_plans_push,
    )
    caplog.set_level(logging.WARNING)

    initialize_sidecars(project, 1, specs)

    _assert_schema_three(project)
    assert "plans-side cleanup failed" in caplog.text
    stale_remote = _fresh_remote_clone(tmp_path, remotes["plans"], "stale-plans")
    assert (stale_remote / "beads").is_dir()

    monkeypatch.setattr(_bead_adoption, "push_sidecar", real_push)
    initialize_sidecars(project, 1, specs)

    updated_remote = _fresh_remote_clone(tmp_path, remotes["plans"], "updated-plans")
    assert not (updated_remote / "beads").exists()

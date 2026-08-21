"""Repository-creation coverage for sidecar initialization."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.sdd._sidecar_init import (
    SidecarInitSpec,
    initialize_materialized_sidecars,
    initialize_sidecars,
)
from sase.sdd._store_records import read_sdd_store_record

from ._sidecar_init_helpers import bare_remote, configure_git_environment


def _has_head(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_custom_sidecar_init_uses_pinned_private_provider_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    remote = bare_remote(tmp_path, "shared-artifacts")
    clone = tmp_path / "artifacts-clone"
    captured: list[dict[str, object]] = []
    spec = SidecarInitSpec(
        role="artifacts",
        repo="acme/shared-artifacts",
        remote_url=str(remote),
        visibility="private",
        description="Durable build artifacts.",
    )

    def create_remote(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        captured.append(options)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/shared-artifacts",
            "remote_url": str(remote),
            "discovery": "found",
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _role: str(clone),
    )

    outcome = initialize_sidecars(
        project,
        1,
        (spec,),
        creation_authorized={"artifacts": True},
    )

    assert outcome.created == frozenset({"artifacts"})
    assert outcome.record is None
    assert (clone / "README.md").is_file()
    assert captured[0]["sdd_repo"] == "acme/shared-artifacts"
    assert captured[0]["sdd_visibility"] == "private"
    assert captured[0]["sdd_creation_authorized"] is True


def test_split_init_creates_both_repos_before_writing_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "sase.yml").write_text("is_sase_managed: true\n")
    remotes = {kind: bare_remote(tmp_path, kind) for kind in ("plans", "research")}
    clones = {kind: tmp_path / f"widget--{kind}" for kind in remotes}
    calls: list[tuple[str, bool]] = []

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
    ) -> dict[str, object]:
        kind = str(options["sdd_sidecar_suffix"])
        calls.append((kind, options["sdd_creation_authorized"] is True))
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": f"acme/widget--{kind}",
            "remote_url": str(remotes[kind]),
            "discovery": "found",
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, kind: str(clones[kind]),
    )

    outcome = initialize_sidecars(
        project,
        1,
        (SidecarInitSpec(role="plans"), SidecarInitSpec(role="research")),
        creation_authorized={"plans": True, "research": True},
    )

    assert calls == [("plans", True), ("research", True)]
    assert outcome.created == frozenset({"plans", "research"})
    record = read_sdd_store_record(project)
    assert record is not None and record.is_sidecar_storage
    assert record.plans is not None and record.plans.repo == "acme/widget--plans"
    assert record.sidecar_for_kind("research") is not None
    assert (clones["plans"] / "README.md").is_file()
    assert (clones["plans"] / ".gitignore").read_text().splitlines() == [
        "beads/beads.db",
        "beads/beads.db-shm",
        "beads/beads.db-wal",
        "beads/.bead-mutation-lock.holder",
        "/links/**/*.lock",
    ]
    assert (clones["research"] / "README.md").is_file()
    assert (clones["research"] / ".gitignore").read_text().splitlines() == [
        "/links/**/*.lock",
    ]


def test_split_init_no_publish_writes_plans_and_beads_without_commits_or_pushes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    roles = ("plans", "beads")
    remotes = {role: bare_remote(tmp_path, role) for role in roles}
    clones = {role: tmp_path / f"widget--{role}" for role in roles}

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
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
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, role: str(clones[role]),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.push_sidecar",
        lambda _root: pytest.fail("--no-commit must not push sidecars"),
    )

    initialize_sidecars(
        project,
        1,
        tuple(SidecarInitSpec(role=role) for role in roles),
        creation_authorized=dict.fromkeys(roles, True),
        publish_sidecar_changes=False,
    )

    assert (clones["plans"] / "README.md").is_file()
    assert (clones["plans"] / ".gitignore").read_text().splitlines() == [
        "/links/**/*.lock",
    ]
    assert (clones["beads"] / "README.md").is_file()
    assert (clones["beads"] / ".gitignore").is_file()
    assert "/links/**/*.lock" not in (clones["beads"] / ".gitignore").read_text()
    assert not _has_head(clones["plans"])
    assert not _has_head(clones["beads"])
    for remote in remotes.values():
        result = subprocess.run(
            ["git", "--git-dir", str(remote), "show-ref"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1


def test_split_init_materializes_plans_and_custom_role_without_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    roles = ("plans", "designs")
    remotes = {role: bare_remote(tmp_path, role) for role in roles}
    clones = {role: tmp_path / f"widget--{role}" for role in roles}

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
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
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, role: str(clones[role]),
    )

    outcome = initialize_sidecars(
        project,
        1,
        tuple(SidecarInitSpec(role=role) for role in roles),
        creation_authorized=dict.fromkeys(roles, True),
    )

    assert outcome.record is not None
    assert set(outcome.record.sidecars) == {"plans", "designs"}
    assert outcome.record.sidecar_for_kind("research") is None
    assert outcome.store is not None
    assert outcome.store.kind_root("designs") == clones["designs"]
    assert outcome.store.repo_root_for_kind("designs") == clones["designs"]
    assert set(
        json.loads((project / ".sase" / "sdd-store.json").read_text())["sidecars"]
    ) == {"plans", "designs"}


def test_agents_init_uses_hidden_root_and_records_every_sidecar_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    remotes = {
        role: bare_remote(tmp_path, role) for role in ("plans", "research", "agents")
    }
    visible_clones = {
        role: tmp_path / f"widget--{role}" for role in ("plans", "research")
    }
    state_root = tmp_path / "state"
    captured: list[tuple[str, str, bool]] = []
    monkeypatch.setenv("SASE_HOME", str(state_root))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: "gh_acme__widget",
    )

    def create_remote(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        role = str(options["sdd_sidecar_suffix"])
        captured.append(
            (
                role,
                str(options["sdd_visibility"]),
                options["sdd_creation_authorized"] is True,
            )
        )
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": f"acme/widget--{role}",
            "remote_url": str(remotes[role]),
            "discovery": "found",
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, role: str(visible_clones[role]),
    )
    specs = (
        SidecarInitSpec(role="plans"),
        SidecarInitSpec(role="research"),
        SidecarInitSpec(
            role="agents",
            visibility="private",
            description="Private commit-associated agents.",
        ),
    )

    outcome = initialize_sidecars(
        project,
        1,
        specs,
        creation_authorized={"plans": True, "research": True, "agents": True},
    )

    agents_root = state_root / "projects" / "gh_acme__widget" / "repos" / "agents"
    assert captured == [
        ("plans", "public", True),
        ("research", "public", True),
        ("agents", "private", True),
    ]
    assert outcome.roots == {**visible_clones, "agents": agents_root}
    assert outcome.created == frozenset({"plans", "research", "agents"})
    assert (agents_root / "README.md").is_file()
    directory_map = agents_root / "assets" / "agents-directory-map.png"
    assert directory_map.is_file()
    assert json.loads((agents_root / "schema.json").read_text()) == {
        "schema_version": 2,
        "format": "sase-agents-sidecar",
        "authority": "owner-sharded",
        "relationship_schema_version": 2,
    }
    assert (agents_root / "agents" / ".gitkeep").is_file()
    assert (agents_root / "families" / ".gitkeep").is_file()
    assert (agents_root / "users" / ".gitkeep").is_file()
    assert not (project / "sase" / "repos" / "agents").exists()

    record = read_sdd_store_record(project)
    assert record is not None and record.is_sidecar_storage
    assert record.plans is not None
    assert record.sidecar_for_kind("research") is not None
    assert record.sidecar_for_kind("agents") is not None
    persisted = json.loads((project / ".sase" / "sdd-store.json").read_text())
    assert set(persisted["sidecars"]) == {"plans", "research", "agents"}

    roots = initialize_materialized_sidecars(project, (specs[-1],))
    assert roots == {"agents": agents_root}

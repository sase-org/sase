from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase import (
    artifact_ref_context,
    artifact_ref_entity_context,
    artifact_refs,
)
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefProject,
)
from sase.sdd.store import SDD_STORAGE_SIDECAR_REPOS, SddStore


def _projects() -> tuple[ArtifactRefProject, ...]:
    return (
        ArtifactRefProject("alpha", "gh_example__alpha"),
        ArtifactRefProject("sase", "gh_sase-org__sase"),
        ArtifactRefProject("omega", "gh_example__omega"),
    )


def _store(beads: Path) -> SddStore:
    plans = beads.parent / "plans"
    return SddStore(
        storage=SDD_STORAGE_SIDECAR_REPOS,
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )


def test_entity_context_matches_provider_slug_with_multiple_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    beads = tmp_path / "beads"
    agents = tmp_path / "agents"
    beads.mkdir()
    agents.mkdir()
    (beads / "config.json").write_text(
        json.dumps({"issue_prefix": "sase"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        artifact_ref_entity_context,
        "hidden_sidecar_clone_dir",
        lambda project_key, _role: agents if project_key == "gh_sase-org__sase" else "",
    )
    monkeypatch.setattr(
        "sase.config.get_agent_owner_identity",
        lambda: SimpleNamespace(username="alice", machine_name="athena"),
    )

    assert artifact_ref_entity_context.collect_entity_context(
        _store(beads),
        "sase-org/sase",
        _projects(),
    ) == (
        (ArtifactRefBeadStore("sase", "sase", beads),),
        (ArtifactRefAgentRoot("sase", agents),),
        ArtifactRefAgentOwner("alice", "athena"),
    )


def test_entity_context_logs_unknown_project_without_raising(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=artifact_ref_entity_context.__name__):
        bead_stores, agent_roots, _owner = (
            artifact_ref_entity_context.collect_entity_context(
                _store(tmp_path / "missing-beads"),
                "unknown/provider",
                _projects(),
            )
        )

    assert bead_stores == ()
    assert agent_roots == ()
    assert "unknown/provider" in caplog.text


def test_workspace_project_ref_prefers_project_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = SimpleNamespace(project_key="sase-org/sase", project_name="sase")
    monkeypatch.setattr(
        "sase.workspace_provider.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )

    assert artifact_ref_context._workspace_project_ref(tmp_path) == "sase"


def test_workspace_context_resolves_entities_with_multiple_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    beads = tmp_path / "beads"
    agents = tmp_path / "agents"
    bead_page = beads / "pages" / "sase-b2" / "README.md"
    agent_page = agents / "agents" / "alice.athena.sase-b2.9" / "README.md"
    workspace.mkdir()
    bead_page.parent.mkdir(parents=True)
    agent_page.parent.mkdir(parents=True)
    (beads / "config.json").write_text(
        json.dumps({"issue_prefix": "sase"}),
        encoding="utf-8",
    )
    bead_page.write_text("# Bead\n", encoding="utf-8")
    agent_page.write_text("# Agent\n", encoding="utf-8")

    records = [
        SimpleNamespace(
            project_name=project.key,
            display_name=project.name,
            aliases=list(project.aliases),
        )
        for project in _projects()
    ]
    marker = SimpleNamespace(project_key="sase-org/sase", project_name="sase")
    monkeypatch.setattr(
        artifact_ref_context,
        "resolve_sdd_store",
        lambda *_: _store(beads),
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "collect_repo_inventory",
        lambda **_: SimpleNamespace(records=()),
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "list_project_records",
        lambda *_args, **_kwargs: records,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.find_marker_from_cwd",
        lambda _cwd: (str(workspace), marker),
    )
    monkeypatch.setattr(
        artifact_ref_entity_context,
        "hidden_sidecar_clone_dir",
        lambda project_key, _role: agents if project_key == "gh_sase-org__sase" else "",
    )
    monkeypatch.setattr(
        "sase.config.get_agent_owner_identity",
        lambda: SimpleNamespace(username="alice", machine_name="athena"),
    )

    context = artifact_refs.artifact_ref_context(workspace, 16)

    assert context.selected_project == "sase"
    bead = artifact_refs.resolve_artifact_ref("bead:sase-b2", context=context)
    agent = artifact_refs.resolve_artifact_ref("agent:sase-b2.9", context=context)
    assert bead.status == "exact"
    assert bead.resolved_path == bead_page
    assert agent.status == "exact"
    assert agent.resolved_path == agent_page

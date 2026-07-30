from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase import artifact_ref_context, artifact_ref_entity_context, artifact_refs
from sase.artifact_refs import (
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)

from .helpers import context as make_context


def test_context_assembles_dynamic_document_role_and_namespaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Store:
        def split_sidecar_roles(self) -> tuple[str, ...]:
            return ("plans", "designs", "beads")

        def kind_root(self, role: str) -> Path:
            if role == "designs":
                return tmp_path / "missing-designs-clone"
            if role == "plans":
                return tmp_path / "repo-plans"
            raise ValueError(role)

    repo = SimpleNamespace(name="sase", slug="sase-org/sase")
    inventory = SimpleNamespace(records=(repo,))
    project_record = SimpleNamespace(
        project_name="gh_sase-org__sase",
        display_name="sase",
        aliases=["core-ui"],
    )
    bead_store = ArtifactRefBeadStore("sase", "sase", tmp_path / "beads")
    agent_root = ArtifactRefAgentRoot("sase", tmp_path / "agents")
    agent_owner = ArtifactRefAgentOwner("alice", "athena")
    monkeypatch.setattr(artifact_ref_context, "resolve_sdd_store", lambda *_: _Store())
    monkeypatch.setattr(
        artifact_ref_context,
        "collect_repo_inventory",
        lambda **_: inventory,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "list_project_records",
        lambda *_args, **_kwargs: [project_record],
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "effective_project_name",
        lambda record: record.display_name,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "sase_subdir",
        lambda name: tmp_path / "state" / name,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "default_artifact_files_index_path",
        lambda: tmp_path / "artifact-index.jsonl",
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "collect_entity_context",
        lambda store, project_ref, projects: (
            (bead_store,),
            (agent_root,),
            agent_owner,
        ),
    )

    context = artifact_refs.artifact_ref_context(tmp_path / "workspace", 7)

    assert [(entry.kind, entry.root) for entry in context.document_roots] == [
        ("plans", (tmp_path / "repo-plans").resolve()),
        ("plans", (tmp_path / "state" / "plans").resolve()),
        ("designs", (tmp_path / "missing-designs-clone").resolve()),
    ]
    assert context.known_kinds == (
        "commit",
        "chat",
        "bug",
        "file",
        "bead",
        "agent",
        "plans",
        "designs",
    )
    assert context.repositories[0].name == "sase"
    assert context.projects[0] == ArtifactRefProject(
        name="sase",
        key="gh_sase-org__sase",
        aliases=("core-ui",),
    )
    assert context.bead_stores == (bead_store,)
    assert context.agent_roots == (agent_root,)
    assert context.agent_owner == agent_owner


def test_entity_context_discovers_only_available_local_sidecars(
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
    (beads / "issues.jsonl").write_text(
        "not read by context discovery", encoding="utf-8"
    )

    store = SimpleNamespace(kind_root=lambda role: beads)
    monkeypatch.setattr(
        artifact_ref_entity_context,
        "hidden_sidecar_clone_dir",
        lambda project_key, role: str(agents),
    )
    monkeypatch.setattr(
        "sase.config.get_agent_owner_identity",
        lambda: SimpleNamespace(username="alice", machine_name="athena"),
    )

    assert artifact_ref_entity_context._collect_bead_stores(store, "sase") == (
        ArtifactRefBeadStore("sase", "sase", beads),
    )
    assert artifact_ref_entity_context._collect_agent_roots(
        "gh_sase-org__sase",
        "sase",
    ) == (ArtifactRefAgentRoot("sase", agents),)
    assert artifact_ref_entity_context._local_agent_owner() == ArtifactRefAgentOwner(
        "alice",
        "athena",
    )
    projects = (
        ArtifactRefProject(
            name="sase",
            key="gh_sase-org__sase",
            aliases=("core-ui",),
        ),
    )
    assert artifact_ref_entity_context.collect_entity_context(
        store,
        "core-ui",
        projects,
    ) == (
        (ArtifactRefBeadStore("sase", "sase", beads),),
        (ArtifactRefAgentRoot("sase", agents),),
        ArtifactRefAgentOwner("alice", "athena"),
    )

    missing_store = SimpleNamespace(kind_root=lambda role: tmp_path / "missing")
    monkeypatch.setattr(
        artifact_ref_entity_context,
        "hidden_sidecar_clone_dir",
        lambda project_key, role: str(tmp_path / "missing-agents"),
    )
    assert (
        artifact_ref_entity_context._collect_bead_stores(
            missing_store,
            "sase",
        )
        == ()
    )
    assert (
        artifact_ref_entity_context._collect_agent_roots(
            "gh_sase-org__sase",
            "sase",
        )
        == ()
    )


def test_lsp_catalog_projects_authoritative_context_and_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    alpha_workspace = tmp_path / "alpha"
    beta_workspace = tmp_path / "beta"
    alpha_workspace.mkdir()
    beta_workspace.mkdir()
    records = [
        SimpleNamespace(
            project_name="gh_example__beta",
            display_name="Beta",
            aliases=["beta-ui"],
            workspace_dir=str(beta_workspace),
            system_managed=False,
        ),
        SimpleNamespace(
            project_name="gh_example__alpha",
            display_name="Alpha",
            aliases=["alpha-ui"],
            workspace_dir=str(alpha_workspace),
            system_managed=False,
        ),
        SimpleNamespace(
            project_name="home",
            display_name="home",
            aliases=[],
            workspace_dir=str(tmp_path),
            system_managed=True,
        ),
    ]
    contexts = {
        "gh_example__alpha": ArtifactRefContext(
            document_roots=(
                ArtifactRefDocumentRoot("designs", tmp_path / "alpha-designs"),
            ),
            chats_root=tmp_path / "chats",
            artifact_index_path=tmp_path / "index.jsonl",
            repositories=(ArtifactRefRepository("alpha"),),
            projects=(
                ArtifactRefProject(
                    "Alpha",
                    "gh_example__alpha",
                    ("alpha-ui",),
                ),
            ),
        ),
        "gh_example__beta": ArtifactRefContext(
            document_roots=(ArtifactRefDocumentRoot("plans", tmp_path / "beta-plans"),),
            chats_root=tmp_path / "chats",
            artifact_index_path=tmp_path / "index.jsonl",
            repositories=(ArtifactRefRepository("beta"),),
            projects=(
                ArtifactRefProject(
                    "Beta",
                    "gh_example__beta",
                    ("beta-ui",),
                ),
            ),
        ),
    }
    monkeypatch.setattr(
        artifact_ref_context,
        "list_project_records",
        lambda *_args, **_kwargs: records,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "effective_project_name",
        lambda record: record.display_name,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "workspace_context_for_plan_resolution",
        lambda workspace: (Path(workspace).resolve(), 1),
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "artifact_ref_context",
        lambda _workspace, _workspace_num, project=None: contexts[str(project)],
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "_workspace_project_ref",
        lambda _workspace: "example/beta",
    )

    payload = artifact_refs.artifact_ref_lsp_catalog_payload(beta_workspace)

    assert payload["schema_version"] == 1
    assert payload["default_project"] == "gh_example__beta"
    projects = payload["projects"]
    assert isinstance(projects, list)
    assert [project["name"] for project in projects] == ["Alpha", "Beta"]
    assert projects[0] == {
        "name": "Alpha",
        "key": "gh_example__alpha",
        "aliases": ["alpha-ui"],
        "context": contexts["gh_example__alpha"].to_wire(),
    }


def test_lsp_catalog_omits_only_failing_or_unusable_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    good_workspace = tmp_path / "good"
    bad_workspace = tmp_path / "bad"
    good_workspace.mkdir()
    bad_workspace.mkdir()
    records = [
        SimpleNamespace(
            project_name="good",
            display_name="Good",
            aliases=[],
            workspace_dir=str(good_workspace),
            system_managed=False,
        ),
        SimpleNamespace(
            project_name="bad",
            display_name="Bad",
            aliases=[],
            workspace_dir=str(bad_workspace),
            system_managed=False,
        ),
        SimpleNamespace(
            project_name="missing",
            display_name="Missing",
            aliases=[],
            workspace_dir=str(tmp_path / "missing"),
            system_managed=False,
        ),
    ]
    context = make_context(tmp_path)
    monkeypatch.setattr(
        artifact_ref_context,
        "list_project_records",
        lambda *_args, **_kwargs: records,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "effective_project_name",
        lambda record: record.display_name,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "workspace_context_for_plan_resolution",
        lambda workspace: (Path(workspace).resolve(), 1),
    )

    def build_context(
        _workspace: Path,
        _workspace_num: int,
        project: str | None = None,
    ) -> ArtifactRefContext:
        if project == "bad":
            raise RuntimeError("stale project")
        return context

    monkeypatch.setattr(artifact_ref_context, "artifact_ref_context", build_context)
    monkeypatch.setattr(
        artifact_ref_context,
        "_workspace_project_ref",
        lambda _workspace: None,
    )

    payload = artifact_refs.artifact_ref_lsp_catalog_payload(tmp_path)

    projects = payload["projects"]
    assert isinstance(projects, list)
    assert [project["key"] for project in projects] == ["good"]

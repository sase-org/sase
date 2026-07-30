from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase import (
    artifact_ref_context,
    artifact_ref_entity_context,
    artifact_ref_operations,
    artifact_refs,
)
from sase.artifact_ref_models import check_record_schema
from sase.artifact_refs import (
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
    ArtifactRefAgentOwner,
    ArtifactRefAgentRoot,
    ArtifactRefBeadStore,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)


def _context(
    tmp_path: Path,
    *,
    document_kind: str = "designs",
) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(
            ArtifactRefDocumentRoot(document_kind, tmp_path / document_kind),
            ArtifactRefDocumentRoot("plans", tmp_path / "plans"),
        ),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(ArtifactRefRepository("sase"),),
        projects=(
            ArtifactRefProject(
                name="sase",
                key="gh_sase-org__sase",
                aliases=("core-ui",),
            ),
        ),
        bead_stores=(
            ArtifactRefBeadStore(
                project="sase",
                prefix="sase",
                root=tmp_path / "beads",
            ),
        ),
        agent_roots=(
            ArtifactRefAgentRoot(
                project="sase",
                root=tmp_path / "agents-sidecar",
            ),
        ),
        agent_owner=ArtifactRefAgentOwner(
            username="alice",
            machine_name="athena",
        ),
    )


def test_parse_render_and_scan_wrappers_round_trip() -> None:
    parsed = artifact_refs.parse_artifact_ref("plans:202607/plan.md#L2-L4")

    assert parsed.kind == "plans"
    assert parsed.kind_type == "document"
    assert parsed.payload.path == "202607/plan.md"
    assert parsed.fragment is not None
    assert (parsed.fragment.type, parsed.fragment.start, parsed.fragment.end) == (
        "lines",
        2,
        4,
    )
    candidates = artifact_refs.scan_artifact_refs("é @plans:202607/plan.md#L2-L4.")
    assert len(candidates) == 1
    assert candidates[0].reference == parsed.rendered
    assert candidates[0].candidate_span.start == len("é ".encode())
    assert candidates[0].fragment_span is not None


@pytest.mark.parametrize(
    ("reference", "kind", "payload_field", "payload_value"),
    [
        ("bead:sase-9z.1", "bead", "id", "sase-9z.1"),
        (
            "agent:alice.athena.9w--code",
            "agent",
            "name",
            "alice.athena.9w--code",
        ),
    ],
)
def test_entity_references_round_trip_through_python_facade(
    reference: str,
    kind: str,
    payload_field: str,
    payload_value: str,
) -> None:
    parsed = artifact_refs.parse_artifact_ref(reference)

    assert parsed.schema_version == ARTIFACT_REF_WIRE_SCHEMA_VERSION == 2
    assert parsed.kind == parsed.kind_type == kind
    assert getattr(parsed.payload, payload_field) == payload_value
    assert parsed.to_wire()["payload"] == {
        "type": kind,
        payload_field: payload_value,
    }


@pytest.mark.parametrize(
    "reference",
    ["bead:sase-9z#L1", "agent:9w#L1"],
)
def test_entity_references_reject_fragments(reference: str) -> None:
    with pytest.raises(ValueError, match="references do not support fragments"):
        artifact_refs.parse_artifact_ref(reference)


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

    assert artifact_ref_entity_context.collect_bead_stores(store, "sase") == (
        ArtifactRefBeadStore("sase", "sase", beads),
    )
    assert artifact_ref_entity_context.collect_agent_roots(
        "gh_sase-org__sase",
        "sase",
    ) == (ArtifactRefAgentRoot("sase", agents),)
    assert artifact_ref_entity_context.local_agent_owner() == ArtifactRefAgentOwner(
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
        artifact_ref_entity_context.collect_bead_stores(
            missing_store,
            "sase",
        )
        == ()
    )
    assert (
        artifact_ref_entity_context.collect_agent_roots(
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
    context = _context(tmp_path)
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


def test_document_chat_and_indexed_file_resolve_through_fixture_roots(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    document = tmp_path / "designs" / "202607" / "design.md"
    chat = tmp_path / "chats" / "202607" / "agent.md"
    artifact = tmp_path / "output.png"
    document.parent.mkdir(parents=True)
    chat.parent.mkdir(parents=True)
    context.artifact_index_path.parent.mkdir(parents=True)
    document.write_text("# Design\n", encoding="utf-8")
    chat.write_text("# Chat\n", encoding="utf-8")
    artifact.write_bytes(b"png")
    artifact_id = "default:52895d68931185056fd0e49f"
    context.artifact_index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact": {
                    "id": artifact_id,
                    "path": str(artifact),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    for path, expected in (
        (document, "designs:202607/design.md"),
        (chat, "chat:202607/agent.md"),
        (artifact, f"file:{artifact_id}"),
    ):
        reference = artifact_ref_operations.canonicalize_artifact_ref(
            path,
            context=context,
        )
        assert reference == expected
        resolution = artifact_refs.resolve_artifact_ref(
            reference,
            context=context,
        )
        assert resolution.status == "exact"
        assert resolution.resolved_path == path


def test_bug_resolution_accepts_key_and_renders_display_name(tmp_path: Path) -> None:
    context = _context(tmp_path)

    resolution = artifact_refs.resolve_artifact_ref(
        "bug:gh_sase-org__sase#42",
        context=context,
    )

    assert resolution.status == "exact"
    assert resolution.rendered == "bug:sase#42"
    assert resolution.locator == "sase#42"


def test_bead_resolution_statuses_and_candidates(tmp_path: Path) -> None:
    context = _context(tmp_path)
    page = context.bead_stores[0].root / "pages" / "sase-9z" / "README.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Bead\n", encoding="utf-8")

    exact = artifact_refs.resolve_artifact_ref("bead:sase-9z", context=context)
    assert exact.status == "exact"
    assert exact.resolved_path == page
    assert exact.locator == "sase/sase-9z"

    unknown = artifact_refs.resolve_artifact_ref("bead:other-9z", context=context)
    assert unknown.status == "unknown_project"

    missing = artifact_refs.resolve_artifact_ref("bead:sase-aa", context=context)
    assert missing.status == "missing"
    assert missing.candidates == (
        str(context.bead_stores[0].root / "pages" / "sase-aa" / "README.md"),
    )


def test_agent_resolution_globalizes_local_name_and_reports_missing(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    page = (
        context.agent_roots[0].root / "agents" / "alice.athena.9w--code" / "README.md"
    )
    page.parent.mkdir(parents=True)
    page.write_text("# Agent\n", encoding="utf-8")

    exact = artifact_refs.resolve_artifact_ref("agent:9w--code", context=context)
    assert exact.status == "exact"
    assert exact.resolved_path == page
    assert exact.rendered == "agent:alice.athena.9w--code"
    assert exact.locator == "sase/alice.athena.9w--code"

    missing = artifact_refs.resolve_artifact_ref("agent:missing", context=context)
    assert missing.status == "missing"
    assert missing.candidates


def test_context_without_entity_sidecars_preserves_other_resolution(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    context = ArtifactRefContext(
        document_roots=context.document_roots,
        chats_root=context.chats_root,
        artifact_index_path=context.artifact_index_path,
        repositories=context.repositories,
        projects=context.projects,
    )
    document = context.document_roots[0].root / "design.md"
    chat = context.chats_root / "agent.md"
    document.parent.mkdir(parents=True)
    chat.parent.mkdir(parents=True)
    document.write_text("# Design\n", encoding="utf-8")
    chat.write_text("# Chat\n", encoding="utf-8")

    assert (
        artifact_refs.resolve_artifact_ref(
            "designs:design.md",
            context=context,
        ).status
        == "exact"
    )
    assert (
        artifact_refs.resolve_artifact_ref(
            "chat:agent.md",
            context=context,
        ).status
        == "exact"
    )


def test_reference_for_each_entry_target_shape(tmp_path: Path) -> None:
    context = _context(tmp_path)
    chat = context.chats_root / "202607" / "agent.md"
    proposal = context.document_roots[1].root / "202607" / "proposal.md"
    archive = SimpleNamespace(
        plan=SimpleNamespace(relpath="202607/design.md", kind="designs")
    )
    issue = SimpleNamespace(id="sase-av", design="plans:202607/epic.md")
    phase = SimpleNamespace(id="sase-av.2", design="plans:202607/epic.md")

    assert (
        artifact_refs.reference_for_entry_target(
            "commits",
            ("commit", "sase", "a" * 40),
            context=context,
        )
        == f"commit:sase@{'a' * 40}"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "chats",
            ("chat", str(chat)),
            context=context,
        )
        == "chat:202607/agent.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "bugs",
            ("bug", "gh_sase-org__sase", "42"),
            context=context,
        )
        == "bug:sase#42"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "archive", str(archive.plan.relpath)),
            context=context,
            row=SimpleNamespace(archive=archive, archive_role="designs"),
        )
        == "designs:202607/design.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "epic", "sase-av"),
            context=context,
            row=SimpleNamespace(issue=issue),
        )
        == "bead:sase-av"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "phase", "sase-av.2"),
            context=context,
            row=SimpleNamespace(issue=phase),
        )
        == "bead:sase-av.2"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "proposal", "notification"),
            context=context,
            row=SimpleNamespace(proposal=SimpleNamespace(plan_path=str(proposal))),
        )
        == "plans:202607/proposal.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "files",
            ("file", "default:0123456789abcdef01234567"),
            context=None,
        )
        == "file:default:0123456789abcdef01234567"
    )


def test_reference_rendering_declines_unrepresentable_rows(tmp_path: Path) -> None:
    context = _context(tmp_path)

    assert (
        artifact_refs.reference_for_entry_target(
            "chats",
            ("chat", str(tmp_path / "imported.md")),
            context=context,
        )
        is None
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "phase", "sase-av.2"),
            context=context,
            row=SimpleNamespace(issue=SimpleNamespace(id="")),
        )
        is None
    )


def test_plan_design_and_agent_reference_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity(username="alice", machine_name="athena"),
        sibling_machines=("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )

    row = SimpleNamespace(issue=SimpleNamespace(design="plans:202607/epic.md"))
    assert artifact_refs.design_reference_for_plan_row(row) == "plans:202607/epic.md"
    assert artifact_refs.reference_for_agent_name("9w") == "agent:alice.athena.9w"
    assert (
        artifact_refs.reference_for_agent_name("alice.athena.9w--code")
        == "agent:alice.athena.9w--code"
    )
    assert (
        artifact_refs.reference_for_agent_name("bob.zeus.reader")
        == "agent:bob.zeus.reader"
    )


def test_schema_gate_fails_before_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def require(name: str) -> Any:
        requested.append(name)
        if name == "artifact_ref_wire_schema_version":
            return lambda: 99
        raise AssertionError(name)

    monkeypatch.setattr(artifact_ref_operations, "require_rust_binding", require)

    with pytest.raises(RuntimeError, match="wire is stale"):
        artifact_refs.parse_artifact_ref("plans:202607/plan.md")
    assert requested == ["artifact_ref_wire_schema_version"]


def test_record_schema_rejects_schema_one() -> None:
    assert ARTIFACT_REF_WIRE_SCHEMA_VERSION == 2
    with pytest.raises(RuntimeError, match="unsupported test wire: 1"):
        check_record_schema({"schema_version": 1}, record="test")

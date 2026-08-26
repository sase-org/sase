from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.artifact_links.derive import DerivableDocument
from sase.sdd import artifact_link_derivation as artifact_link_derivation_module
from sase.sdd._store_types import SddStore
from sase.sdd.artifact_link_derivation import derive_and_persist_artifact_links
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    render_plan_header_block,
)
from tests._conftest_environment import redirect_sase_home


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def _research_lineage_documents(tmp_path: Path) -> tuple[DerivableDocument, ...]:
    month = tmp_path / "research" / "202608" / "widget"
    month.mkdir(parents=True)
    lead = month / "widget.md"
    lead.write_text("# lead\n", encoding="utf-8")
    (month / "widget__a.md").write_text("# a\n", encoding="utf-8")
    return (DerivableDocument(ref="research:202608/widget/widget.md", path=lead),)


def test_no_documents_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)

    outcome = derive_and_persist_artifact_links(store, (), created_by="sase")

    assert outcome == type(outcome)()


def test_derives_and_persists_research_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    documents = _research_lineage_documents(tmp_path)

    outcome = derive_and_persist_artifact_links(
        store, documents, created_by="sase-agent.1"
    )

    assert outcome.candidates == 1
    assert outcome.persisted == 1
    assert outcome.errors == ()
    rows = store.load_artifact_rows("research:202608/widget/widget.md")
    assert len(rows) == 1
    row = rows[0]
    assert row["relation"] == "derives-from"
    assert row["target_ref"] == "research:202608/widget/widget__a.md"
    assert row["origin"] == "derived"
    assert row["created_by"] == "sase-agent.1"


def test_derives_and_persists_plan_implements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sase.sdd.artifact_link_derivation._known_bead_ids",
        lambda _store: frozenset({"sase-xx"}),
    )
    month = tmp_path / "plans" / "202608"
    month.mkdir(parents=True)
    plan_path = month / "example.md"
    plan_path.write_text(
        "---\ntier: tale\nbead_id: sase-xx\n---\n\nbody\n", encoding="utf-8"
    )
    documents = (DerivableDocument(ref="plan:202608/example.md", path=plan_path),)

    outcome = derive_and_persist_artifact_links(
        store, documents, created_by="sase-agent.1"
    )

    assert outcome.persisted == 1
    rows = store.load_artifact_rows("plan:202608/example.md")
    assert rows[0]["relation"] == "implements"
    assert rows[0]["target_ref"] == "bead:sase-xx"


def test_a_second_pass_over_the_same_documents_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    documents = _research_lineage_documents(tmp_path)

    derive_and_persist_artifact_links(store, documents, created_by="sase")
    second = derive_and_persist_artifact_links(store, documents, created_by="sase")

    assert second.persisted == 1
    assert len(store.load_artifact_rows("research:202608/widget/widget.md")) == 1


def test_a_persist_failure_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    documents = _research_lineage_documents(tmp_path)

    def _boom(_self: object, _ref: object, _row: object) -> dict[str, object]:
        raise ValueError("disk is on fire")

    monkeypatch.setattr(ArtifactLinkStore, "_upsert_sidecar", _boom)

    outcome = derive_and_persist_artifact_links(store, documents, created_by="sase")

    assert outcome.candidates == 1
    assert outcome.persisted == 0
    assert outcome.errors and "disk is on fire" in outcome.errors[0]


def test_every_candidate_lands_in_one_commit_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    # Two lead documents each deriving one candidate.
    first_month = tmp_path / "research" / "202608" / "widget"
    first_month.mkdir(parents=True)
    first_lead = first_month / "widget.md"
    first_lead.write_text("# lead\n", encoding="utf-8")
    (first_month / "widget__a.md").write_text("# a\n", encoding="utf-8")
    second_month = tmp_path / "research" / "202608" / "gadget"
    second_month.mkdir(parents=True)
    second_lead = second_month / "gadget.md"
    second_lead.write_text("# lead\n", encoding="utf-8")
    (second_month / "gadget__b.md").write_text("# b\n", encoding="utf-8")
    documents = (
        DerivableDocument(ref="research:202608/widget/widget.md", path=first_lead),
        DerivableDocument(ref="research:202608/gadget/gadget.md", path=second_lead),
    )

    calls: list[object] = []
    original = artifact_link_derivation_module.persist_artifact_link_graph_mutation

    def _spy(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        artifact_link_derivation_module, "persist_artifact_link_graph_mutation", _spy
    )

    outcome = derive_and_persist_artifact_links(store, documents, created_by="sase")

    assert outcome.persisted == 2
    assert len(calls) == 1


def test_derives_and_persists_agent_cites_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    agents = tmp_path / "agents"
    plans.mkdir()
    research.mkdir()
    agents.mkdir()
    sdd_store = SddStore(
        "sidecar_repos",
        plans,
        plans,
        sidecar_dirs={"research": research, "agents": agents},
    )
    store = ArtifactLinkStore.from_sdd_store(sdd_store, "gh_sase-org__sase")

    prompt_section = PlanHeaderSection(
        kind=PlanHeaderSectionKind.PROMPT,
        label="prompts/202608/example.md",
        target="https://example.test/prompt",
    )
    plan_path = plans / "202608" / "example.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        f"{render_plan_header_block((prompt_section,))}\n\n# Plan\n",
        encoding="utf-8",
    )
    agents_section = PlanHeaderSection(
        kind=PlanHeaderSectionKind.AGENTS,
        entries=(PlanHeaderEntry(label="alice.athena.worker"),),
    )
    prompt_path = agents / "prompts" / "202608" / "example.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text(
        f"{render_plan_header_block((agents_section,))}\n\n# Prompt\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        artifact_link_derivation_module,
        "_is_agent_published",
        lambda name, **_kwargs: name == "alice.athena.worker",
    )
    documents = (DerivableDocument(ref="plan:202608/example.md", path=plan_path),)

    outcome = derive_and_persist_artifact_links(
        store, documents, created_by="sase-agent.1"
    )

    assert outcome.persisted == 1
    rows = store.load_artifact_rows("plan:202608/example.md")
    assert rows[0]["source_ref"] == "agent:alice.athena.worker"
    assert rows[0]["relation"] == "cites"
    assert rows[0]["origin"] == "derived"


def test_derivation_inputs_resolve_agents_from_store_workspace_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = tmp_path / "workspace" / "sase" / "repos" / "plans"
    research = tmp_path / "workspace" / "sase" / "repos" / "research"
    agents = tmp_path / "agents"
    plans.mkdir(parents=True)
    research.mkdir(parents=True)
    agents.mkdir()
    sdd_store = SddStore(
        "sidecar_repos",
        plans,
        plans,
        sidecar_dirs={"research": research, "agents": agents},
    )
    store = ArtifactLinkStore.from_sdd_store(sdd_store, "gh_sase-org__sase")
    context = object()
    resolved_contexts: list[object | None] = []
    monkeypatch.setattr(
        "sase.workspace_provider.find_marker_from_cwd",
        lambda _cwd: (
            str(tmp_path / "workspace"),
            SimpleNamespace(workspace_num=12),
        ),
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_context",
        lambda workspace_root, workspace_num, project=None: context,
    )

    def _resolve(_ref: str, *, context: object | None = None) -> object:
        resolved_contexts.append(context)
        return SimpleNamespace(resolution=SimpleNamespace(status="exact"))

    monkeypatch.setattr("sase.artifact_cli.references.resolve_cli_reference", _resolve)

    inputs = artifact_link_derivation_module.artifact_link_derivation_inputs(store)

    assert inputs.is_agent_published("alice.athena.worker") is True
    assert resolved_contexts == [context]

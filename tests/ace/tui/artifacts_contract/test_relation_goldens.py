"""Frozen relation oracle: Patch chains plus built-in pane sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.ace.patch import Patch
from sase.ace.tui._artifact_tab_contract import (
    compile_builtin_contract,
    compile_provider_contract,
)
from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
from sase.ace.tui.relations import (
    build_beads_relation_index,
    build_documents_relation_index,
    build_files_relation_index,
    build_patches_relation_index,
    build_provider_relation_index,
    build_stitches_relation_index,
)
from sase.ace.tui.widgets.artifacts.bead_plan_links import BeadPlanLink
from sase.ace.tui.widgets.artifacts.beads_data_models import BeadsSnapshot, ProjectBead
from sase.ace.tui.widgets.artifacts.files_data import (
    FileVersion,
    FilesSnapshot,
    LogicalFile,
)
from sase.ace.tui.widgets.artifacts.plans_data_models import (
    ActivePlanDocument,
    LinkedPlanDocument,
    PlanProposal,
    PlansSnapshot,
    ProjectArchive,
)
from sase.bead.model import Dependency, Issue, IssueType, Status
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationEdge, RelationIndex
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.notifications.models import Notification
from sase.plan_search.model import Plan, PlanSearchMatch

_GOLDEN = Path(__file__).resolve().parent / "goldens" / "relations" / "cases.json"
_PATCH_CASES = ("parent_chain", "cycle", "missing_parent", "family")
_STATUS = {
    "open": Status.OPEN,
    "closed": Status.CLOSED,
    "in_progress": Status.IN_PROGRESS,
}
_ISSUE_TYPE = {
    "plan": IssueType.PLAN,
    "phase": IssueType.PHASE,
    "task": IssueType.TASK,
}


def _cases() -> dict[str, Any]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def _patch(item: dict[str, Any]) -> Patch:
    return Patch(
        name=str(item["name"]),
        description="d",
        parent=item.get("parent"),
        status=str(item.get("status") or "Ready"),
        file_path="/tmp/demo.sase",
        line_number=1,
    )


def _patch_target(patch: Patch) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(
        pane_id="patches", parts=(patch.project_name, patch.name)
    )


def _patches_contract():
    return compile_builtin_contract("patches", label="Patch", icon="x", accent="#0")


def test_relation_cases_match_current_patch_graph() -> None:
    cases = _cases()
    contract = _patches_contract()
    for name in _PATCH_CASES:
        case = cases[name]
        patches = [_patch(item) for item in case["patches"]]
        graph = build_patch_graph_index(patches)
        index = build_patches_relation_index(patches, graph, contract=contract)
        selected = next(item for item in patches if item.name == case["from"])
        target = _patch_target(selected)
        ancestors = [edge.target.parts[-1] for edge in index.chain(target, "ancestors")]
        children = [
            edge.target.parts[-1]
            for edge in index.edges_for_relation(target, "children")
        ]
        siblings = [
            edge.target.parts[-1]
            for edge in index.edges_for_relation(target, "siblings")
        ]
        assert ancestors == case["ancestors"], name
        assert siblings == case["siblings"], name
        assert children == case["children"], name


def test_cross_kind_and_pane_sources_match_goldens() -> None:
    cases = _cases()
    panes = cases["panes"]
    beads = _beads_index(panes["beads"])
    files = _files_index(panes["files"])
    stitches = _stitches_index(panes["stitches"])
    documents = _documents_index(panes["documents"])
    provider = _provider_index(panes["provider"])
    by_pane = {
        "beads": beads,
        "files": files,
        "stitches": stitches,
        "ref:plan": documents,
        provider.pane_id: provider,
    }
    expected = cases["cross_kind_edges"]
    actual = [
        _edge_record(edge)
        for index in by_pane.values()
        for edge in index.edges
        if edge.target.pane_id != index.pane_id
    ]
    for record in expected:
        assert record in actual
    assert (
        _edge_record(
            next(
                edge
                for edge in stitches.edges
                if edge.relation == "patches" and not edge.derived
            )
        )
        == expected[0]
    )
    assert any(
        edge.relation == "plans" and edge.target.pane_id == "ref:plan"
        for edge in beads.edges
    )
    assert any(
        edge.relation == "beads" and edge.target.pane_id == "beads"
        for edge in documents.edges
    )


def _edge_record(edge: RelationEdge) -> dict[str, object]:
    return {
        "relation": edge.relation,
        "kind": edge.kind.value,
        "source_parts": list(edge.source.parts),
        "target_parts": list(edge.target.parts),
        "target_pane": edge.target.pane_id,
        "dangling": edge.dangling,
    }


def _beads_index(case: dict[str, Any]) -> RelationIndex:
    project = str(case["project"])
    epics = tuple(
        _project_bead(project, item, IssueType.PLAN) for item in case["epics"]
    )
    phases = tuple(
        _project_bead(project, item, IssueType.PHASE) for item in case["phases"]
    )
    tasks = tuple(
        _project_bead(project, item, IssueType.TASK) for item in case["tasks"]
    )
    phases_by_epic: dict[tuple[str, str], tuple[ProjectBead, ...]] = {}
    for phase in phases:
        parent = phase.issue.parent_id or ""
        key = (project, parent)
        phases_by_epic[key] = (*phases_by_epic.get(key, ()), phase)
    snapshot = BeadsSnapshot(
        project=project,
        projects=(project,),
        display_names={project: project},
        beads_dirs={},
        workspace_dirs={},
        tasks=tasks,
        epics=epics,
        phases_by_epic=phases_by_epic,
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
        plan_links={
            (project, bead_id): path for bead_id, path in case["plan_links"].items()
        },
        triage_gates={},
        source_key=("golden",),
        errors={},
    )
    contract = compile_builtin_contract("beads", label="Bead", icon="x", accent="#0")
    return build_beads_relation_index(snapshot, contract=contract)


def _project_bead(
    project: str, item: dict[str, Any], issue_type: IssueType
) -> ProjectBead:
    depends_on = item.get("depends_on")
    return ProjectBead(
        project,
        Issue(
            id=str(item["id"]),
            title=str(item["id"]),
            status=_STATUS[str(item.get("status") or "open")],
            issue_type=issue_type,
            parent_id=item.get("parent_id"),
            dependencies=(
                []
                if not depends_on
                else [
                    Dependency(
                        issue_id=str(item["id"]),
                        depends_on_id=str(depends_on),
                        created_at="2026-08-01T00:00:00Z",
                    )
                ]
            ),
        ),
    )


def _files_index(case: dict[str, Any]) -> RelationIndex:
    logical_id = str(case["logical_id"])
    versions = tuple(
        FileVersion(
            version_id=str(version_id),
            logical_id=logical_id,
            label=logical_id,
            kind="file",
            origin="ref",
            origins=frozenset({"ref"}),
            created_at=None,
            agents=(),
            projects=(),
        )
        for version_id in case["versions"]
    )
    snapshot = FilesSnapshot(
        rows=(
            LogicalFile(
                logical_id=logical_id,
                label=logical_id,
                kind="file",
                versions=versions,
                agents=(),
                projects=(),
                origins=frozenset({"ref"}),
                latest_seen_at=None,
            ),
        ),
        project="alpha",
        complete=True,
        view_modes={},
        view_mode_counts={},
        origin_counts={},
    )
    contract = compile_builtin_contract("files", label="File", icon="x", accent="#0")
    return build_files_relation_index(snapshot, contract=contract)


def _stitches_index(case: dict[str, Any]) -> RelationIndex:
    entries = tuple(
        AggregatedCommitWire(
            str(item["repo"]),
            VcsCommitWire(
                full_id=str(item["id"]),
                short_id=str(item["id"])[:7],
                author_name="Ada",
                author_email="ada@example.com",
                timestamp=1,
                parent_ids=tuple(str(parent) for parent in item.get("parents") or ()),
                subject="feat",
                body=str(item.get("body") or ""),
            ),
        )
        for item in case["commits"]
    )
    contract = compile_builtin_contract(
        "stitches", label="Stitch", icon="x", accent="#0"
    )
    return build_stitches_relation_index(
        entries,
        contract=contract,
        project_keys_by_repo=dict(case["project_keys_by_repo"]),
    )


def _documents_index(case: dict[str, Any]) -> RelationIndex:
    project = str(case["project"])
    proposal = case["proposal"]
    active = case["active"]
    link = case["bead_link"]
    notification = Notification(
        id=str(proposal["id"]),
        timestamp="2026-08-01T00:00:00+00:00",
        sender="planner",
    )
    snapshot = PlansSnapshot(
        project=project,
        projects=(project,),
        display_names={project: project},
        beads_dirs={},
        plans_roots={},
        workspace_dirs={},
        proposals=(
            PlanProposal(
                project=project,
                notification=notification,
                title="Plan",
                tier="epic",
                age="",
                timestamp=notification.timestamp,
                plan_path=str(proposal["path"]),
                content="",
                frontmatter={},
                body="",
                agent="",
                provider_model="",
            ),
        ),
        active=(
            ActivePlanDocument(
                project,
                LinkedPlanDocument(
                    reference="plan:p",
                    path=str(active["path"]),
                    content="",
                    frontmatter={},
                    body="",
                    error=None,
                    signature=None,
                ),
                BeadPlanLink(
                    project=project,
                    bead_id=str(link["bead_id"]),
                    bead_type=_ISSUE_TYPE[str(link["bead_type"])],
                    bead_status=Status.IN_PROGRESS,
                    bead_tier=None,
                    bead_title="",
                    bead_created_at="",
                    reference="plan:p",
                    path=str(link["path"]),
                ),
            ),
        ),
        archive=(),
        bead_plan_links={
            (project, str(link["bead_id"])): BeadPlanLink(
                project=project,
                bead_id=str(link["bead_id"]),
                bead_type=_ISSUE_TYPE[str(link["bead_type"])],
                bead_status=Status.IN_PROGRESS,
                bead_tier=None,
                bead_title="",
                bead_created_at="",
                reference="plan:p",
                path=str(link["path"]),
            )
        },
        linked_plan_documents={},
        source_key=("golden",),
        errors={},
    )
    result = compile_provider_contract(
        kind="plan",
        label="Plan",
        icon="x",
        accent="#0",
        spec=None,
        provider_spec_digest="golden",
    )
    return build_documents_relation_index(snapshot, contract=result.contract)


def _provider_index(case: dict[str, Any]) -> RelationIndex:
    archive = tuple(
        ProjectArchive(
            str(item["project"]),
            PlanSearchMatch(
                plan=Plan(
                    source="repo",
                    kind="notes",
                    path=str(item["path"]),
                    relpath=str(item["relpath"]),
                    name=Path(str(item["relpath"])).stem,
                    title=Path(str(item["relpath"])).stem,
                    status="",
                    created_at="",
                    prompt_link="",
                    summary="",
                    body="",
                    frontmatter=dict(item.get("frontmatter") or {}),
                ),
                matched_fields=[],
                score=1.0,
            ),
        )
        for item in case["archive"]
    )
    snapshot = PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "alpha"},
        beads_dirs={},
        plans_roots={},
        workspace_dirs={},
        proposals=(),
        active=(),
        archive=archive,
        bead_plan_links={},
        linked_plan_documents={},
        source_key=("golden",),
        errors={},
        provider_kind=str(case["kind"]),
        provider_label="Note",
    )
    result = compile_provider_contract(
        kind=str(case["kind"]),
        label="Note",
        icon="¶",
        accent="#0",
        spec={
            "schema_version": 1,
            "provider": "notes",
            "ref": {
                "kind": "notes",
                "icon": "¶",
                "expansion_format": "@{checkout_path}",
                "properties": {
                    "title": {"type": "string", "source": "markdown_frontmatter"},
                    "related": {"type": "string", "source": "markdown_frontmatter"},
                },
                "identity": {},
                "inventory": {"globs": ["**/*.md"]},
                "publication": {
                    "link": "vcs_permalink",
                    "referenced_by": "markdown_table",
                },
                "relations": [
                    {
                        "name": "related",
                        "kind": "link",
                        "label": "Related",
                        "source": "related",
                        "target_pane": None,
                        "inverse": None,
                        "directed": True,
                        "transitive": False,
                    }
                ],
            },
        },
        provider_spec_digest="golden",
    )
    return build_provider_relation_index(snapshot, contract=result.contract)

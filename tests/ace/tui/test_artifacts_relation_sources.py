"""Focused coverage for each built-in Artifacts relation source."""

from __future__ import annotations

from sase.ace.patch import Patch
from sase.ace.tui._artifact_tab_contract import (
    compile_builtin_contract,
    compile_provider_contract,
)
from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
from sase.ace.tui.relations import (
    ArtifactLinksSnapshot,
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
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.notifications.models import Notification
from sase.plan_search.model import Plan, PlanSearchMatch


def _patch(name: str, parent: str | None = None) -> Patch:
    return Patch(
        name=name,
        description="d",
        parent=parent,
        status="Ready",
        file_path="/tmp/demo.sase",
        line_number=1,
    )


def test_patches_source_emits_ancestors_children_and_siblings() -> None:
    patches = [_patch("root"), _patch("child", "root"), _patch("root__1")]
    contract = compile_builtin_contract("patches", label="P", icon="x", accent="#0")
    index = build_patches_relation_index(
        patches, build_patch_graph_index(patches), contract=contract
    )
    child = ArtifactEntryTarget("patches", (patches[1].project_name, "child"))
    root = ArtifactEntryTarget("patches", (patches[0].project_name, "root"))
    assert [edge.target.parts[-1] for edge in index.chain(child, "ancestors")] == [
        "root"
    ]
    assert [
        edge.target.parts[-1] for edge in index.edges_for_relation(root, "children")
    ] == ["child"]
    assert [
        edge.target.parts[-1] for edge in index.edges_for_relation(root, "siblings")
    ] == ["root__1"]


def test_beads_source_emits_parent_dependencies_and_plan_link() -> None:
    epic = ProjectBead(
        "alpha",
        Issue(id="e1", title="epic", issue_type=IssueType.PLAN, status=Status.OPEN),
    )
    phase = ProjectBead(
        "alpha",
        Issue(
            id="e1.1",
            title="phase",
            issue_type=IssueType.PHASE,
            parent_id="e1",
            status=Status.CLOSED,
        ),
    )
    task = ProjectBead(
        "alpha",
        Issue(
            id="t1",
            title="task",
            issue_type=IssueType.TASK,
            parent_id="e1",
            dependencies=[
                Dependency(issue_id="t1", depends_on_id="e1.1", created_at="t")
            ],
        ),
    )
    flag = ProjectBead(
        "alpha",
        Issue(
            id="f1",
            title="flag",
            issue_type=IssueType.TASK,
            task_type="flag",
            task_type_fields={
                "key": "demo_key",
                "kind": "beta",
                "when_enabled": "on",
                "when_disabled": "off",
                "remove_when": "done",
                "remove_by_date": "2026-12-01",
                "remove_by_release": "0.19.0",
            },
        ),
    )
    snapshot = BeadsSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={},
        workspace_dirs={},
        tasks=(task,),
        flags=(flag,),
        epics=(epic,),
        phases_by_epic={("alpha", "e1"): (phase,)},
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
        plan_links={("alpha", "e1"): "/plans/e1.md"},
        triage_gates={},
        source_key=("src",),
        errors={},
    )
    contract = compile_builtin_contract("beads", label="B", icon="x", accent="#0")
    index = build_beads_relation_index(snapshot, contract=contract)
    phase_t = ArtifactEntryTarget("beads", ("alpha", "phase", "e1.1"))
    epic_t = ArtifactEntryTarget("beads", ("alpha", "epic", "e1"))
    task_t = ArtifactEntryTarget("beads", ("alpha", "task", "t1"))
    flag_t = ArtifactEntryTarget("beads", ("alpha", "flag", "f1"))
    assert index.edges_for_relation(phase_t, "parent")[0].target == epic_t
    assert index.edges_for_relation(epic_t, "children")
    assert index.edges_for_relation(task_t, "dependencies")[0].target == phase_t
    assert flag_t in index.known_targets
    plan = index.edges_for_relation(epic_t, "plans")[0]
    assert plan.target == ArtifactEntryTarget(
        "ref:plan", ("alpha", "active", "/plans/e1.md")
    )
    assert plan.dangling is False


def test_files_source_emits_row_to_version_family() -> None:
    versions = (
        FileVersion(
            version_id="v1",
            logical_id="doc",
            label="doc",
            kind="file",
            origin="ref",
            origins=frozenset({"ref"}),
            created_at=None,
            agents=(),
            projects=(),
        ),
        FileVersion(
            version_id="v2",
            logical_id="doc",
            label="doc",
            kind="file",
            origin="ref",
            origins=frozenset({"ref"}),
            created_at=None,
            agents=(),
            projects=(),
        ),
    )
    snapshot = FilesSnapshot(
        rows=(
            LogicalFile(
                logical_id="doc",
                label="doc",
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
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    index = build_files_relation_index(snapshot, contract=contract)
    row = ArtifactEntryTarget("files", ("doc",))
    v1 = ArtifactEntryTarget("files", ("doc", "v1"))
    assert {edge.target for edge in index.edges_for_relation(row, "versions")} == {
        v1,
        ArtifactEntryTarget("files", ("doc", "v2")),
    }
    assert index.edges_for_relation(v1, "versions")[0].target == row
    assert not any(edge.dangling for edge in index.edges)


def test_artifact_links_source_emits_typed_relations_for_current_pane() -> None:
    snapshot = _files_snapshot_with_link_rows(
        (
            {
                "source_ref": "file:doc",
                "relation": "implements",
                "target_ref": "bead:sase-r8",
                "description": "extends requirement",
                "origin": "manual",
                "uses": 3,
            },
            {
                "source_ref": "plan:202608/design.md",
                "relation": "implements",
                "target_ref": "file:doc",
                "description": "frontmatter link",
                "origin": "derived",
                "uses": 2,
            },
        )
    )
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    index = build_files_relation_index(snapshot, contract=contract)
    row = ArtifactEntryTarget("files", ("doc",))

    implements = index.edges_for_relation(row, "implements")
    assert implements[0].target == ArtifactEntryTarget(
        "beads", ("alpha", "task", "sase-r8")
    )
    assert implements[0].label == "implements"
    assert implements[0].description == "extends requirement"
    assert implements[0].origin == "manual"
    assert implements[0].uses == 3
    implemented_by = index.edges_for_relation(row, "implemented-by")
    assert implemented_by[0].target == ArtifactEntryTarget(
        "ref:plan", ("alpha", "archive", "202608/design.md")
    )
    assert implemented_by[0].label == "implemented-by"
    assert implemented_by[0].description == "frontmatter link"
    assert implemented_by[0].origin == "derived"
    assert implemented_by[0].uses == 2


def test_artifact_links_source_deduplicates_undirected_related_rows() -> None:
    snapshot = _files_snapshot_with_link_rows(
        (
            {
                "source_ref": "file:doc",
                "relation": "related",
                "target_ref": "file:other",
            },
            {
                "source_ref": "file:other",
                "relation": "related",
                "target_ref": "file:doc",
            },
        ),
        extra_logical_ids=("other",),
    )
    contract = compile_builtin_contract("files", label="F", icon="x", accent="#0")
    index = build_files_relation_index(snapshot, contract=contract)
    row = ArtifactEntryTarget("files", ("doc",))

    assert [
        edge.target.parts[0] for edge in index.edges_for_relation(row, "related")
    ] == ["other"]


def test_stitches_source_emits_parents_and_patch_tag() -> None:
    child = AggregatedCommitWire(
        "sase",
        VcsCommitWire(
            full_id="ccc",
            short_id="ccc",
            author_name="Ada",
            author_email="ada@example.com",
            timestamp=1,
            parent_ids=("ppp",),
            subject="feat",
            body="body\n\nSASE_PATCH=feat-x",
        ),
    )
    parent = AggregatedCommitWire(
        "sase",
        VcsCommitWire(
            full_id="ppp",
            short_id="ppp",
            author_name="Ada",
            author_email="ada@example.com",
            timestamp=0,
            subject="base",
            body="",
        ),
    )
    contract = compile_builtin_contract("stitches", label="S", icon="x", accent="#0")
    index = build_stitches_relation_index(
        (child, parent),
        contract=contract,
        project_keys_by_repo={"sase": "sase_key"},
    )
    child_t = ArtifactEntryTarget("stitches", ("sase", "ccc"))
    parent_t = ArtifactEntryTarget("stitches", ("sase", "ppp"))
    assert index.edges_for_relation(child_t, "parents")[0].target == parent_t
    assert index.edges_for_relation(parent_t, "children")[0].target == child_t
    patch = index.edges_for_relation(child_t, "patches")[0]
    assert patch.target == ArtifactEntryTarget("patches", ("sase_key", "feat-x"))
    assert patch.dangling is False


def test_documents_source_emits_lifecycle_children_and_bead_links() -> None:
    notification = Notification(
        id="p1", timestamp="2026-08-01T00:00:00+00:00", sender="planner"
    )
    link = BeadPlanLink(
        project="alpha",
        bead_id="e1",
        bead_type=IssueType.PLAN,
        bead_status=Status.IN_PROGRESS,
        bead_tier=None,
        bead_title="",
        bead_created_at="",
        reference="plan:p",
        path="/p.md",
    )
    snapshot = PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={},
        plans_roots={},
        workspace_dirs={},
        proposals=(
            PlanProposal(
                project="alpha",
                notification=notification,
                title="Plan",
                tier="epic",
                age="",
                timestamp=notification.timestamp,
                plan_path="/p.md",
                content="",
                frontmatter={},
                body="",
                agent="",
                provider_model="",
            ),
        ),
        active=(
            ActivePlanDocument(
                "alpha",
                LinkedPlanDocument(
                    reference="plan:p",
                    path="/p.md",
                    content="",
                    frontmatter={},
                    body="",
                    error=None,
                    signature=None,
                ),
                link,
            ),
        ),
        archive=(),
        bead_plan_links={("alpha", "e1"): link},
        linked_plan_documents={},
        source_key=("src",),
        errors={},
    )
    contract = compile_provider_contract(
        kind="plan",
        label="Plan",
        icon="x",
        accent="#0",
        spec=None,
        provider_spec_digest="t",
    ).contract
    index = build_documents_relation_index(snapshot, contract=contract)
    proposal = ArtifactEntryTarget("ref:plan", ("alpha", "proposal", "p1"))
    active = ArtifactEntryTarget("ref:plan", ("alpha", "active", "/p.md"))
    assert index.edges_for_relation(proposal, "children")[0].target == active
    assert index.edges_for_relation(active, "parent")[0].target == proposal
    bead = index.edges_for_relation(proposal, "beads")[0]
    assert bead.target == ArtifactEntryTarget("beads", ("alpha", "epic", "e1"))


def test_provider_filename_family_and_declared_property() -> None:
    archive = (
        _archive("alpha", "/tmp/bundle.md", "bundle.md"),
        _archive(
            "alpha",
            "/tmp/bundle__a.md",
            "bundle__a.md",
            {"related": "bundle.md"},
        ),
        _archive("alpha", "/tmp/bundle__b.md", "bundle__b.md"),
        _archive("alpha", "/tmp/other.md", "other.md", {"related": "missing.md"}),
    )
    snapshot = PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={},
        plans_roots={},
        workspace_dirs={},
        proposals=(),
        active=(),
        archive=archive,
        bead_plan_links={},
        linked_plan_documents={},
        source_key=("src",),
        errors={},
        provider_kind="notes",
        provider_label="Note",
    )
    contract = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#0",
        spec={
            "schema_version": 1,
            "provider": "notes",
            "ref": {
                "kind": "notes",
                "icon": "¶",
                "expansion_format": (
                    "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
                ),
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
        provider_spec_digest="t",
    ).contract
    index = build_provider_relation_index(snapshot, contract=contract)
    parent = ArtifactEntryTarget("ref:notes", ("alpha", "archive", "/tmp/bundle.md"))
    member_a = ArtifactEntryTarget(
        "ref:notes", ("alpha", "archive", "/tmp/bundle__a.md")
    )
    other = ArtifactEntryTarget("ref:notes", ("alpha", "archive", "/tmp/other.md"))
    bundle_targets = {
        edge.target for edge in index.edges_for_relation(parent, "bundle")
    }
    assert member_a in bundle_targets
    related = index.edges_for_relation(member_a, "related")[0]
    assert related.target == parent
    assert related.dangling is False
    dangling = index.edges_for_relation(other, "related")[0]
    assert dangling.dangling is True
    assert dangling.target == ArtifactEntryTarget("ref:notes", ("missing.md",))


def _archive(
    project: str,
    path: str,
    relpath: str,
    frontmatter: dict[str, str] | None = None,
) -> ProjectArchive:
    return ProjectArchive(
        project,
        PlanSearchMatch(
            plan=Plan(
                source="repo",
                kind="notes",
                path=path,
                relpath=relpath,
                name=relpath,
                title=relpath,
                status="",
                created_at="",
                prompt_link="",
                summary="",
                body="",
                frontmatter=frontmatter or {},
            ),
            matched_fields=[],
            score=1.0,
        ),
    )


def _files_snapshot_with_link_rows(
    rows: tuple[dict[str, str], ...],
    *,
    extra_logical_ids: tuple[str, ...] = (),
) -> FilesSnapshot:
    logical_ids = ("doc", *extra_logical_ids)
    logical_rows: list[LogicalFile] = []
    for logical_id in logical_ids:
        version = FileVersion(
            version_id=f"{logical_id}-v1",
            logical_id=logical_id,
            label=logical_id,
            kind="file",
            origin="ref",
            origins=frozenset({"ref"}),
            created_at=None,
            agents=(),
            projects=("alpha",),
        )
        logical_rows.append(
            LogicalFile(
                logical_id=logical_id,
                label=logical_id,
                kind="file",
                versions=(version,),
                agents=(),
                projects=("alpha",),
                origins=frozenset({"ref"}),
                latest_seen_at=None,
            )
        )
    return FilesSnapshot(
        rows=tuple(logical_rows),
        project="alpha",
        complete=True,
        view_modes={f"{logical_id}-v1": "text" for logical_id in logical_ids},
        view_mode_counts={"text": len(logical_ids)},
        origin_counts={"ref": len(logical_ids)},
        artifact_links=ArtifactLinksSnapshot(
            rows=tuple({**row, "_project": "alpha"} for row in rows),
        ),
    )

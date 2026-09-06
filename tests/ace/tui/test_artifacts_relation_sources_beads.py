"""Focused coverage for the beads Artifacts relation source."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.relations import build_beads_relation_index
from sase.ace.tui.widgets.artifacts.beads_data_models import BeadsSnapshot, ProjectBead
from sase.bead.model import Dependency, Issue, IssueType, Status
from sase.core.artifact_entry_target import ArtifactEntryTarget


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

"""Tests for cross-project artifact-timestamp dedup collisions.

Artifact directories are named by launch timestamp (``YYYYmmddHHMMSS``) and the
loader keys agents throughout by ``raw_suffix = <timestamp dir name>``. That
name is only unique *within a single project's* artifact tree, so two unrelated
projects whose runs launched in the same clock second produce the same
``raw_suffix``. The dedup keys must therefore be project-scoped
(``(project_file, raw_suffix)``) so a running agent in project A is never
conflated with a workflow agent in project B that shares its launch second.

Regression coverage for the bug where a live TALE coder showed ``TALE DONE``
because an unrelated, already-completed workflow in another project shared its
artifact-timestamp dir name.
"""

from datetime import datetime

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    merge_incomplete_load_after_complete_history,
)
from sase.ace.tui.models._dedup import (
    dedup_running_vs_workflow,
    dedup_workflow_entries,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState, _apply_status_overrides


def _workflow_agent(
    *,
    project_file: str,
    raw_suffix: str,
    status: str,
    cl_name: str = "unknown",
    start_time: datetime | None = None,
    **kwargs: object,
) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=start_time,
        raw_suffix=raw_suffix,
        **kwargs,  # type: ignore[arg-type]
    )


def test_cross_project_collision_keeps_running_status_order_insensitive() -> None:
    """Two WORKFLOW agents with the same raw_suffix but different project_file.

    They belong to unrelated projects (a same-second launch collision), so they
    must NOT be deduped and the RUNNING one must keep RUNNING rather than
    inheriting the other project's DONE.
    """
    suffix = "20260608070834"

    for running_first in (True, False):
        running = _workflow_agent(
            project_file="/home/u/.sase/projects/bob-cli/bob-cli.sase",
            raw_suffix=suffix,
            status="RUNNING",
            cl_name="bob_coder",
            pid=36341,
        )
        done = _workflow_agent(
            project_file="/home/u/.sase/projects/sase/sase.sase",
            raw_suffix=suffix,
            status="DONE",
            cl_name="sase_fix_just",
            pid=62940,
        )

        agents = [running, done] if running_first else [done, running]
        result = dedup_workflow_entries(agents)

        # Both unrelated agents survive — no cross-project merge.
        assert len(result) == 2
        survivors = {a.cl_name: a for a in result}
        assert survivors["bob_coder"].status == "RUNNING"
        assert survivors["sase_fix_just"].status == "DONE"
        # pid/cl_name from the other project never bleed across.
        assert survivors["bob_coder"].pid == 36341
        assert survivors["sase_fix_just"].pid == 62940


def test_same_project_workflow_dedup_still_merges() -> None:
    """Regression guard: same project + same raw_suffix still dedupes & merges.

    The fix only narrows the match key; within one project the status-preference
    (RUNNING -> non-RUNNING) and metadata copies must be unchanged.
    """
    project = "/home/u/.sase/projects/proj/proj.sase"
    suffix = "20260101120000"

    # RUNNING field entry (seen first): no workspace_num, unknown cl_name, no pid.
    running_field = _workflow_agent(
        project_file=project,
        raw_suffix=suffix,
        status="RUNNING",
        cl_name="unknown",
        workflow="deploy",
    )
    # workflow_state.json entry: accurate DONE status + metadata.
    workflow_state = _workflow_agent(
        project_file=project,
        raw_suffix=suffix,
        status="DONE",
        cl_name="my_feature",
        workflow="deploy",
        workspace_num=7,
        pid=121415,
    )

    result = dedup_workflow_entries([running_field, workflow_state])

    assert len(result) == 1
    merged = result[0]
    # Status preference: RUNNING upgraded to the accurate DONE.
    assert merged.status == "DONE"
    # Metadata copied onto the surviving (first-seen) entry.
    assert merged.cl_name == "my_feature"
    assert merged.workspace_num == 7
    assert merged.pid == 121415


def test_family_resolution_survives_cross_project_collision() -> None:
    """Full scenario: live TALE coder keeps WORKING TALE despite a collision.

    A plan-chain root with plan_action="tale", its running coder, and an
    unrelated completed WORKFLOW agent in a *different* project that shares the
    coder's raw_suffix. After dedup + status overrides the coder and root must
    resolve to WORKING TALE / WORKING TALE (not TALE DONE) and the unrelated
    agent stays DONE.
    """
    project = "/home/u/.sase/projects/bob-cli/bob-cli.sase"
    other_project = "/home/u/.sase/projects/sase/sase.sase"
    root_suffix = "20260608070000"
    coder_suffix = "20260608070834"

    root = _workflow_agent(
        project_file=project,
        raw_suffix=root_suffix,
        status="DONE",
        cl_name="bob_feature",
        start_time=datetime(2026, 6, 8, 7, 0, 0),
        role_suffix="--plan",
        plan_action="tale",
        agent_family="bob_feature",
        agent_family_role="root",
        plan_chain_root=True,
    )
    coder = _workflow_agent(
        project_file=project,
        raw_suffix=coder_suffix,
        status="RUNNING",
        cl_name="bob_feature--code",
        start_time=datetime(2026, 6, 8, 7, 8, 34),
        parent_timestamp=root_suffix,
        role_suffix="--code",
        agent_family="bob_feature",
        agent_family_role="code",
    )
    # Unrelated, already-completed workflow in another project, same launch sec.
    unrelated = _workflow_agent(
        project_file=other_project,
        raw_suffix=coder_suffix,
        status="DONE",
        cl_name="sase_fix_just",
        start_time=datetime(2026, 6, 8, 7, 8, 34),
        pid=62940,
    )

    agents = dedup_workflow_entries([root, coder, unrelated])
    # All three survive dedup (no cross-project merge swallowed the coder).
    assert len(agents) == 3

    _apply_status_overrides(agents)

    assert coder.status == "WORKING TALE"
    assert root.status == "WORKING TALE"
    assert unrelated.status == "DONE"


def test_dedup_running_vs_workflow_cross_project_not_merged() -> None:
    """A RUNNING ace-run agent must not merge into a WORKFLOW from another project."""
    suffix = "20260608070834"

    running = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="bob_coder",
        project_file="/home/u/.sase/projects/bob-cli/bob-cli.sase",
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix=suffix,
    )
    workflow = _workflow_agent(
        project_file="/home/u/.sase/projects/sase/sase.sase",
        raw_suffix=suffix,
        status="DONE",
        cl_name="sase_fix_just",
        appears_as_agent=True,
    )

    result = dedup_running_vs_workflow([running, workflow])

    # Different projects — both survive, running keeps RUNNING.
    assert len(result) == 2
    assert {a.cl_name for a in result} == {"bob_coder", "sase_fix_just"}
    running_survivor = next(a for a in result if a.cl_name == "bob_coder")
    assert running_survivor.status == "RUNNING"


def test_dedup_running_vs_workflow_same_project_still_merges() -> None:
    """Same project + same raw_suffix: RUNNING ace-run still merges into WORKFLOW."""
    project = "/home/u/.sase/projects/proj/proj.sase"
    suffix = "20260329140000"

    running = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file=project,
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix=suffix,
        workspace_num=7,
    )
    workflow = _workflow_agent(
        project_file=project,
        raw_suffix=suffix,
        status="RUNNING",
        cl_name="unknown",
        appears_as_agent=True,
        pid=99999,
    )

    result = dedup_running_vs_workflow([running, workflow])

    assert len(result) == 1
    merged = result[0]
    assert merged.agent_type == AgentType.WORKFLOW
    assert merged.cl_name == "my_feature"
    assert merged.workspace_num == 7
    assert merged.pid == 99999


def test_incomplete_merge_artifact_row_recovery_key_is_project_scoped() -> None:
    """Same timestamp in different projects must not drive Tier-1 replacement."""
    suffix = "20260829072911"
    parent_suffix = "20260829061545"
    project_a = "/home/u/.sase/projects/project-a/project-a.sase"
    project_b = "/home/u/.sase/projects/project-b/project-b.sase"
    cached = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="project_a",
        project_file=project_a,
        status="RUNNING",
        start_time=None,
        raw_suffix=suffix,
        pid=111,
    )
    incoming_parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="project_b.parent",
        project_file=project_b,
        status="RUNNING",
        start_time=None,
        raw_suffix=parent_suffix,
        pid=222,
        agent_clan="project-b-clan",
    )
    incoming_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="project_b.child",
        project_file=project_b,
        status="RUNNING",
        start_time=None,
        raw_suffix=suffix,
        pid=333,
        parent_timestamp=parent_suffix,
        agent_family="project_b.parent",
        agent_clan="project-b-clan",
    )
    prep = PreparedApplyData(
        filtered_agents=[incoming_parent, incoming_child],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[cached],
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    suffix_rows = [
        agent for agent in prep.filtered_agents if agent.raw_suffix == suffix
    ]
    assert {(agent.project_file, agent.pid) for agent in suffix_rows} == {
        (project_a, 111),
        (project_b, 333),
    }


def test_dedup_running_vs_workflow_preserves_live_runner_provenance() -> None:
    """A richer workflow row retains proof from its verified RUNNING claim."""
    project = "/home/u/.sase/projects/proj/proj.sase"
    suffix = "20260706115800"
    running = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retry-family",
        project_file=project,
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix=suffix,
        pid=4242,
        runner_is_live=True,
    )
    workflow = _workflow_agent(
        project_file=project,
        raw_suffix=suffix,
        status="FAILED",
        cl_name="retry-family",
        appears_as_agent=True,
        pid=4242,
    )

    result = dedup_running_vs_workflow([running, workflow])

    assert result == [workflow]
    assert workflow.runner_is_live is True
    assert workflow.status == "RUNNING"
    bundle = workflow.to_bundle_dict()
    assert "runner_is_live" not in bundle
    assert Agent.from_bundle_dict(bundle).runner_is_live is False

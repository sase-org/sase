"""Tests for agent dedup status resolution (FAILED propagation, STARTING rules)."""

from unittest.mock import patch

from sase.ace.tui.models._dedup import dedup_running_vs_workflow
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_workflow_dedup_propagates_failed_status() -> None:
    """Test that dedup propagates FAILED status from workflow_state.json."""
    # Simulate RUNNING field entry (status=RUNNING, no PID)
    running_field_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="deploy",
        raw_suffix="20260101120000",
        workspace_num=5,
    )

    # Simulate workflow_state.json entry (status=FAILED, with PID)
    workflow_state_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=None,
        workflow="deploy",
        raw_suffix="20260101120000",
        pid=121415,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_patches",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[running_field_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[workflow_state_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
    ):
        result = load_all_agents()

    # Should be deduplicated to one agent
    assert len(result) == 1
    # Status should be FAILED (propagated from workflow_state.json)
    assert result[0].status == "FAILED"
    # Workspace num should be preserved from RUNNING field entry
    assert result[0].workspace_num == 5
    # PID should be propagated from workflow_state.json
    assert result[0].pid == 121415


def test_dedup_running_vs_workflow_starting_claim_never_downgrades_observed_status() -> (
    None
):
    """A claim row's placeholder STARTING must never overwrite an observed status.

    Regression test for the RUNNING/STARTING flap: STARTING on a claim row
    means "the claim source knows nothing about this agent yet", not an
    observation, so it must never win over a status the artifact record has
    already observed. Pre-fix, this merge downgraded the WORKFLOW row's
    RUNNING status back to STARTING, which also made the row disappear from
    the panel (STARTING rows are hidden).
    """
    project = "/tmp/test.sase"
    suffix = "20260101120000"

    workflow_running = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file=project,
        status="RUNNING",
        start_time=None,
        raw_suffix=suffix,
    )
    claim_starting = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="unknown",
        project_file=project,
        status="STARTING",
        start_time=None,
        workflow="ace(run)-260101_120000",
        raw_suffix=suffix,
    )

    result = dedup_running_vs_workflow([workflow_running, claim_starting])

    assert len(result) == 1
    assert result[0].status == "RUNNING"


def test_dedup_running_vs_workflow_sibling_status_branches_still_work() -> None:
    """The STARTING-skip must not regress the other status-resolution branches."""
    project = "/tmp/test.sase"

    # A terminal claim status still wins over a RUNNING workflow row.
    terminal_workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a",
        project_file=project,
        status="RUNNING",
        start_time=None,
        raw_suffix="20260101120001",
    )
    terminal_claim = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a",
        project_file=project,
        status="DONE",
        start_time=None,
        workflow="ace(run)-260101_120001",
        raw_suffix="20260101120001",
    )
    terminal_result = dedup_running_vs_workflow([terminal_workflow, terminal_claim])
    assert terminal_result[0].status == "DONE"

    # A FAILED workflow row with a live RUNNING claim still promotes.
    failed_workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="b",
        project_file=project,
        status="FAILED",
        start_time=None,
        raw_suffix="20260101120002",
    )
    failed_claim = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="b",
        project_file=project,
        status="RUNNING",
        start_time=None,
        workflow="ace(run)-260101_120002",
        raw_suffix="20260101120002",
    )
    failed_result = dedup_running_vs_workflow([failed_workflow, failed_claim])
    assert failed_result[0].status == "RUNNING"

    # A semantic status (PLAN) still overrides a bare RUNNING claim.
    plan_workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="c",
        project_file=project,
        status="PLAN",
        start_time=None,
        raw_suffix="20260101120003",
    )
    plan_claim = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="c",
        project_file=project,
        status="RUNNING",
        start_time=None,
        workflow="ace(run)-260101_120003",
        raw_suffix="20260101120003",
    )
    plan_result = dedup_running_vs_workflow([plan_workflow, plan_claim])
    assert plan_result[0].status == "PLAN"


def test_dedup_running_vs_workflow_agrees_across_broad_and_delta_shaped_inputs() -> (
    None
):
    """Anti-flap regression: broad load and delta load must agree on status.

    The artifact-delta refresh path never rescans ProjectSpec RUNNING claims
    (see ``_mark_live_artifact_delta_runners``), so its dedup input never
    includes a claim row for this agent -- only the observed WORKFLOW row.
    The broad refresh path always includes a fresh claim row, and until
    ``run_started_at`` is recorded that claim is STARTING. Pre-fix, that
    placeholder downgraded the already-observed RUNNING status on every
    broad refresh, so the row alternated visible (delta refresh) / hidden
    (broad refresh) — the flap the user saw. Both input shapes must now
    agree on the resulting status.
    """
    project = "/tmp/test.sase"
    suffix = "20260101130000"
    observed_running = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file=project,
        status="RUNNING",
        start_time=None,
        raw_suffix=suffix,
    )

    # Delta-load shape: no claim row rescanned, only the observed row.
    delta_result = dedup_running_vs_workflow([observed_running])
    assert delta_result[0].status == "RUNNING"

    # Broad-load shape: a fresh STARTING claim row is always present until
    # run_started_at is recorded.
    fresh_claim = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="unknown",
        project_file=project,
        status="STARTING",
        start_time=None,
        workflow="ace(run)-260101_130000",
        raw_suffix=suffix,
    )
    broad_result = dedup_running_vs_workflow([observed_running, fresh_claim])

    assert broad_result[0].status == delta_result[0].status == "RUNNING"

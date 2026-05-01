"""Tests for VCS workspace removal during agent dedup."""

from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from tests._agent_loader_helpers import _empty_artifact_snapshot

pytestmark = pytest.mark.usefixtures("python_agent_compose_backend")


def test_embedded_vcs_removed_by_axe_pid() -> None:
    """Test that embedded VCS workspace claims are removed when sharing PID with axe agent.

    When an axe(crs) agent embeds #hg, the VCS workflow claims its own workspace
    with a "hg-<cl_name>" workflow. Both share the same PID. The VCS entry should
    be removed entirely so it doesn't appear as a duplicate on the Agents tab,
    even when hidden agents are toggled visible.
    """
    # axe(crs) agent on workspace #100
    axe_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="axe(crs)-critique-260310_140240",
        raw_suffix="20260310140240",
        workspace_num=100,
        pid=781497,
    )

    # Embedded #hg workspace claim on workspace #101 (same PID)
    hg_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="hg-my_feature",
        raw_suffix=None,
        workspace_num=101,
        pid=781497,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[axe_agent, hg_agent],
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
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    # Only the axe agent should remain — the VCS workspace is removed entirely
    assert len(result) == 1
    assert result[0].workflow == "axe(crs)-critique-260310_140240"
    # workspace_num should be merged from the VCS agent (axe had 100, VCS had 101)
    # But axe already had workspace_num=100, so it stays 100 (only None fields merge)
    assert result[0].workspace_num == 100


def test_embedded_vcs_fields_merged_into_axe_agent() -> None:
    """Test that fields from VCS workspace agent are merged into the surviving axe agent.

    When an axe agent has no workspace_num/model but the VCS workspace does,
    those fields should be preserved on the axe agent after VCS removal.
    """
    # axe(crs) agent WITHOUT workspace_num or model
    axe_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="axe(crs)-critique-260310_140240",
        raw_suffix="20260310140240",
        workspace_num=None,
        pid=781497,
    )

    # Embedded #hg workspace claim WITH workspace_num and model
    hg_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="hg-my_feature",
        raw_suffix=None,
        workspace_num=101,
        pid=781497,
        model="gemini-2.5-pro",
        vcs_provider="Mercurial",
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[axe_agent, hg_agent],
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
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].workflow == "axe(crs)-critique-260310_140240"
    # Fields merged from VCS workspace agent
    assert result[0].workspace_num == 101
    assert result[0].model == "gemini-2.5-pro"
    assert result[0].vcs_provider == "Mercurial"


def test_embedded_vcs_removed_by_workflow_axe_pid() -> None:
    """Test VCS removal works when axe agent is WORKFLOW type (from workflow_state.json).

    The axe(crs) agent may be loaded as AgentType.WORKFLOW (from workflow_state.json)
    rather than AgentType.RUNNING. The VCS dedup should still collect the PID and
    remove the embedded VCS workspace claim.
    """
    # axe(crs) agent loaded as WORKFLOW type (from workflow_state.json)
    axe_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="axe(crs)-critique-260310_140240",
        raw_suffix="20260310140240",
        workspace_num=102,
        pid=781497,
    )

    # Embedded #hg workspace claim on workspace #103 (same PID)
    hg_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="hg-my_feature",
        raw_suffix=None,
        workspace_num=103,
        pid=781497,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[hg_agent],
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
            return_value=[axe_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    # Only the axe agent should remain — VCS workspace is removed
    assert len(result) == 1
    assert result[0].workflow == "axe(crs)-critique-260310_140240"


def test_embedded_vcs_removed_by_plain_workflow_name() -> None:
    """Test VCS removal when axe agent has plain workflow name (from workflow_state.json).

    When a fix-hook agent is loaded as WORKFLOW type with workflow="fix-hook"
    (plain name, not "axe(fix-hook)-..."), its PID should still be collected
    for VCS removal so the embedded #hg workspace claim gets removed.
    """
    # fix-hook agent loaded as WORKFLOW type (plain workflow name)
    fix_hook_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        raw_suffix="20260310173745",
        workspace_num=None,
        pid=2970578,
    )

    # Embedded #hg workspace claim on workspace #100 (same PID)
    hg_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="hg-my_feature",
        raw_suffix=None,
        workspace_num=100,
        pid=2970578,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[hg_agent],
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
            return_value=[fix_hook_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    # Only the fix-hook agent should remain — VCS workspace is removed
    assert len(result) == 1
    assert result[0].workflow == "fix-hook"


def test_embedded_vcs_removed_when_changespec_fix_hook_hidden() -> None:
    """Test VCS workspace removed even when the fix-hook agent comes from ChangeSpec.

    This reproduces the exact scenario: the fix-hook runner doesn't claim a workspace
    in the RUNNING field, so the fix-hook agent only exists as a ChangeSpec entry
    (with hidden=True, _from_changespec=True). The embedded #hg workspace shares
    the same PID. The VCS workspace should be removed entirely (not just hidden)
    to prevent duplicate PIDs when hidden agents are toggled visible.
    """
    from sase.ace.changespec import ChangeSpec, HookEntry, HookStatusLine

    # ChangeSpec HOOKS entry for the fix-hook agent (hidden=True, _from_changespec=True)
    mock_status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="260310_175213",
        status="RUNNING",
        suffix="fix_hook-3105619-260310_175213",
        suffix_type="running_agent",
    )

    mock_hook = HookEntry(
        command="bb_test :MediumTests", status_lines=[mock_status_line]
    )

    mock_cs = ChangeSpec(
        name="yserve_15_yp_fields",
        description="Test",
        parent=None,
        cl="881522624",
        status="Mailed",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        hooks=[mock_hook],
    )

    # Embedded #hg workspace claim on workspace #100 (same PID as fix-hook)
    hg_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="yserve_15_yp_fields",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="hg-yserve_15_yp_fields",
        raw_suffix=None,
        workspace_num=100,
        pid=3105619,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[mock_cs],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[hg_agent],
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
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    # Only the fix-hook ChangeSpec agent should remain — VCS workspace is removed
    assert len(result) == 1
    assert result[0].workflow == "fix-hook"
    assert result[0].hidden is True  # ChangeSpec agents are hidden by default
    # No agents with VCS workflow should remain
    hg_result = [a for a in result if a.workflow == "hg-yserve_15_yp_fields"]
    assert len(hg_result) == 0

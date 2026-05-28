"""Tests for running agent-backed chops through the shared runner."""

from pathlib import Path
from unittest.mock import patch

from sase.agent.launcher import AgentLaunchResult
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import read_chop_run, read_chop_run_log_tail

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_run_configured_chop_once_launches_agent_with_chop_env(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    chop = ChopConfig(name="my_agent", description="", agent="some prompt")

    launch_result = AgentLaunchResult(
        pid=4242,
        workspace_num=7,
        workspace_dir="/tmp/ws7",
        output_path="/tmp/out",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )
    with patch(
        "sase.agent.launcher.launch_agent_from_cwd", return_value=launch_result
    ) as mock_launch:
        outcome = run_configured_chop_once(
            lumberjack_name="agentj",
            chop=chop,
            axe_config=axe_config,
            source="manual",
            started_by="ace",
        )

    assert outcome.status == "agent_launched"
    assert outcome.agent_pid == 4242
    assert outcome.run_id is not None

    extra_env = mock_launch.call_args.kwargs["extra_env"]
    assert extra_env["SASE_CHOP_LUMBERJACK"] == "agentj"
    assert extra_env["SASE_CHOP_NAME"] == "my_agent"
    assert extra_env["SASE_CHOP_RUN_ID"]
    assert extra_env["SASE_CHOP_PROMPT_HASH"]

    entry = read_chop_run("agentj", "my_agent", outcome.run_id)
    assert entry is not None
    assert entry.status == "agent_launched"
    assert entry.agent_pid == 4242
    assert entry.source == "manual"
    assert entry.started_by == "ace"

    tail = read_chop_run_log_tail("agentj", "my_agent", outcome.run_id)
    assert "Launched agent chop 'my_agent' (PID 4242)" in tail
    assert "chop=my_agent lumberjack=agentj source=manual started_by=ace" in tail
    assert f"prompt_hash={extra_env['SASE_CHOP_PROMPT_HASH']}" in tail
    assert "agent_pid=4242 workspace=7 workspace_dir=/tmp/ws7 output=/tmp/out" in tail
    assert "project=proj workflow=ace(run)-260101_120000 cl=proj" in tail
    assert "prompt_preview='some prompt'" in tail


def test_run_configured_chop_once_dedupes_live_agent(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A live registry record blocks a duplicate manual launch."""
    from sase.axe.chop_agents import _record_chop_agent_launch

    chop = ChopConfig(name="my_agent", description="", agent="some prompt")
    _record_chop_agent_launch(
        lumberjack_name="agentj",
        chop_name="my_agent",
        run_id="prev",
        pid=99999,
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workspace_num=1,
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
        prompt="some prompt",
    )

    with (
        patch("sase.axe.chop_agents.is_process_running", return_value=True),
        patch("sase.agent.launcher.launch_agent_from_cwd") as mock_launch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="agentj",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "already_running"
    assert outcome.agent_pid == 99999
    mock_launch.assert_not_called()


def test_run_configured_chop_once_agent_launch_failure(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    chop = ChopConfig(name="my_agent", description="", agent="some prompt")
    with patch(
        "sase.agent.launcher.launch_agent_from_cwd",
        side_effect=RuntimeError("workspace plugin missing"),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="agentj",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "agent_failed"
    assert outcome.error is not None and "workspace plugin" in str(outcome.error)
    assert outcome.run_id is not None
    entry = read_chop_run("agentj", "my_agent", outcome.run_id)
    assert entry is not None
    assert entry.status == "failure"

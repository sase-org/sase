"""Tests for sase run workflow visibility in TUI.

Validates that:
- workflow loaders include artifacts/run/* directories
- dedup merges RUNNING 'run' with WORKFLOW entries (same timestamp)
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models._dedup import dedup_running_vs_workflow
from sase.ace.tui.models.agent_loader import load_tiered_agents
from sase.ace.tui.models._loaders._workflow_loaders import (
    _iter_workflow_timestamp_dirs,
    load_workflow_agents,
    load_workflow_states,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_models import StepState, StepStatus, Workflow, WorkflowStep


def test_iter_workflow_timestamp_dirs_includes_run(tmp_path: Path) -> None:
    """Verify _iter_workflow_timestamp_dirs() discovers artifacts/run/* directories."""
    # Build a fake ~/.sase/projects/myproj/artifacts/run/<timestamp> tree
    project_dir = tmp_path / "myproj"
    run_ts_dir = project_dir / "artifacts" / "run" / "20260329120000"
    run_ts_dir.mkdir(parents=True)

    # Also create a workflow-foo directory to confirm existing dirs still work
    wf_ts_dir = project_dir / "artifacts" / "workflow-foo" / "20260329110000"
    wf_ts_dir.mkdir(parents=True)

    # Patch Path.home so projects_dir = fake_home / ".sase" / "projects"
    fake_home = tmp_path.parent / "fakehome"
    sase_projects = fake_home / ".sase" / "projects" / "myproj" / "artifacts"
    sase_projects.mkdir(parents=True)

    # Symlink the artifacts subdirs into the fake home structure
    run_art = sase_projects / "run" / "20260329120000"
    run_art.mkdir(parents=True)
    wf_art = sase_projects / "workflow-foo" / "20260329110000"
    wf_art.mkdir(parents=True)

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.Path.home",
        return_value=fake_home,
    ):
        dirs = list(_iter_workflow_timestamp_dirs())

    dir_names = {d.name for _, d in dirs}
    assert "20260329120000" in dir_names, "run timestamp dir not discovered"
    assert "20260329110000" in dir_names, "workflow-foo timestamp dir not discovered"


def test_load_workflow_states_from_run_dir(tmp_path: Path) -> None:
    """Verify load_workflow_states() reads workflow_state.json under artifacts/run/."""
    fake_home = tmp_path / "fakehome"
    project_dir = fake_home / ".sase" / "projects" / "testproj"
    ts_dir = project_dir / "artifacts" / "run" / "20260329140000"
    ts_dir.mkdir(parents=True)

    state = {
        "status": "running",
        "appears_as_agent": True,
        "hidden": True,
        "pid": 12345,
        "context": {"cl_name": "my_cl"},
        "steps": [],
        "current_step_index": 0,
        "workflow_name": "run",
    }
    with open(ts_dir / "workflow_state.json", "w") as f:
        json.dump(state, f)

    with (
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.Path.home",
            return_value=fake_home,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
            return_value=True,
        ),
    ):
        entries = load_workflow_states()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.workflow_name == "run"
    assert entry.cl_name == "my_cl"
    assert entry.status == "RUNNING"
    assert entry.appears_as_agent is True
    assert entry.hidden is True
    assert entry.pid == 12345


def test_load_workflow_agents_maps_state_hidden_to_agent_hidden(
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "fakehome"
    ts_dir = (
        fake_home
        / ".sase"
        / "projects"
        / "testproj"
        / "artifacts"
        / "workflow-launcher"
        / "20260329140000"
    )
    ts_dir.mkdir(parents=True)
    with open(ts_dir / "workflow_state.json", "w") as f:
        json.dump(
            {
                "status": "running",
                "hidden": True,
                "context": {"cl_name": "my_cl"},
                "steps": [],
                "current_step_index": 0,
                "workflow_name": "launcher",
            },
            f,
        )

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.Path.home",
        return_value=fake_home,
    ):
        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].hidden is True


def test_write_workflow_state_refreshes_artifact_index(tmp_path: Path) -> None:
    """Initial workflow visibility writes refresh the Tier 1 artifact row."""
    from sase.axe.run_workflow_runner import _write_workflow_state

    with patch(
        "sase.axe.run_workflow_runner.update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        _write_workflow_state(
            str(tmp_path),
            "workflow-demo",
            "cl_demo",
            status="running",
        )

    update_index.assert_called_once_with(str(tmp_path))


def test_workflow_workspace_prep_recreates_companion_after_teardown() -> None:
    from sase.axe.run_workflow_runner import _prepare_workflow_workspace

    calls: list[str] = []
    with (
        patch(
            "sase.axe.run_workflow_runner.prepare_workspace",
            side_effect=lambda *_args, **_kwargs: calls.append("prepare") or True,
        ),
        patch(
            "sase.linked_repos.clear_workspace_repos",
            side_effect=lambda _workspace, _num: calls.append("clear"),
        ),
        patch(
            "sase.sdd.store.ensure_workspace_sdd_clone",
            side_effect=lambda _workspace, _num: calls.append("clone"),
        ),
    ):
        result = _prepare_workflow_workspace(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_basename="sase",
        )

    assert result is True
    assert calls == ["prepare", "clear", "clone"]


def test_workflow_workspace_prep_does_not_clear_after_failure() -> None:
    from sase.axe.run_workflow_runner import _prepare_workflow_workspace

    with (
        patch("sase.axe.run_workflow_runner.prepare_workspace", return_value=False),
        patch("sase.linked_repos.clear_workspace_repos") as clear_repos,
        patch("sase.sdd.store.ensure_workspace_sdd_clone") as ensure_clone,
    ):
        result = _prepare_workflow_workspace(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_basename="sase",
        )

    assert result is False
    clear_repos.assert_not_called()
    ensure_clone.assert_not_called()


@pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for Tier 1 loader integration tests.",
)
def test_write_workflow_state_is_visible_to_tier1_loader(tmp_path: Path) -> None:
    """A first workflow_state write is visible without a full-history scan."""
    from sase.axe.run_workflow_runner import _write_workflow_state

    fake_home = tmp_path / "home"
    projects_root = fake_home / ".sase" / "projects"
    artifacts_dir = (
        projects_root / "proj" / "artifacts" / "workflow-demo" / "20260521170000"
    )
    artifacts_dir.mkdir(parents=True)

    index_path = fake_home / ".sase" / "agent_artifact_index.sqlite"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    rebuild_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactScanOptionsWire(),
    )

    with patch("pathlib.Path.home", return_value=fake_home):
        _write_workflow_state(
            str(artifacts_dir),
            "workflow-demo",
            "cl_demo",
            status="running",
        )
        agents, load_state = load_tiered_agents(full_history=False)

    assert load_state.tier == "tier1"
    assert load_state.used_artifact_index is True
    assert any(
        agent.workflow == "workflow-demo"
        and agent.raw_suffix == "20260521170000"
        and agent.status == "RUNNING"
        for agent in agents
    )


def test_workflow_executor_state_and_step_markers_refresh_index(
    tmp_path: Path,
) -> None:
    """WorkflowExecutor refreshes the index for state and prompt-step writes."""
    workflow = Workflow(
        name="workflow-demo",
        steps=[WorkflowStep(name="step1", bash="echo ok")],
    )
    executor = WorkflowExecutor(workflow=workflow, args={}, artifacts_dir=str(tmp_path))

    with patch(
        "sase.xprompt.workflow_executor.update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        executor._save_state()
        executor._save_prompt_step_marker(
            "step1",
            StepState(name="step1", status=StepStatus.IN_PROGRESS),
        )

    assert update_index.call_count == 2
    update_index.assert_any_call(str(tmp_path))


def test_failed_workflow_state_refreshes_artifact_index(tmp_path: Path) -> None:
    """Validation-failure workflow_state writes update the Tier 1 row."""
    from sase.xprompt.workflow_runner import _write_failed_workflow_state

    with patch(
        "sase.xprompt.workflow_runner.update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        _write_failed_workflow_state(
            "workflow-demo",
            str(tmp_path),
            "bad workflow",
        )

    update_index.assert_called_once_with(str(tmp_path))


def test_dedup_running_vs_workflow_merges_plain_run() -> None:
    """Verify dedup merges RUNNING workflow='run' with WORKFLOW entry by timestamp."""
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix="20260329140000",
        workspace_num=7,
        model="claude-opus-4-20250514",
    )

    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="unknown",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix="20260329140000",
        appears_as_agent=True,
        pid=99999,
    )

    agents = [running_agent, workflow_agent]
    result = dedup_running_vs_workflow(agents)

    # RUNNING entry should be dropped; WORKFLOW kept with merged metadata
    assert len(result) == 1
    merged = result[0]
    assert merged.agent_type == AgentType.WORKFLOW
    assert merged.cl_name == "my_feature"
    assert merged.workspace_num == 7
    assert merged.model == "claude-opus-4-20250514"
    assert merged.pid == 99999
    assert merged.appears_as_agent is True


def test_dedup_running_vs_failed_workflow_keeps_live_status_for_retry() -> None:
    """A live outer runner keeps a failed inner workflow eligible for retry state."""
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retrying_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix="20260329140000",
    )
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retrying_feature",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=None,
        workflow="anonymous",
        raw_suffix="20260329140000",
        appears_as_agent=True,
    )

    result = dedup_running_vs_workflow([running_agent, workflow_agent])

    assert len(result) == 1
    assert result[0].agent_type == AgentType.WORKFLOW
    assert result[0].status == "RUNNING"


def test_dedup_workflow_prefers_terminal_retry_marker_and_lineage() -> None:
    """The authoritative done row supplies retry status and chain pointers."""
    done_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retrying_feature",
        project_file="/tmp/test.sase",
        status="FAILED (RETRIED)",
        start_time=None,
        workflow="ace-run",
        raw_suffix="20260329140000",
        retried_as_timestamp="20260329140100",
        retry_chain_root_timestamp="20260329140000",
        retry_terminal=True,
    )
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retrying_feature",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=None,
        workflow="anonymous",
        raw_suffix="20260329140000",
        appears_as_agent=True,
    )

    result = dedup_running_vs_workflow([done_agent, workflow_agent])

    assert len(result) == 1
    merged = result[0]
    assert merged.status == "FAILED (RETRIED)"
    assert merged.retried_as_timestamp == "20260329140100"
    assert merged.retry_chain_root_timestamp == "20260329140000"
    assert merged.retry_terminal is True


def test_dedup_running_vs_workflow_no_match_without_suffix() -> None:
    """RUNNING 'run' without matching suffix should NOT be deduped."""
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix="20260329140000",
    )

    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="other_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        workflow="run",
        raw_suffix="20260329150000",  # Different timestamp
        appears_as_agent=True,
    )

    agents = [running_agent, workflow_agent]
    result = dedup_running_vs_workflow(agents)

    # Both should survive — different timestamps
    assert len(result) == 2

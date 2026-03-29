"""Tests for sase run workflow visibility in TUI.

Validates that:
- workflow loaders include artifacts/run/* directories
- dedup merges RUNNING 'run' with WORKFLOW entries (same timestamp)
- synchronous run path writes initial workflow_state.json before execution
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models._dedup import dedup_running_vs_workflow
from sase.ace.tui.models._loaders._workflow_loaders import (
    _iter_workflow_timestamp_dirs,
    load_workflow_states,
)
from sase.ace.tui.models.agent import Agent, AgentType


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
    assert entry.pid == 12345


def test_dedup_running_vs_workflow_merges_plain_run() -> None:
    """Verify dedup merges RUNNING workflow='run' with WORKFLOW entry by timestamp."""
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
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


def test_dedup_running_vs_workflow_no_match_without_suffix() -> None:
    """RUNNING 'run' without matching suffix should NOT be deduped."""
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="run",
        raw_suffix="20260329140000",
    )

    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="other_cl",
        project_file="/tmp/test.gp",
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


def test_run_query_writes_initial_workflow_state(tmp_path: Path) -> None:
    """Verify run_query writes workflow_state.json before claim/execute."""
    artifacts_dir = str(tmp_path / "20260329160000")
    os.makedirs(artifacts_dir)

    # We abort at claim_workspace (which runs after the initial state write)
    # to verify the file was written before execution begins.
    class _EarlyExit(Exception):
        pass

    mock_multi = type(
        "M", (), {"local_xprompts": None, "frontmatter": None, "segments": []}
    )()
    mock_directives = type("D", (), {"model": None})()
    mock_provider_inst = type(
        "P", (), {"resolve_model_name": lambda self: "test-model"}
    )()

    with (
        patch(
            "sase.main.query_handler._query._resolve_vcs_cwd",
            return_value=None,
        ),
        patch(
            "sase.main.query_handler._query.ensure_project_file_and_get_workspace_num",
            return_value=("/tmp/test.gp", 1, "testproj"),
        ),
        patch(
            "sase.main.query_handler._query.create_artifacts_directory",
            return_value=artifacts_dir,
        ),
        patch("sase.xprompt.resolve_xprompt_aliases", side_effect=lambda q: q),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch("sase.agent.multi_prompt.parse_multi_prompt", return_value=mock_multi),
        patch("sase.core.time.generate_timestamp", return_value="260329_160000"),
        patch(
            "sase.xprompt.directives.extract_prompt_directives",
            return_value=("test", mock_directives),
        ),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="anthropic",
        ),
        patch(
            "sase.llm_provider.registry.get_provider",
            return_value=mock_provider_inst,
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch(
            "sase.main.query_handler._query.claim_workspace",
            side_effect=_EarlyExit("stop after claim"),
        ),
        patch("sase.main.query_handler._query.release_workspace"),
    ):
        try:
            from sase.main.query_handler._query import run_query

            run_query("hello")
        except _EarlyExit:
            pass  # Expected — we abort right after claim_workspace

    # The initial workflow_state.json should exist before claim was called
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    assert os.path.exists(state_path), "workflow_state.json not written before claim"

    with open(state_path) as f:
        data = json.load(f)

    assert data["status"] == "running"
    assert data["appears_as_agent"] is True
    assert data["steps"] == []
    assert data["workflow_name"] == "run"

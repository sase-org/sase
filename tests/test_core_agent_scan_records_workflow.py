"""Golden tests for running marker and workflow scan records."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_scan_facade import scan_agent_artifacts

from .agent_scan_golden.fixture_builder import TS_HOME_RUNNING, TS_WORKFLOW_ROOT
from .core_agent_scan_helpers import (
    core_agent_scan_fixture_root as _fixture_root,
    record_by_timestamp,
)


def test_home_running_record_has_running_marker(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_HOME_RUNNING)
    assert rec.project_name == "home"
    assert rec.workflow_dir_name == "ace-run"
    assert rec.running is not None
    assert rec.running.pid == 11111
    assert rec.running.cl_name == "~"
    assert rec.running.workspace_dir == "/tmp/home-target"
    assert rec.raw_prompt_snippet == "Investigate the failing job"


def test_workflow_root_record_has_state_and_steps(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)
    assert rec.workflow_dir_name == "workflow-three_phase"
    assert rec.workflow_state is not None
    state = rec.workflow_state
    assert state.workflow_name == "three_phase"
    assert state.cl_name == "feature_workflow"
    assert state.status == "completed"
    assert state.appears_as_agent is True
    assert state.is_anonymous is False
    assert state.hidden is False
    assert len(state.steps) == 3
    assert state.steps[0].name == "plan"
    assert state.steps[0].status == "completed"
    assert state.steps[0].output == {"plan_path": "/tmp/plan.md"}
    assert state.steps[0].output_types == {"plan_path": "path"}

    # plan_path.json projects through.
    assert rec.plan_path is not None
    assert rec.plan_path.plan_path == "/tmp/plan.md"

    # Three prompt-step markers, sorted by file name (the leading
    # zero-padded index matches the sort order).
    assert [m.file_name for m in rec.prompt_steps] == [
        "prompt_step_000_pre.json",
        "prompt_step_001_plan.json",
        "prompt_step_002_code.json",
    ]
    pre, plan, code = rec.prompt_steps
    assert pre.is_pre_prompt_step is True
    assert pre.embedded_workflow_name == "three_phase"
    assert plan.output is not None and plan.output.get("meta_workspace") == "5"
    assert code.hidden is True
    assert code.diff_path == "/tmp/diff.diff"


def test_workflow_state_hidden_is_parsed(fixture_root: Path) -> None:
    state_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "workflow-three_phase"
        / TS_WORKFLOW_ROOT
        / "workflow_state.json"
    )
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["hidden"] = True
    state_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)

    assert rec.workflow_state is not None
    assert rec.workflow_state.hidden is True

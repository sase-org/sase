"""Loader-level regression coverage for the propose-to-gate pending window.

Reproduces the incident where a planner's ``workflow_state.json`` is
rewritten to ``completed`` (hence ``DONE``) at plan-submission time, before
the review gate shell exists to carry the pending ``TALE``/``PLAN``/``EPIC``
status. Both the wire-snapshot and filesystem loader paths must surface the
pending tier status while the handoff window is open, and fall back to plain
``DONE`` once the gate has taken over (or the plan file's tier can't be
read).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_agents
from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_workflow_agents_from_snapshot,
)
from sase.ace.tui.models.workflow import WorkflowEntry
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
)

_PLAN_SUBMITTED_AT = "2026-09-05T11:08:10.185068+00:00"
_STOPPED_AT = "2026-09-05T11:16:34.061172+00:00"


def _write_tier_plan(path: Path, tier: str) -> None:
    path.write_text(f"---\ntier: {tier}\n---\n# Plan\n", encoding="utf-8")


def _snapshot(records: list[AgentArtifactRecordWire]) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
    )


def _workflow_record(
    tmp_path: Path,
    *,
    plan_path: str | None,
    stopped_at: str | None = None,
    pid: int | None = os.getpid(),
) -> AgentArtifactRecordWire:
    artifact_dir = tmp_path / "20260905064853"
    meta_kwargs: dict[str, object] = {
        "pid": pid,
        "plan": True,
        "plan_path": plan_path,
        "plan_submitted_at": [_PLAN_SUBMITTED_AT],
    }
    if stopped_at is not None:
        meta_kwargs["stopped_at"] = stopped_at
    return AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(tmp_path / "myproj"),
        project_file=str(tmp_path / "myproj" / "myproj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp="20260905064853",
        agent_meta=AgentMetaWire(**meta_kwargs),
        workflow_state=WorkflowStateWire(
            workflow_name="ace-run",
            status="completed",
            pid=pid,
            steps=[WorkflowStepStateWire(name="plan", status="completed")],
        ),
    )


def test_snapshot_workflow_row_reopens_pending_review_window(tmp_path: Path) -> None:
    plan_path = tmp_path / "tale.md"
    _write_tier_plan(plan_path, "tale")
    record = _workflow_record(tmp_path, plan_path=str(plan_path))

    agents = load_workflow_agents_from_snapshot(_snapshot([record]))

    assert len(agents) == 1
    assert agents[0].status == "TALE"


def test_snapshot_workflow_row_settles_to_done_after_stop(tmp_path: Path) -> None:
    plan_path = tmp_path / "tale.md"
    _write_tier_plan(plan_path, "tale")
    record = _workflow_record(
        tmp_path, plan_path=str(plan_path), stopped_at=_STOPPED_AT
    )

    agents = load_workflow_agents_from_snapshot(_snapshot([record]))

    assert len(agents) == 1
    assert agents[0].status == "DONE"


def test_snapshot_workflow_row_with_dead_pid_stays_done(tmp_path: Path) -> None:
    plan_path = tmp_path / "tale.md"
    _write_tier_plan(plan_path, "tale")
    record = _workflow_record(tmp_path, plan_path=str(plan_path), pid=99_999_999)

    agents = load_workflow_agents_from_snapshot(_snapshot([record]))

    assert len(agents) == 1
    assert agents[0].status == "DONE"


def test_snapshot_workflow_row_epic_tier(tmp_path: Path) -> None:
    plan_path = tmp_path / "epic.md"
    _write_tier_plan(plan_path, "epic")
    record = _workflow_record(tmp_path, plan_path=str(plan_path))

    agents = load_workflow_agents_from_snapshot(_snapshot([record]))

    assert len(agents) == 1
    assert agents[0].status == "EPIC"


def test_snapshot_workflow_row_unreadable_tier_falls_back_to_plan(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "no_tier.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    record = _workflow_record(tmp_path, plan_path=str(plan_path))

    agents = load_workflow_agents_from_snapshot(_snapshot([record]))

    assert len(agents) == 1
    assert agents[0].status == "PLAN"


def _filesystem_entry(artifacts_dir: Path) -> WorkflowEntry:
    return WorkflowEntry(
        workflow_name="ace-run",
        cl_name="test_cl",
        project_file="/fake/path.sase",
        status="DONE",
        current_step=0,
        total_steps=1,
        steps=[],
        start_time=None,
        artifacts_dir=str(artifacts_dir),
        pid=os.getpid(),
    )


def _write_meta(
    artifacts_dir: Path,
    *,
    plan_path: str,
    gate_id: str | None = None,
    gate_member_agent_name: str | None = None,
    stopped_at: str | None = None,
) -> None:
    meta: dict[str, object] = {
        "pid": os.getpid(),
        "plan": True,
        "plan_path": plan_path,
        "plan_submitted_at": _PLAN_SUBMITTED_AT,
    }
    if gate_id is not None:
        meta["gate_id"] = gate_id
    if gate_member_agent_name is not None:
        meta["gate_member_agent_name"] = gate_member_agent_name
    if stopped_at is not None:
        meta["stopped_at"] = stopped_at
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_filesystem_workflow_row_reopens_pending_review_window(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "tale.md"
    _write_tier_plan(plan_path, "tale")
    _write_meta(tmp_path, plan_path=str(plan_path))
    entry = _filesystem_entry(tmp_path)

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.load_workflow_states",
        return_value=[entry],
    ):
        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].status == "TALE"


def test_filesystem_workflow_row_settles_to_done_after_gate_handoff(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "tale.md"
    _write_tier_plan(plan_path, "tale")
    _write_meta(
        tmp_path,
        plan_path=str(plan_path),
        gate_id="gate-123",
        gate_member_agent_name="sase-ws.3.g0",
        stopped_at=_STOPPED_AT,
    )
    entry = _filesystem_entry(tmp_path)

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.load_workflow_states",
        return_value=[entry],
    ):
        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].status == "DONE"


def test_filesystem_workflow_row_with_gate_id_stays_done(tmp_path: Path) -> None:
    plan_path = tmp_path / "tale.md"
    _write_tier_plan(plan_path, "tale")
    _write_meta(tmp_path, plan_path=str(plan_path), gate_id="gate-123")
    entry = _filesystem_entry(tmp_path)

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.load_workflow_states",
        return_value=[entry],
    ):
        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].status == "DONE"


def test_filesystem_workflow_row_epic_tier(tmp_path: Path) -> None:
    plan_path = tmp_path / "epic.md"
    _write_tier_plan(plan_path, "epic")
    _write_meta(tmp_path, plan_path=str(plan_path))
    entry = _filesystem_entry(tmp_path)

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.load_workflow_states",
        return_value=[entry],
    ):
        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].status == "EPIC"


def test_filesystem_workflow_row_unreadable_tier_falls_back_to_plan(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "no_tier.md"
    plan_path.write_text("# Plan\n", encoding="utf-8")
    _write_meta(tmp_path, plan_path=str(plan_path))
    entry = _filesystem_entry(tmp_path)

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.load_workflow_states",
        return_value=[entry],
    ):
        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].status == "PLAN"

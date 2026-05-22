"""End-to-end loader regression for TALE APPROVED plan-chain families.

After ``sase plan`` SIGTERMs the planner process, the family-root artifact
dir can legitimately end up with only ``agent_meta.json`` on disk (no
``workflow_state.json``, no ``prompt_step_*.json``).  The TUI Agents tab
must still render:

- the family root ``@<family>`` row with ``TALE APPROVED`` status
- a planner workflow step row ``<family>-plan`` (status ``DONE`` once the
  plan is approved and a coder follow-up exists)
- the coder follow-up row ``@<family>-code`` (status ``TALE APPROVED``
  while the coder runs)

These tests pin the failing on-disk shape so the regression cannot return
silently when the loader stack is refactored.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import (
    _apply_status_overrides,
    load_tiered_agents,
)
from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
)
from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_missing_plan_root_parents,
    load_plan_root_agents_from_snapshot,
)
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
)


_FAMILY = "fam"
_PLAN_TS = "20260522115443"
_CODE_TS = "20260522120022"


def _project_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "sase"
    project_file = project_dir / "sase.gp"
    artifacts_root = project_dir / "artifacts" / "ace-run"
    artifacts_root.mkdir(parents=True)
    project_file.write_text("NAME: sase\n", encoding="utf-8")
    planner_dir = artifacts_root / _PLAN_TS
    planner_dir.mkdir()
    coder_dir = artifacts_root / _CODE_TS
    coder_dir.mkdir()
    return projects_root, planner_dir, coder_dir


def _planner_meta() -> dict[str, object]:
    return {
        "pid": 1,
        "name": _FAMILY,
        "workflow_name": _FAMILY,
        "role_suffix": "-plan",
        "agent_family": _FAMILY,
        "agent_family_role": "root",
        "plan_chain_root": True,
        "plan_action": "tale",
        "plan_approved": True,
        "plan_submitted_at": "2026-05-22T15:58:01.248929+00:00",
        "cl_name": "sase",
        "changespec_name": "sase",
    }


def _coder_meta() -> dict[str, object]:
    return {
        "pid": 1,
        "name": f"{_FAMILY}-code",
        "workflow_name": _FAMILY,
        "role_suffix": "-code",
        "agent_family": _FAMILY,
        "agent_family_role": "code",
        "parent_timestamp": _PLAN_TS,
        "plan_chain_parent_timestamp": _PLAN_TS,
        "cl_name": "sase",
        "changespec_name": "sase",
    }


def _coder_state() -> dict[str, object]:
    return {
        "workflow_name": _FAMILY,
        "status": "running",
        "current_step_index": 0,
        "steps": [
            {
                "name": "main",
                "status": "in_progress",
                "output": None,
                "error": None,
                "traceback": None,
                "hidden": False,
                "output_types": None,
                "iteration_errors": [],
            }
        ],
        "context": {"cl_name": "sase"},
        "artifacts_dir": "",
        "pid": 1,
        "appears_as_agent": True,
        "is_anonymous": False,
        "hidden": False,
    }


def _coder_step_marker() -> dict[str, object]:
    return {
        "file_name": "prompt_step_main.json",
        "workflow_name": _FAMILY,
        "step_name": "main",
        "step_type": "agent",
        "status": "in_progress",
        "step_index": 0,
        "total_steps": 1,
        "output": None,
    }


def _str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _int(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) else None


def _meta_wire(data: dict[str, object]) -> AgentMetaWire:
    submitted = _str(data, "plan_submitted_at")
    return AgentMetaWire(
        name=_str(data, "name"),
        cl_name=_str(data, "cl_name"),
        workflow_name=_str(data, "workflow_name"),
        agent_family=_str(data, "agent_family"),
        agent_family_role=_str(data, "agent_family_role"),
        plan_chain_root=bool(data.get("plan_chain_root", False)),
        pid=_int(data, "pid"),
        role_suffix=_str(data, "role_suffix"),
        parent_timestamp=_str(data, "parent_timestamp"),
        plan=bool(data.get("plan", False)),
        plan_approved=bool(data.get("plan_approved", False)),
        plan_action=_str(data, "plan_action"),
        plan_submitted_at=[submitted] if submitted else [],
    )


def _planner_record(planner_dir: Path) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="sase",
        project_dir=str(planner_dir.parent.parent.parent),
        project_file=str(planner_dir.parent.parent.parent / "sase.gp"),
        workflow_dir_name="ace-run",
        artifact_dir=str(planner_dir),
        timestamp=_PLAN_TS,
        agent_meta=_meta_wire(_planner_meta()),
    )


def test_planner_with_meta_only_dir_surfaces_as_plan_chain_root(
    tmp_path: Path,
) -> None:
    """Planner dirs without workflow_state.json still emit a family-root Agent."""
    _, planner_dir, _ = _project_layout(tmp_path)
    (planner_dir / "agent_meta.json").write_text(
        json.dumps(_planner_meta()), encoding="utf-8"
    )

    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(tmp_path / "projects"),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[_planner_record(planner_dir)],
    )

    with patch(
        "sase.ace.tui.models._loaders._workflow_snapshot_loaders.is_process_running",
        return_value=True,
    ):
        agents = load_plan_root_agents_from_snapshot(snapshot)

    assert len(agents) == 1
    root = agents[0]
    assert root.raw_suffix == _PLAN_TS
    assert root.plan_chain_root is True
    assert root.agent_family == _FAMILY
    assert root.agent_family_role == "root"
    assert root.agent_name == _FAMILY
    assert root.plan_action == "tale"
    assert root.appears_as_agent is True


def test_missing_planner_parent_is_self_healed_from_disk(tmp_path: Path) -> None:
    """Follow-up agents referencing a snapshot-absent parent recover via disk read."""
    _, planner_dir, coder_dir = _project_layout(tmp_path)
    (planner_dir / "agent_meta.json").write_text(
        json.dumps(_planner_meta()), encoding="utf-8"
    )
    (coder_dir / "agent_meta.json").write_text(
        json.dumps(_coder_meta()), encoding="utf-8"
    )

    coder_followup = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file=str(planner_dir.parent.parent.parent / "sase.gp"),
        status="RUNNING",
        start_time=None,
        raw_suffix=_CODE_TS,
        parent_timestamp=_PLAN_TS,
        artifacts_dir=str(coder_dir),
        agent_family=_FAMILY,
        agent_family_role="code",
        role_suffix="-code",
    )
    with patch(
        "sase.ace.tui.models._loaders._workflow_snapshot_loaders.is_process_running",
        return_value=True,
    ):
        recovered = load_missing_plan_root_parents([coder_followup])

    assert len(recovered) == 1
    root = recovered[0]
    assert root.raw_suffix == _PLAN_TS
    assert root.plan_chain_root is True
    assert root.agent_family == _FAMILY
    assert root.plan_action == "tale"


def test_workflow_child_identity_derives_coder_role(tmp_path: Path) -> None:
    """Coder workflow steps pick up ``-code`` identity from agent_meta."""
    _, _, coder_dir = _project_layout(tmp_path)
    (coder_dir / "agent_meta.json").write_text(
        json.dumps(_coder_meta()), encoding="utf-8"
    )

    coder_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file=str(coder_dir.parent.parent.parent / "sase.gp"),
        status="RUNNING",
        start_time=None,
        raw_suffix=_CODE_TS,
        parent_workflow=_FAMILY,
        parent_timestamp=_CODE_TS,
        step_name="main",
        step_type="agent",
        artifacts_dir=str(coder_dir),
    )
    enrich_agent_from_meta(coder_step, str(coder_dir), workflow_child=True)

    assert coder_step.role_suffix == "-code"
    assert coder_step.agent_family_role == "code"
    assert coder_step.agent_family == _FAMILY
    assert coder_step.agent_name == f"{_FAMILY}-code"


def test_tale_approved_family_renders_root_planner_and_coder(tmp_path: Path) -> None:
    """Full loader emits root, planner-step, and coder rows for a TALE family."""
    projects_root, planner_dir, coder_dir = _project_layout(tmp_path)
    (planner_dir / "agent_meta.json").write_text(
        json.dumps(_planner_meta()), encoding="utf-8"
    )
    (coder_dir / "agent_meta.json").write_text(
        json.dumps(_coder_meta()), encoding="utf-8"
    )
    (coder_dir / "workflow_state.json").write_text(
        json.dumps(_coder_state()), encoding="utf-8"
    )
    (coder_dir / "prompt_step_main.json").write_text(
        json.dumps(_coder_step_marker()), encoding="utf-8"
    )

    real_snapshot = scan_agent_artifacts(
        projects_root,
        AgentArtifactScanOptionsWire(
            include_prompt_step_markers=True,
            include_raw_prompt_snippets=False,
        ),
    )

    def _fake_index(*, full_history: bool):
        from sase.ace.tui.models.agent_loader import AgentLoadState

        state = AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        )
        return real_snapshot, state

    with (
        patch(
            "sase.ace.tui.models.agent_loader._artifact_snapshot_for_tui_load",
            side_effect=_fake_index,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_snapshot_loaders.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
    ):
        agents, _ = load_tiered_agents(full_history=False)

    by_suffix = {a.raw_suffix: a for a in agents if a.raw_suffix}
    assert _PLAN_TS in by_suffix, [
        (a.raw_suffix, a.agent_name, a.status) for a in agents
    ]
    assert _CODE_TS in by_suffix, [
        (a.raw_suffix, a.agent_name, a.status) for a in agents
    ]
    root = by_suffix[_PLAN_TS]
    coder = by_suffix[_CODE_TS]
    assert root.plan_chain_root is True
    assert root.agent_family == _FAMILY
    assert root.status == "TALE APPROVED"
    assert coder.parent_timestamp == _PLAN_TS
    assert coder.status == "TALE APPROVED"


def test_apply_status_overrides_renders_full_tale_family() -> None:
    """``apply_status_overrides`` with a meta-only planner produces the expected rows."""
    planner = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/sase.gp",
        status="DONE",
        start_time=None,
        raw_suffix=_PLAN_TS,
        plan_chain_root=True,
        agent_family=_FAMILY,
        agent_family_role="root",
        role_suffix="-plan",
        plan_action="tale",
        agent_name=_FAMILY,
    )
    coder = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/sase.gp",
        status="RUNNING",
        start_time=None,
        raw_suffix=_CODE_TS,
        parent_timestamp=_PLAN_TS,
        role_suffix="-code",
        agent_family=_FAMILY,
        agent_family_role="code",
        agent_name=f"{_FAMILY}-code",
    )
    agents = [planner, coder]
    _apply_status_overrides(agents)

    # Root mirrors the coder follow-up's TALE APPROVED state.
    assert planner.status == "TALE APPROVED"
    assert coder.status == "TALE APPROVED"
    # Planner-child synthesis added a logical ``-plan`` row carrying the
    # planner-side history (DONE because the coder follow-up exists).
    synth = [
        a
        for a in agents
        if a.role_suffix == "-plan"
        and a is not planner
        and a.agent_family_role == "plan"
    ]
    assert synth, [a.agent_name for a in agents]
    assert synth[0].status == "DONE"

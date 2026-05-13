from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.repro import (
    capture_agents_tab_repro_bundle,
    check_bundle_invariants,
    enable_agents_tab_repro_capture,
    load_bundle,
    record_agents_tab_app_projection,
    record_agents_tab_loader_result,
)


_TIER1_STATE = AgentLoadState(
    tier="tier1",
    complete_history=False,
    artifact_source="artifact_index",
    used_artifact_index=True,
)


def _agent(
    cl_name: str,
    raw_suffix: str,
    *,
    agent_name: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/private_project/private_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 13, 12, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_num=100,
        workspace_dir="/home/bryan/projects/private_project_100",
    )


class _App:
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_identity = None
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._agents_seen_complete_history = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_full_history = False
        self._hidden_count = 0
        self._grouping_mode = "standard"
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._fold_manager = FoldStateManager()
        self._agent_search_query = ""
        self._agent_load_state = _TIER1_STATE
        self._agents_repro_capture = None


def _record_cycle(app: _App, agent: Agent, *, source: str = "test") -> None:
    record_agents_tab_loader_result(
        app,
        load_state=_TIER1_STATE,
        agents=[agent],
        dismissed_from_loader=[],
        on_agents_tab=True,
        selected_identity=agent.identity,
        source=source,
    )
    app._agents = [agent]
    app._agents_with_children = [agent]
    record_agents_tab_app_projection(app, load_state=_TIER1_STATE, source="apply")


def test_capture_ring_is_disabled_until_enabled() -> None:
    app = _App()
    agent = _agent("private_cl", "20260513120000")

    _record_cycle(app, agent)

    assert app._agents_repro_capture is None


def test_capture_ring_keeps_last_three_load_apply_cycles() -> None:
    app = _App()
    ring = enable_agents_tab_repro_capture(app, capacity=3)

    for index in range(4):
        _record_cycle(app, _agent(f"private_cl_{index}", f"2026051312000{index}"))

    steps = ring.steps
    assert [step.step_id for step in steps] == [
        "capture_0002",
        "capture_0003",
        "capture_0004",
    ]
    assert all(step.metadata["visible_row_count"] == 1 for step in steps)
    assert all(step.metadata["loaded_row_count"] == 1 for step in steps)


def test_redacted_capture_bundle_loads_against_schema(tmp_path: Path) -> None:
    app = _App()
    enable_agents_tab_repro_capture(app, capacity=3)
    agent = _agent(
        "secret/customer/project",
        "20260513123000",
        agent_name="customer-agent-name",
    )
    _record_cycle(app, agent)

    bundle_path = capture_agents_tab_repro_bundle(app, tmp_path, commit_safe=True)
    raw = bundle_path.read_text(encoding="utf-8")
    bundle = load_bundle(bundle_path)

    assert bundle.manifest.commit_safe is True
    assert bundle.load_steps[0].agent_rows[0].raw_suffix == "20260513123000"
    assert bundle.load_steps[0].agent_rows[0].agent_name is None
    assert "secret/customer/project" not in raw
    assert "customer-agent-name" not in raw
    check_bundle_invariants(bundle).assert_ok()

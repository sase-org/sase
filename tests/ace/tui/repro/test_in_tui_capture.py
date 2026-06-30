from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.repro import (
    enable_agents_tab_repro_capture,
    load_bundle,
    record_agents_tab_app_projection,
    record_agents_tab_loader_result,
    set_agents_tab_repro_auto_check,
)


_TIER1_STATE = AgentLoadState(
    tier="tier1",
    complete_history=False,
    artifact_source="artifact_index",
    used_artifact_index=True,
)
_TIER2_STATE = AgentLoadState(
    tier="tier2",
    complete_history=True,
    artifact_source="source_scan",
    used_artifact_index=False,
)


def _agent(cl_name: str, raw_suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/repro/repro.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 13, 12, 0, 0),
        raw_suffix=raw_suffix,
        workspace_num=100,
        workspace_dir="/tmp/projects/repro_100",
    )


def _empty_load_result() -> _AgentDiskLoadResult:
    return _AgentDiskLoadResult(
        all_agents=[],
        dismissed_from_loader=[],
        load_state=_TIER1_STATE,
    )


async def test_leader_capture_action_writes_valid_bundle(tmp_path: Path) -> None:
    with patch(
        "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
        return_value=_empty_load_result(),
    ):
        async with AcePage() as page:
            # Agents-first order: Shift+Tab moves PRs -> Agents.
            await page.press("shift+tab")
            page.app._agents_repro_output_dir = str(tmp_path)

            leader = page.app._keymap_registry.leader_mode
            capture_key = leader.keys["capture_agents_repro"]
            assert isinstance(capture_key, str)
            await page.press(leader.prefix, capture_key)

    bundle_paths = list(tmp_path.glob("*/agents_tab_repro.json"))
    assert len(bundle_paths) == 1
    bundle = load_bundle(bundle_paths[0])
    assert bundle.manifest.source == "in_tui_ring_buffer"
    assert bundle.manifest.commit_safe is True
    assert len(bundle.load_steps) >= 1


class _App:
    def __init__(self, output_dir: Path) -> None:
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
        self._group_fold_registry = None
        self._fold_manager = None
        self._agent_search_query = ""
        self._agent_load_state = _TIER1_STATE
        self._agents_repro_capture = None
        self._agents_repro_auto_check_enabled = False
        self._agents_repro_auto_capture_burst_active = False
        self._agents_repro_last_invariant_failures = []
        self._agents_repro_output_dir = str(output_dir)


def _record_cycle(
    app: _App,
    agents: list[Agent],
    *,
    load_state: AgentLoadState,
) -> None:
    record_agents_tab_loader_result(
        app,
        load_state=load_state,
        agents=agents,
        dismissed_from_loader=[],
        on_agents_tab=True,
        selected_identity=agents[0].identity if agents else None,
        source="test",
    )
    app._agents = agents
    app._agents_with_children = agents
    app._agents_seen_complete_history = load_state.complete_history
    app._agent_load_state = load_state
    record_agents_tab_app_projection(app, load_state=load_state, source="apply")


def test_auto_capture_writes_once_per_violation_burst(tmp_path: Path) -> None:
    app = _App(tmp_path)
    enable_agents_tab_repro_capture(app)
    set_agents_tab_repro_auto_check(app, enabled=True)
    first = _agent("current", "20260513120000")
    historical = _agent("historical", "20260512120000")

    _record_cycle(app, [first, historical], load_state=_TIER2_STATE)
    _record_cycle(app, [first], load_state=_TIER1_STATE)
    _record_cycle(app, [first], load_state=_TIER1_STATE)

    assert len(list(tmp_path.glob("*/agents_tab_repro.json"))) == 1
    assert app._agents_repro_auto_capture_burst_active is True
    assert app._agents_repro_last_invariant_failures

    _record_cycle(app, [first, historical], load_state=_TIER2_STATE)
    assert app._agents_repro_auto_capture_burst_active is False

    _record_cycle(app, [first], load_state=_TIER1_STATE)
    assert len(list(tmp_path.glob("*/agents_tab_repro.json"))) == 2

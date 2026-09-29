"""Shared helpers for agent cleanup facade tests.

Facade preserving the original
``tests.test_core_facade._agent_cleanup_helpers`` import path. The builders
now live in :mod:`tests.test_core_facade._agent_cleanup_builders` and the
scenarios in :mod:`tests.test_core_facade._agent_cleanup_scenarios` and
:mod:`tests.test_core_facade._agent_cleanup_session_scenarios`; they are
re-exported here (public names only), so existing imports keep working.
"""

from __future__ import annotations

import pytest

from tests.test_core_facade._agent_cleanup_builders import (
    START_TIME,
    STOP_TIME,
    make_agent,
    make_identity,
    make_request,
)
from tests.test_core_facade._agent_cleanup_scenarios import (
    scenario_clan_scope,
    scenario_clan_scope_active_parallel_agent_session,
    scenario_collapsed_group,
    scenario_duplicate_child_inputs,
    scenario_focused_panel_dismiss,
    scenario_focused_panel_kill_dismiss,
    scenario_marked_set,
    scenario_pidless_dismiss_fallback,
    scenario_tribe_scope,
    scenario_workflow_parent_with_children,
)
from tests.test_core_facade._agent_cleanup_session_scenarios import (
    scenario_clan_sequential_agent_session_dismiss,
    scenario_custom_child_running,
    scenario_direct_live_monitor,
    scenario_done_live_runner_dismiss,
    scenario_explicit_child_done,
    scenario_explicit_child_running,
    scenario_explicit_clan_sequential_agent_session_dismiss,
    scenario_failed_live_runner_dismiss_completed,
    scenario_failed_live_runner_kill,
    scenario_owner_cascades_live_monitor,
    scenario_parallel_agent_session_root,
)

SCENARIOS = [
    pytest.param(scenario_focused_panel_dismiss, id="focused-panel-dismiss-done"),
    pytest.param(
        scenario_focused_panel_kill_dismiss,
        id="focused-panel-kill-dismiss",
    ),
    pytest.param(scenario_marked_set, id="marked-set"),
    pytest.param(scenario_collapsed_group, id="collapsed-group"),
    pytest.param(scenario_tribe_scope, id="tribe-scope"),
    pytest.param(scenario_clan_scope, id="clan-scope"),
    pytest.param(
        scenario_clan_scope_active_parallel_agent_session,
        id="clan-scope-active-parallel-agent-session",
    ),
    pytest.param(
        scenario_workflow_parent_with_children,
        id="workflow-parent-cascade",
    ),
    pytest.param(scenario_pidless_dismiss_fallback, id="pidless-dismiss-fallback"),
    pytest.param(scenario_duplicate_child_inputs, id="duplicate-child-inputs"),
    pytest.param(scenario_explicit_child_running, id="explicit-child-running"),
    pytest.param(scenario_explicit_child_done, id="explicit-child-done"),
    pytest.param(scenario_custom_child_running, id="custom-child-running"),
    pytest.param(
        scenario_parallel_agent_session_root, id="parallel-agent-session-root"
    ),
    pytest.param(
        scenario_clan_sequential_agent_session_dismiss,
        id="clan-sequential-agent-session-dismiss",
    ),
    pytest.param(
        scenario_explicit_clan_sequential_agent_session_dismiss,
        id="explicit-clan-sequential-agent-session-dismiss",
    ),
    pytest.param(scenario_direct_live_monitor, id="direct-live-monitor"),
    pytest.param(scenario_owner_cascades_live_monitor, id="owner-cascade-monitor"),
    pytest.param(scenario_failed_live_runner_kill, id="failed-live-runner-kill"),
    pytest.param(
        scenario_failed_live_runner_dismiss_completed,
        id="failed-live-runner-dismiss-completed",
    ),
    pytest.param(scenario_done_live_runner_dismiss, id="done-live-runner-dismiss"),
]

__all__ = [
    "SCENARIOS",
    "START_TIME",
    "STOP_TIME",
    "make_agent",
    "make_identity",
    "make_request",
    "scenario_clan_scope",
    "scenario_clan_scope_active_parallel_agent_session",
    "scenario_clan_sequential_agent_session_dismiss",
    "scenario_collapsed_group",
    "scenario_custom_child_running",
    "scenario_direct_live_monitor",
    "scenario_done_live_runner_dismiss",
    "scenario_duplicate_child_inputs",
    "scenario_explicit_child_done",
    "scenario_explicit_child_running",
    "scenario_explicit_clan_sequential_agent_session_dismiss",
    "scenario_failed_live_runner_dismiss_completed",
    "scenario_failed_live_runner_kill",
    "scenario_focused_panel_dismiss",
    "scenario_focused_panel_kill_dismiss",
    "scenario_marked_set",
    "scenario_owner_cascades_live_monitor",
    "scenario_parallel_agent_session_root",
    "scenario_pidless_dismiss_fallback",
    "scenario_tribe_scope",
    "scenario_workflow_parent_with_children",
]

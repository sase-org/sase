"""Roster-latch orchestration for Agents-tab baseline reads.

The first load of a session, a committed-query change, and recovery after a
partial replacement read the whole visible inbox as a baseline (no viewport
window). Refreshes after a same-query baseline stay windowed patches, and a
partial roster arms prompt completion with the short input-quiet threshold.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents._loading_disk_viewport import (
    agents_viewport_for_load,
    current_agents_history_query_key,
)
from sase.ace.tui.actions.agents._loading_refresh_polling import (
    ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S,
)
from sase.ace.tui.models.agent_loader import AgentLoadState
from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent
from tests.ace.tui._lazy_tier2_reconcile_helpers import apply_load


def _baseline_state(**overrides: Any) -> AgentLoadState:
    kwargs: dict[str, Any] = {
        "tier": "tier1",
        "complete_history": False,
        "complete_visible_inbox": True,
        "artifact_source": "artifact_index",
        "used_artifact_index": True,
        "bounded_prefix": False,
        "truncated": False,
    }
    kwargs.update(overrides)
    return AgentLoadState(**kwargs)  # type: ignore[arg-type]


def _bounded_patch_state(**overrides: Any) -> AgentLoadState:
    kwargs: dict[str, Any] = {
        "tier": "tier1",
        "complete_history": False,
        "complete_visible_inbox": True,
        "artifact_source": "artifact_index",
        "used_artifact_index": True,
        "bounded_prefix": True,
        "requested_limit": 126,
        "returned_count": 126,
        "has_more": True,
    }
    kwargs.update(overrides)
    return AgentLoadState(**kwargs)  # type: ignore[arg-type]


def test_first_load_and_query_change_read_baseline() -> None:
    """No latch yet (or a new query): the provider issues a baseline read."""
    app = FakeAgentApp()

    assert agents_viewport_for_load(app) is None

    apply_load(app, _baseline_state())
    assert app._agents_roster_complete_query_key == current_agents_history_query_key(
        app
    )

    assert agents_viewport_for_load(app) is not None

    app._agent_search_query = "model:gpt-5"
    assert agents_viewport_for_load(app) is None


def test_bounded_patch_over_baseline_keeps_latch() -> None:
    """A same-query bounded patch leaves the roster-complete latch alone."""
    app = FakeAgentApp()
    apply_load(app, _baseline_state())
    latch = app._agents_roster_complete_query_key
    assert latch is not None

    app._agents_with_children = [_make_agent(cl_name="cached")]
    apply_load(app, _bounded_patch_state())

    assert app._agents_roster_complete_query_key == latch


def test_partial_replacement_clears_latch() -> None:
    """A partial load with no same-query cache to patch over clears the latch."""
    app = FakeAgentApp()
    apply_load(app, _baseline_state())
    assert app._agents_roster_complete_query_key is not None

    app._agents_with_children = []
    apply_load(app, _bounded_patch_state())

    assert app._agents_roster_complete_query_key is None
    assert agents_viewport_for_load(app) is None


def test_artifact_delta_leaves_latch_unchanged() -> None:
    """Exact deltas patch rows; they never set or clear the roster latch."""
    app = FakeAgentApp()
    apply_load(app, _baseline_state())
    latch = app._agents_roster_complete_query_key

    apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
            complete_visible_inbox=True,
        ),
    )

    assert app._agents_roster_complete_query_key == latch

    fresh = FakeAgentApp()
    apply_load(
        fresh,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
            complete_visible_inbox=True,
        ),
    )
    assert getattr(fresh, "_agents_roster_complete_query_key", None) is None


def test_roster_partial_apply_arms_completion_with_short_threshold() -> None:
    """A partial roster arms Tier 2 with the 2 s roster-completion threshold."""
    app = FakeAgentApp()
    apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_index_missing_bounded_fallback",
        ),
    )

    assert app._agents_roster_complete_query_key is None
    assert app._agents_history_reconcile_pending is True
    assert (
        app._agents_history_reconcile_quiet_s
        == ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S
    )


def test_lock_busy_trigger_retries_baseline_while_missing_runs_tier2() -> None:
    """The countdown trigger picks the completing load by cause."""
    scheduled: list[dict[str, Any]] = []

    def record_schedule(**kwargs: Any) -> None:
        scheduled.append(kwargs)

    busy = FakeAgentApp()
    busy._schedule_agents_async_refresh = record_schedule  # type: ignore[method-assign]
    busy._agents_refresh_scheduled = False
    busy._agents_artifact_delta_scheduled = None
    apply_load(
        busy,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_reason="artifact_index_lock_busy_bounded_fallback",
        ),
    )
    assert busy._agents_history_reconcile_pending is True
    busy._last_input_mono = 100.0
    busy._agents_history_reconcile_armed_mono = 100.0
    assert (
        busy._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=100.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S + 0.5
        )
        is True
    )
    assert scheduled and scheduled[-1].get("full_history", False) is False

    tier2_scheduled: list[dict[str, Any]] = []

    def record_tier2(**kwargs: Any) -> None:
        tier2_scheduled.append(kwargs)

    missing = FakeAgentApp()
    missing._schedule_agents_async_refresh = record_tier2  # type: ignore[method-assign]
    missing._agents_refresh_scheduled = False
    missing._agents_artifact_delta_scheduled = None
    apply_load(
        missing,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_index_missing_bounded_fallback",
        ),
    )
    missing._last_input_mono = 100.0
    missing._agents_history_reconcile_armed_mono = 100.0
    assert (
        missing._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=100.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S + 0.5
        )
        is True
    )
    assert tier2_scheduled and tier2_scheduled[-1].get("full_history") is True


def test_repair_only_arming_on_complete_roster_keeps_default_threshold() -> None:
    """Repair arming over a same-query baseline keeps the 30 s default."""
    from sase.ace.tui.actions.agents._loading_refresh_polling import (
        TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
    )

    app = FakeAgentApp()
    apply_load(app, _baseline_state())
    assert app._agents_roster_complete_query_key is not None

    app._agents_with_children = [_make_agent(cl_name="cached")]
    apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_index_missing_bounded_fallback",
        ),
    )

    assert app._agents_roster_complete_query_key is not None
    assert app._agents_history_reconcile_pending is True
    assert (
        app._agents_history_reconcile_quiet_s == TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S
    )


def test_revalidate_does_not_arm_while_roster_partial() -> None:
    """The 300 s maintenance revalidate waits for a complete roster."""
    app = FakeAgentApp()
    app._agents_index_revalidate_pending = False
    app._agents_index_revalidate_armed_mono = 0.0
    app._agents_index_revalidate_last_mono = 0.0
    apply_load(
        app,
        _baseline_state(
            truncated=True,
            complete_visible_inbox=False,
        ),
    )

    assert app._agents_roster_complete_query_key is None
    assert app._agents_index_revalidate_pending is False
    assert app._agents_history_reconcile_pending is True

    apply_load(app, _baseline_state())

    assert app._agents_roster_complete_query_key is not None
    assert app._agents_index_revalidate_pending is True

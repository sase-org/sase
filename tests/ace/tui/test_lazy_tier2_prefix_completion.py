"""Tests for startup prefix completion refresh behavior."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._loading_disk import _agents_viewport_for_load
from sase.ace.tui.actions.agents._loading_refresh import (
    STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S,
    STARTUP_PREFIX_COMPLETION_SOURCE,
)
from sase.ace.tui.models.agent_loader import AgentLoadState
from tests._agents_tab_query_helpers import FakeAgentApp
from tests.ace.tui._lazy_tier2_reconcile_helpers import (
    FakeRefreshApp,
    apply_load,
    bounded_partial_load_state,
)


def test_prefix_completion_arms_on_bounded_partial_apply() -> None:
    app = FakeAgentApp()
    app._agents_prefix_completion_pending = False
    app._agents_prefix_completion_done = False
    app._agents_prefix_completion_armed_mono = 0.0
    app._agents_refresh_scheduled = False

    apply_load(app, bounded_partial_load_state())

    assert app._agents_prefix_completion_pending is True
    assert app._agents_prefix_completion_done is False
    assert app._agents_prefix_completion_armed_mono > 0.0
    assert app._agents_refresh_scheduled is False


def test_prefix_completion_does_not_arm_when_has_more_is_false() -> None:
    app = FakeAgentApp()
    app._agents_prefix_completion_pending = False
    app._agents_prefix_completion_done = False

    apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=126,
            returned_count=40,
            has_more=False,
        ),
    )

    assert app._agents_prefix_completion_pending is False
    assert app._agents_prefix_completion_done is False


def test_prefix_completion_does_not_arm_when_already_done() -> None:
    app = FakeAgentApp()
    app._agents_prefix_completion_pending = False
    app._agents_prefix_completion_done = True
    app._agents_prefix_completion_armed_mono = 0.0

    apply_load(app, bounded_partial_load_state())

    assert app._agents_prefix_completion_pending is False
    assert app._agents_prefix_completion_done is True
    assert app._agents_prefix_completion_armed_mono == 0.0


def test_unbounded_apply_marks_prefix_completion_done() -> None:
    app = FakeAgentApp()
    app._agents_prefix_completion_pending = True
    app._agents_prefix_completion_done = False

    apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=False,
            has_more=False,
        ),
    )

    assert app._agents_prefix_completion_done is True
    assert app._agents_prefix_completion_pending is False


def test_prefix_completion_trigger_skips_when_recent_input() -> None:
    app = FakeRefreshApp()
    app._agents_prefix_completion_pending = True
    app._agents_prefix_completion_armed_mono = 100.0
    app._last_input_mono = 100.0
    fired = app._maybe_trigger_startup_prefix_completion(
        now_mono=100.0 + STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S - 1.0
    )
    assert fired is False
    assert app._scheduled == []
    assert app._agents_prefix_completion_pending is True


def test_prefix_completion_trigger_fires_after_threshold() -> None:
    app = FakeRefreshApp()
    app._agents_prefix_completion_pending = True
    app._agents_prefix_completion_armed_mono = 100.0

    fired = app._maybe_trigger_startup_prefix_completion(
        now_mono=100.0 + STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S + 0.5
    )

    assert fired is True
    assert app._agents_prefix_completion_pending is False
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_source == STARTUP_PREFIX_COMPLETION_SOURCE
    assert app._agents_refresh_scheduled_full_history is False
    assert app._agents_refresh_scheduled_revalidate_index is False
    assert app._agents_refresh_scheduled_prefix_completion is True


def test_prefix_completion_trigger_skips_when_load_already_in_flight() -> None:
    app = FakeRefreshApp()
    app._agents_prefix_completion_pending = True
    app._agents_prefix_completion_armed_mono = 100.0
    app._agents_loading = True
    fired = app._maybe_trigger_startup_prefix_completion(
        now_mono=100.0 + STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S + 5.0
    )
    assert fired is False
    assert app._scheduled == []
    assert app._agents_prefix_completion_pending is True


def test_prefix_completion_trigger_skips_when_refresh_scheduled() -> None:
    app = FakeRefreshApp()
    app._agents_prefix_completion_pending = True
    app._agents_prefix_completion_armed_mono = 100.0
    app._agents_refresh_scheduled = True
    fired = app._maybe_trigger_startup_prefix_completion(
        now_mono=100.0 + STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S + 5.0
    )
    assert fired is False
    assert app._agents_prefix_completion_pending is True


def test_prefix_completion_trigger_skips_when_artifact_delta_scheduled() -> None:
    app = FakeRefreshApp()
    app._agents_prefix_completion_pending = True
    app._agents_prefix_completion_armed_mono = 100.0
    app._agents_artifact_delta_scheduled = object()
    fired = app._maybe_trigger_startup_prefix_completion(
        now_mono=100.0 + STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S + 5.0
    )
    assert fired is False
    assert app._agents_prefix_completion_pending is True


@pytest.mark.asyncio
async def test_prefix_completion_routes_unwindowed_cached_refresh() -> None:
    app = FakeRefreshApp()
    captured: list[dict[str, object]] = []

    async def _fake_load_agents_async(
        *,
        full_history: bool = False,
        source: str = "unknown",
        index_freshness: str = "cached",
    ) -> None:
        captured.append(
            {
                "full_history": full_history,
                "source": source,
                "index_freshness": index_freshness,
                "viewport": _agents_viewport_for_load(app),
            }
        )

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]
    app._agents_prefix_completion_pending = True
    app._agents_prefix_completion_armed_mono = 0.001
    fired = app._maybe_trigger_startup_prefix_completion(
        now_mono=STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S + 1.0
    )
    assert fired is True
    await app._run_agents_async_refresh()
    assert captured == [
        {
            "full_history": False,
            "source": STARTUP_PREFIX_COMPLETION_SOURCE,
            "index_freshness": "cached",
            "viewport": None,
        }
    ]

"""Tests for Tier 1 index revalidation refresh behavior."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._loading_refresh import (
    TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S,
    TIER1_INDEX_REVALIDATE_SOURCE,
)
from sase.ace.tui.models.agent_loader import AgentLoadState
from tests.ace.tui._lazy_tier2_reconcile_helpers import FakeRefreshApp


def test_tier1_index_revalidate_arms_after_cached_index_load() -> None:
    app = FakeRefreshApp()
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    app._arm_tier1_index_revalidate_reconcile(
        load_state,
        source="apply",
        now_mono=100.0,
    )

    assert app._agents_index_revalidate_pending is True
    assert app._agents_index_revalidate_armed_mono == 100.0
    assert app._agents_refresh_scheduled is False


def test_tier1_index_revalidate_trigger_fires_after_threshold() -> None:
    app = FakeRefreshApp()
    app._agents_index_revalidate_pending = True
    app._agents_index_revalidate_armed_mono = 100.0

    fired = app._maybe_trigger_tier1_index_revalidate_reconcile(
        now_mono=100.0 + TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S + 0.5
    )

    assert fired is True
    assert app._agents_index_revalidate_pending is False
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_source == TIER1_INDEX_REVALIDATE_SOURCE
    assert app._agents_refresh_scheduled_full_history is False
    assert app._agents_refresh_scheduled_revalidate_index is True


@pytest.mark.asyncio
async def test_tier1_index_revalidate_routes_through_async_refresh() -> None:
    app = FakeRefreshApp()
    captured: list[tuple[bool, str]] = []

    async def _fake_load_agents_async(
        *,
        full_history: bool = False,
        source: str = "unknown",
        index_freshness: str = "cached",
    ) -> None:
        del source
        captured.append((full_history, index_freshness))

    app._load_agents_async = _fake_load_agents_async  # type: ignore[method-assign]

    app._agents_index_revalidate_pending = True
    app._agents_index_revalidate_armed_mono = 0.001
    fired = app._maybe_trigger_tier1_index_revalidate_reconcile(
        now_mono=TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S + 1.0
    )
    assert fired is True
    await app._run_agents_async_refresh()
    assert captured == [(False, "revalidate")]

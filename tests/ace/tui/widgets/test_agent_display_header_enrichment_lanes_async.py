"""Lane-batch streaming tests for async detail-header enrichment."""

from __future__ import annotations

from typing import cast

import pytest

from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    ALL_DETAIL_CONTEXT_LANES,
    LANE_RESOLUTION_BATCHES,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
    cache_detail_header_summary,
    get_cached_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailContextLane
from sase.ace.tui.widgets.prompt_panel._messages import AgentDetailHeaderEnriched
from tests.ace.tui.widgets._agent_display_header_enrichment_helpers import (
    StreamingHeaderEnrichmentPanel,
    patch_summary_builder,
    set_context,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def test_worker_resolves_lane_batches_cheapest_first_and_publishes_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bead sase-l6.4: batches run in ``LANE_RESOLUTION_BATCHES`` order and
    every batch but the last is handed to the main thread as it lands.
    """
    agent = make_agent(status="RUNNING")
    panel = StreamingHeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    seen_batches: list[frozenset[DetailContextLane]] = []

    def build(
        agent_arg: object, *, lanes: frozenset[DetailContextLane]
    ) -> _DetailHeaderSummary:
        del agent_arg
        seen_batches.append(lanes)
        return _DetailHeaderSummary(ready_lanes=lanes)

    patch_summary_builder(monkeypatch, build)

    panel.update_display(agent)
    assert panel.worker_fn is not None
    result = cast(_DetailHeaderSummary, panel.worker_fn())

    assert seen_batches == list(LANE_RESOLUTION_BATCHES)
    assert result.ready_lanes == ALL_DETAIL_CONTEXT_LANES

    # Every batch but the last publishes to the main thread as it lands;
    # the final batch is left for the Worker.StateChanged SUCCESS path so
    # completion has exactly one place that caches and posts.
    assert len(panel.app.calls) == len(LANE_RESOLUTION_BATCHES) - 1
    assert len(panel.messages) == len(LANE_RESOLUTION_BATCHES) - 1
    assert all(isinstance(m, AgentDetailHeaderEnriched) for m in panel.messages)

    # The cache already reflects the first two batches by the time the
    # worker returns, ahead of the SUCCESS handler's own cache write.
    cached = get_cached_detail_header_summary(panel, agent)
    assert cached is not None
    assert cached.ready_lanes == LANE_RESOLUTION_BATCHES[0] | LANE_RESOLUTION_BATCHES[1]


def test_only_stale_lanes_are_resolved_when_summary_is_partially_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache with one stale lane should not re-resolve the fresh ones."""
    agent = make_agent(status="RUNNING")
    panel = StreamingHeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    cache_detail_header_summary(
        panel,
        agent,
        _DetailHeaderSummary(ready_lanes=ALL_DETAIL_CONTEXT_LANES - {"memory"}),
    )
    seen_batches: list[frozenset[DetailContextLane]] = []

    def build(
        agent_arg: object, *, lanes: frozenset[DetailContextLane]
    ) -> _DetailHeaderSummary:
        del agent_arg
        seen_batches.append(lanes)
        return _DetailHeaderSummary(ready_lanes=lanes)

    patch_summary_builder(monkeypatch, build)

    panel.update_display(agent)

    assert panel.worker_fn is not None
    result = cast(_DetailHeaderSummary, panel.worker_fn())

    assert seen_batches == [frozenset({"memory"})]
    assert result.ready_lanes == frozenset({"memory"})
    # No intermediate publish: the one stale lane is also the last batch.
    assert panel.app.calls == []


def test_superseded_selection_intermediate_batch_caches_without_repaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch landing after the selection moved on must not repaint it."""
    agent = make_agent(status="RUNNING")
    panel = StreamingHeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=False)

    def build(
        agent_arg: object, *, lanes: frozenset[DetailContextLane]
    ) -> _DetailHeaderSummary:
        del agent_arg
        return _DetailHeaderSummary(ready_lanes=lanes)

    patch_summary_builder(monkeypatch, build)

    panel.update_display(agent)
    assert panel.worker_fn is not None
    result = cast(_DetailHeaderSummary, panel.worker_fn())

    assert result.ready_lanes == ALL_DETAIL_CONTEXT_LANES
    # The now-stale intermediate batches still ran and still cached (same
    # unconditional-cache-then-check-is_current shape as the SUCCESS
    # handler), but none of them posted a repaint message.
    assert panel.messages == []
    cached = get_cached_detail_header_summary(panel, agent)
    assert cached is not None
    assert cached.ready_lanes == LANE_RESOLUTION_BATCHES[0] | LANE_RESOLUTION_BATCHES[1]

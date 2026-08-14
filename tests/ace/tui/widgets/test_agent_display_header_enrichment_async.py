"""Async detail-header enrichment tests for the agent prompt panel."""

from __future__ import annotations

from typing import Any, cast

import pytest
from textual.worker import Worker, WorkerState

from sase.ace.tui.widgets.prompt_panel import _agent_display_parts
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
    get_cached_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._messages import AgentDetailHeaderEnriched
from tests.ace.tui.widgets._agent_display_header_enrichment_helpers import (
    HeaderEnrichmentPanel,
    MessageHeaderEnrichmentPanel,
    make_phase_summary,
    make_summary,
    patch_summary_builder,
    set_context,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent, plain_of


def test_update_display_schedules_header_enrichment_without_sync_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = HeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    calls: list[object] = []
    summary = make_summary()

    def build(agent_arg: object, *, lanes: object = None) -> _DetailHeaderSummary:
        del lanes
        calls.append(agent_arg)
        return summary

    patch_summary_builder(monkeypatch, build)

    panel.update_display(agent)

    assert calls == []
    assert panel.worker_fn is not None
    assert "Deltas:" not in plain_of(panel.captured[-1])
    assert "Files:" not in plain_of(panel.captured[-1])

    # The streaming worker (bead sase-l6.4) resolves the default full lane
    # set cheapest-first across three batches, calling the patched builder
    # once per batch; every batch here returns the same fixed summary, so
    # the merge across batches collapses back to that same object.
    assert panel.worker_fn() is summary
    assert calls == [agent, agent, agent]


def test_successful_header_enrichment_repaints_from_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = HeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    summary = make_summary()
    patch_summary_builder(monkeypatch, lambda _agent, *, lanes=None: summary)

    panel.update_display(agent)
    assert panel.worker_fn is not None
    assert "Deltas:" not in plain_of(panel.captured[-1])

    panel.worker.result = panel.worker_fn()
    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )

    plain = plain_of(panel.captured[-1])
    assert "  Deltas:\n    ~ src/foo.py  ~1\n" in plain
    assert "  Files:\n    • artifact.txt\n" in plain


def test_successful_phase_enrichment_replaces_cold_header_with_bead_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(
        status="RUNNING",
        agent_name="sase-7.2",
        epic_bead_id="sase-7",
        phase_bead_id="sase-7.2",
    )
    panel = HeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    summary = _DetailHeaderSummary(
        phase_bead=make_phase_summary(
            "sase-7.2",
            notes="[2026-08-01T14:10:00Z · reviewer] deferred note",
        )
    )
    patch_summary_builder(monkeypatch, lambda _agent, *, lanes=None: summary)

    panel.update_display(agent)
    assert "Bead:" not in plain_of(panel.captured[-1])
    assert "▸ BEAD" not in plain_of(panel.captured[-1])
    assert "Notes:" not in plain_of(panel.captured[-1])

    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )

    plain = plain_of(panel.captured[-1])
    assert "Bead:" not in plain
    assert "▸ BEAD · ↳ phase sase-7.2\n" in plain
    assert "ID:" not in plain
    assert plain.count("▸ BEAD · ↳ phase sase-7.2") == 1
    assert " Description: Deferred selected phase description.\n" in plain
    assert "        Notes: [2026-08-01T14:10:00Z · reviewer] deferred note\n" in plain


def test_successful_header_enrichment_posts_completion_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = MessageHeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    summary = make_summary()
    patch_summary_builder(monkeypatch, lambda _agent, *, lanes=None: summary)

    panel.update_display(agent)
    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    captured_count = len(panel.captured)

    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )

    assert len(panel.captured) == captured_count
    assert get_cached_detail_header_summary(panel, agent) is summary
    assert len(panel.messages) == 1
    message = panel.messages[0]
    assert isinstance(message, AgentDetailHeaderEnriched)
    assert message.agent_identity == agent.identity


def test_stale_header_enrichment_result_is_cached_without_repaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = HeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=False)
    summary = make_summary()
    patch_summary_builder(monkeypatch, lambda _agent, *, lanes=None: summary)

    panel.update_display(agent)
    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    captured_count = len(panel.captured)

    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )

    assert len(panel.captured) == captured_count
    assert get_cached_detail_header_summary(panel, agent) is summary


def test_completed_phase_enrichment_cannot_overwrite_new_phase_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = make_agent(
        cl_name="phase-one",
        raw_suffix="1",
        agent_name="sase-7.1",
        epic_bead_id="sase-7",
        phase_bead_id="sase-7.1",
    )
    second = make_agent(
        cl_name="phase-two",
        raw_suffix="2",
        agent_name="sase-7.2",
        epic_bead_id="sase-7",
        phase_bead_id="sase-7.2",
    )
    panel = HeaderEnrichmentPanel()
    selected_identity = first.identity
    patch_summary_builder(
        monkeypatch,
        lambda agent, *, lanes=None: _DetailHeaderSummary(
            phase_bead=make_phase_summary(agent.phase_bead_id or "missing")
        ),
    )

    panel.start_agent_detail_header_enrichment(
        first,
        generation=7,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda identity, *_args: identity == selected_identity,
    )
    assert panel.worker_fn is not None
    first_worker = panel.worker
    first_worker.result = panel.worker_fn()

    selected_identity = second.identity
    panel.start_agent_detail_header_enrichment(
        second,
        generation=8,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda identity, *_args: identity == selected_identity,
    )
    assert first_worker.cancelled

    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], first_worker),
        WorkerState.SUCCESS,
    )

    assert get_cached_detail_header_summary(panel, first) is None
    assert get_cached_detail_header_summary(panel, second) is None


def test_fresh_header_summary_cache_skips_second_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 10.0
    monkeypatch.setattr(
        _agent_display_parts.time,
        "monotonic",
        lambda: now,
    )
    agent = make_agent(status="RUNNING")
    panel = HeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    summary = make_summary()
    build_calls: list[object] = []

    def build(agent_arg: object, *, lanes: object = None) -> _DetailHeaderSummary:
        del lanes
        build_calls.append(agent_arg)
        return summary

    patch_summary_builder(monkeypatch, build)

    panel.update_display(agent)
    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )
    assert build_calls == [agent, agent, agent]

    panel.worker_fn = None
    panel.update_display(agent)

    assert panel.worker_fn is None
    assert build_calls == [agent, agent, agent]
    assert "  Deltas:\n    ~ src/foo.py  ~1\n" in plain_of(panel.captured[-1])

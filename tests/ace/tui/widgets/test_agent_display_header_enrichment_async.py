"""Async detail-header enrichment tests for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from textual.worker import Worker, WorkerState

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.widgets.prompt_panel import _agent_display_parts
from sase.ace.tui.widgets.prompt_panel._agent_artifacts import AgentArtifactPath
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
    get_cached_detail_header_summary,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent, plain_of


class _FakeWorker:
    def __init__(self, result: object | None = None) -> None:
        self.is_running = True
        self.result = result
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class _HeaderEnrichmentPanel(AgentDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []
        self.worker = _FakeWorker()
        self.worker_fn: Callable[[], object] | None = None

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)

    def run_worker(self, fn: Callable[[], object], *, thread: bool) -> _FakeWorker:
        assert thread
        self.worker_fn = fn
        self.worker = _FakeWorker()
        return self.worker


def _set_context(
    panel: AgentDisplayMixin,
    agent_identity: tuple[Any, ...],
    *,
    current: bool,
) -> None:
    def is_current(
        identity: tuple[Any, ...],
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
    ) -> bool:
        return (
            current
            and identity == agent_identity
            and generation == 7
            and attempt_view_mode == "merged"
            and attempt_pinned_number is None
        )

    panel.set_agent_detail_render_context(
        generation=7,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=is_current,
    )


def _summary() -> _DetailHeaderSummary:
    return _DetailHeaderSummary(
        delta_entries=[
            DeltaEntry(
                path="src/foo.py",
                change_type="M",
                line_stats=DeltaLineStats(modified=1),
            )
        ],
        artifact_paths=[
            AgentArtifactPath(
                display_path="artifact.txt",
                actual_path="/tmp/artifact.txt",
            )
        ],
    )


def test_update_display_schedules_header_enrichment_without_sync_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = _HeaderEnrichmentPanel()
    _set_context(panel, agent.identity, current=True)
    calls: list[object] = []
    summary = _summary()

    def build(agent_arg: object) -> _DetailHeaderSummary:
        calls.append(agent_arg)
        return summary

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_detail_header_summary",
        build,
    )

    panel.update_display(agent)

    assert calls == []
    assert panel.worker_fn is not None
    assert "Deltas:" not in plain_of(panel.captured[-1])
    assert "Artifacts:" not in plain_of(panel.captured[-1])

    assert panel.worker_fn() is summary
    assert calls == [agent]


def test_successful_header_enrichment_repaints_from_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = _HeaderEnrichmentPanel()
    _set_context(panel, agent.identity, current=True)
    summary = _summary()
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_detail_header_summary",
        lambda _agent: summary,
    )

    panel.update_display(agent)
    assert panel.worker_fn is not None
    assert "Deltas:" not in plain_of(panel.captured[-1])

    panel.worker.result = panel.worker_fn()
    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )

    plain = plain_of(panel.captured[-1])
    assert "Deltas:\n  ~ src/foo.py  ~1\n" in plain
    assert "Artifacts:\n  \u2022 artifact.txt\n" in plain


def test_stale_header_enrichment_result_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = _HeaderEnrichmentPanel()
    _set_context(panel, agent.identity, current=False)
    summary = _summary()
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_detail_header_summary",
        lambda _agent: summary,
    )

    panel.update_display(agent)
    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    captured_count = len(panel.captured)

    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )

    assert len(panel.captured) == captured_count
    assert get_cached_detail_header_summary(panel, agent) is None


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
    panel = _HeaderEnrichmentPanel()
    selected_identity = first.identity
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_detail_header_summary",
        lambda agent: _DetailHeaderSummary(bead_display=agent.phase_bead_id),
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
    panel = _HeaderEnrichmentPanel()
    _set_context(panel, agent.identity, current=True)
    summary = _summary()
    build_calls: list[object] = []

    def build(agent_arg: object) -> _DetailHeaderSummary:
        build_calls.append(agent_arg)
        return summary

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_detail_header_summary",
        build,
    )

    panel.update_display(agent)
    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )
    assert build_calls == [agent]

    panel.worker_fn = None
    panel.update_display(agent)

    assert panel.worker_fn is None
    assert build_calls == [agent]
    assert "Deltas:\n  ~ src/foo.py  ~1\n" in plain_of(panel.captured[-1])

"""Async detail-header enrichment tests for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from textual.worker import Worker, WorkerState

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel import _agent_display_parts
from sase.ace.tui.widgets.prompt_panel._agent_artifacts import AgentArtifactPath
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_hints import (
    AgentHintsDisplayMixin,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
    cache_detail_header_summary,
    get_cached_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._messages import AgentDetailHeaderEnriched
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from tests.ace.tui.widgets._agent_display_helpers import make_agent, plain_of


class _FakeWorker:
    def __init__(self, result: object | None = None) -> None:
        self.is_running = True
        self.result = result
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class _HeaderEnrichmentPanel(AgentDisplayMixin, AgentHintsDisplayMixin):
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


class _MessageHeaderEnrichmentPanel(_HeaderEnrichmentPanel):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[object] = []

    def post_message(self, message: object) -> None:
        self.messages.append(message)


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
    assert "  Deltas:\n    ~ src/foo.py  ~1\n" in plain
    assert "  Artifacts:\n    \u2022 artifact.txt\n" in plain


def test_successful_header_enrichment_posts_completion_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = _MessageHeaderEnrichmentPanel()
    _set_context(panel, agent.identity, current=True)
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
    assert get_cached_detail_header_summary(panel, agent) is summary
    assert len(panel.messages) == 1
    message = panel.messages[0]
    assert isinstance(message, AgentDetailHeaderEnriched)
    assert message.agent_identity == agent.identity


def test_stale_header_enrichment_result_is_cached_without_repaint(
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
    assert get_cached_detail_header_summary(panel, agent) is summary


def test_hint_render_uses_cached_memory_read_summary() -> None:
    agent = make_agent(status="RUNNING")
    panel = _HeaderEnrichmentPanel()
    memory_read = MemoryReadDisplayEvent(
        event=MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="read-1",
            timestamp="2026-07-16T14:22:08+00:00",
            project="test",
            cwd="/tmp/test",
            canonical_path="tui_perf.md",
            resolved_path="/tmp/test/memory/tui_perf.md",
            agent_name="alpha",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/test/artifacts",
            reason="needed TUI performance rules",
            byte_count=64,
            frontmatter_stripped=True,
        )
    )
    cache_detail_header_summary(
        panel,
        agent,
        _DetailHeaderSummary(memory_reads=(memory_read,)),
    )

    result = panel.update_display_with_hints(agent)

    plain = plain_of(panel.captured[-1])
    assert "SASE CONTEXT" in plain
    assert "◇ [1] tui_perf.md  ↩ frontmatter" in plain
    assert result.file_hints == {1: "/tmp/test/memory/tui_perf.md"}
    assert not result.header_enrichment_pending


def test_cold_hint_render_schedules_enrichment_without_sync_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = _HeaderEnrichmentPanel()
    _set_context(panel, agent.identity, current=True)
    calls: list[Agent] = []

    def build(agent_arg: Agent) -> _DetailHeaderSummary:
        calls.append(agent_arg)
        return _summary()

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_detail_header_summary",
        build,
    )

    result = panel.update_display_with_hints(agent)

    assert calls == []
    assert panel.worker_fn is not None
    assert result.header_enrichment_pending
    assert "Deltas:" not in plain_of(panel.captured[-1])


def test_hint_request_replaces_same_agent_in_flight_render_context(
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
    first_worker = panel.worker
    assert panel.worker_fn is not None

    panel.set_agent_detail_render_context(
        generation=8,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda _identity, generation, *_args: generation == 8,
    )
    panel.update_display_with_hints(agent)

    assert panel.worker is first_worker
    assert not first_worker.cancelled
    first_worker.result = panel.worker_fn()
    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], first_worker),
        WorkerState.SUCCESS,
    )
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
    assert "  Deltas:\n    ~ src/foo.py  ~1\n" in plain_of(panel.captured[-1])

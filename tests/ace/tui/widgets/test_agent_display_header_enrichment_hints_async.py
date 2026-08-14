"""Header-enrichment tests for the hint-rendering path of the prompt panel."""

from __future__ import annotations

from typing import Any, cast

import pytest
from textual.worker import Worker, WorkerState

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
    cache_detail_header_summary,
    get_cached_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._messages import AgentDetailHeaderEnriched
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from tests.ace.tui.widgets._agent_display_header_enrichment_helpers import (
    HeaderEnrichmentPanel,
    MessageHeaderEnrichmentPanel,
    make_family_agent,
    make_summary,
    patch_summary_builder,
    set_context,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent, plain_of


def test_hint_render_uses_cached_memory_read_summary() -> None:
    agent = make_agent(status="RUNNING")
    panel = HeaderEnrichmentPanel()
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
    panel = HeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    calls: list[Agent] = []

    def build(agent_arg: Agent, *, lanes: object = None) -> _DetailHeaderSummary:
        del lanes
        calls.append(agent_arg)
        return make_summary()

    patch_summary_builder(monkeypatch, build)

    result = panel.update_display_with_hints(agent)

    assert calls == []
    assert panel.worker_fn is not None
    assert result.header_enrichment_pending
    assert "Deltas:" not in plain_of(panel.captured[-1])


def test_cold_family_hint_render_stays_active_and_gains_enriched_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_family_agent()
    panel = MessageHeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    calls: list[Agent] = []
    summary = _DetailHeaderSummary(
        artifact_file_paths=[
            ArtifactFilePath(
                display_path="family-report.txt",
                actual_path="/tmp/family-report.txt",
            )
        ]
    )

    def build(agent_arg: Agent, *, lanes: object = None) -> _DetailHeaderSummary:
        del lanes
        calls.append(agent_arg)
        return summary

    patch_summary_builder(monkeypatch, build)

    cold = panel.update_display_with_hints(agent)

    assert calls == []
    assert cold.header_enrichment_pending
    assert panel._agent_hint_mode_rendered
    assert panel.worker_fn is not None
    assert "FAMILY MEMBERS" in plain_of(panel.captured[-1])

    panel.worker.result = panel.worker_fn()
    panel._apply_agent_detail_header_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )
    # Three cheapest-first batches (bead sase-l6.4) for the default full
    # lane set, each hitting the patched builder once.
    assert calls == [agent, agent, agent]
    assert isinstance(panel.messages[-1], AgentDetailHeaderEnriched)

    enriched = panel.update_display_with_hints(agent)

    assert enriched.file_hints == {1: "/tmp/family-report.txt"}
    assert not enriched.header_enrichment_pending
    assert "[1] family-report.txt" in plain_of(panel.captured[-1])


def test_hint_request_replaces_same_agent_in_flight_render_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="RUNNING")
    panel = HeaderEnrichmentPanel()
    set_context(panel, agent.identity, current=True)
    summary = make_summary()
    patch_summary_builder(monkeypatch, lambda _agent, *, lanes=None: summary)

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

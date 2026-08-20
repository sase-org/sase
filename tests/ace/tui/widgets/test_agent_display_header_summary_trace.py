"""Per-lane ``tui_trace`` span coverage for ``build_detail_header_summary``.

Phase `trace` of sase-l6 (bead sase-l6.1): the enrichment worker resolves
twelve separate things before returning a summary, and none of them was
individually observable in a trace capture. These tests pin the parent span
plus one child span per resolver, and the disabled-by-default guarantee.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.ace.tui.widgets.prompt_panel import _agent_display_header_summary
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    _TRACE_SPAN_PREFIX,
    build_detail_header_summary,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_CHILD_SPAN_SUFFIXES = (
    "xprompts_used",
    "bead_display",
    "plan_enrichment",
    "slow_tool_sources",
    "agent_page_url",
    "linked_delta_groups",
    "artifact_file_paths",
    "artifact_reads",
    "memory_reads",
    "glossary_reads",
    "skill_uses",
    "opened_workspaces",
    "delta_entries",
    "wait_bead_statuses",
)


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _reset_trace_state() -> Iterator[None]:
    previous_seen = _agent_display_header_summary._detail_header_trace_seen.copy()
    _agent_display_header_summary._detail_header_trace_seen.clear()
    try:
        yield
    finally:
        seen = _agent_display_header_summary._detail_header_trace_seen
        seen.clear()
        seen.update(previous_seen)


def _stub_all_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every resolver with a fast, deterministic stand-in.

    ``build_detail_header_summary`` reads real ``~/.sase`` stores (the
    artifact index, memory-read log, skill-use log) with no per-call cache
    ahead of phase `stores`; a unit test must not pay that cost or depend on
    the developer's local state, so every resolver is stubbed here even
    though the test only cares about the trace spans wrapping them.
    """
    monkeypatch.setattr(
        _agent_display_header_summary,
        "load_xprompts_used",
        lambda agent: [{"name": "x"}],
    )
    monkeypatch.setattr(
        _agent_display_header_summary,
        "cached_bead_display",
        lambda agent: "sase-1",
    )
    from sase.ace.tui.models.agent_associated_plan import _AgentPlanEnrichment

    monkeypatch.setattr(
        _agent_display_header_summary,
        "resolve_agent_plan_enrichment",
        lambda agent: _AgentPlanEnrichment("ordinary", None, None, ()),
    )
    monkeypatch.setattr(
        _agent_display_header_summary,
        "supports_slow_tool_sources",
        lambda agent: True,
    )
    monkeypatch.setattr(
        _agent_display_header_summary,
        "build_slow_tool_sources",
        lambda agent: (),
    )
    monkeypatch.setattr(
        _agent_display_header_summary,
        "agent_publishes_page",
        lambda agent: True,
    )
    monkeypatch.setattr(
        _agent_display_header_summary,
        "resolve_agent_page_url",
        lambda agent: "https://example.invalid/agent",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._linked_deltas.get_cached_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas.agent_commit_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas.agent_delta_entries",
        lambda agent: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda agent: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifact_reads.load_artifact_reads_for_agent_context",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.memory_reads.load_memory_reads_for_agent_context",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.glossary_reads.load_glossary_reads_for_agent_context",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.skill_uses.load_skill_uses_for_agent_context",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.opened_workspaces.load_opened_workspaces_for_agent_context",
        lambda agent: (),
    )
    monkeypatch.setattr(
        _agent_display_header_summary,
        "resolve_wait_bead_statuses",
        lambda agent: None,
    )


def test_disabled_by_default_emits_no_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "trace.jsonl"
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    _stub_all_resolvers(monkeypatch)

    agent = make_agent(agent_name="agent-1", step_type="assistant")
    build_detail_header_summary(agent)

    assert not log.exists()
    assert not _agent_display_header_summary._detail_header_trace_seen


def test_enabled_emits_parent_and_child_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    _stub_all_resolvers(monkeypatch)

    agent = make_agent(agent_name="agent-1", step_type="assistant")
    build_detail_header_summary(agent)

    rows = _records(log)
    spans = {row["span"] for row in rows}

    assert _TRACE_SPAN_PREFIX in spans
    for suffix in _CHILD_SPAN_SUFFIXES:
        assert f"{_TRACE_SPAN_PREFIX}.{suffix}" in spans, suffix

    parent = next(row for row in rows if row["span"] == _TRACE_SPAN_PREFIX)
    assert parent["agent"] == agent.cl_name
    assert parent["cache_state"] == "cold"
    for row in rows:
        assert row["duration_ms"] >= 0.0


def test_cache_state_is_cold_then_warm_per_agent_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    _stub_all_resolvers(monkeypatch)

    agent = make_agent(agent_name="agent-1", step_type="assistant")
    build_detail_header_summary(agent)
    build_detail_header_summary(agent)

    other = make_agent(agent_name="agent-2", cl_name="other_cl", step_type="assistant")
    build_detail_header_summary(other)

    parents = [row for row in _records(log) if row["span"] == _TRACE_SPAN_PREFIX]
    assert [row["cache_state"] for row in parents] == ["cold", "warm", "cold"]

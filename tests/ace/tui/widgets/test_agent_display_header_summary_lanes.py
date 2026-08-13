"""Per-lane resolution, caching, and freshness tests (bead sase-l6.3).

Phase `lanes` of ``plans/202608/sase_context_incremental.md`` splits the
monolithic ``build_detail_header_summary`` into independently resolved and
cached lanes with per-lane freshness, replacing the blanket 1 s TTL. These
tests cover the phase's own stated regression surface: a partial request set
resolves only its lanes, a merge never blanks a lane it did not touch, a lane
that resolved to nothing stays distinguishable from a lane that was never
requested, and a stationary selection settles into per-lane revalidation
instead of re-resolving everything on every repaint.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_display_header_summary
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    ALL_DETAIL_CONTEXT_LANES,
    LANE_RESOLUTION_BATCHES,
    build_detail_header_summary,
    cache_detail_header_summary,
    detail_header_summary_is_complete,
    get_cached_detail_header_summary,
    should_refresh_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_MEMORY_EVENT = MemoryReadDisplayEvent(
    event=MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id="read-1",
        timestamp="2026-08-13T10:00:00+00:00",
        project="demo",
        cwd="/tmp",
        canonical_path="tui_perf.md",
        resolved_path="/tmp/tui_perf.md",
        agent_name="agent-1",
        agent_source="test",
        artifacts_dir="/tmp/artifacts",
        reason="test",
        byte_count=10,
        frontmatter_stripped=False,
    )
)
_OTHER_SKILL_EVENT = SkillUseDisplayEvent(
    event=SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id="skill-1",
        timestamp="2026-08-13T10:00:00+00:00",
        project="demo",
        cwd="/tmp",
        skill_name="sase_beads",
        agent_name="agent-1",
        agent_source="test",
        artifacts_dir="/tmp/artifacts",
        reason="test",
        runtime="codex",
    )
)


class _Widget:
    """A bare panel stand-in; the cache lives on an arbitrary attribute."""


def _stub_non_memory_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every resolver besides ``memory_reads`` cheap and deterministic."""
    from sase.ace.tui.models.agent_associated_plan import _AgentPlanEnrichment

    monkeypatch.setattr(
        _agent_display_header_summary,
        "resolve_agent_plan_enrichment",
        lambda agent: _AgentPlanEnrichment("ordinary", None, None, ()),
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
        "sase.ace.tui.widgets.prompt_panel._artifact_files.artifact_file_paths",
        lambda agent: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._linked_deltas.get_cached_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas."
        "agent_commit_linked_delta_groups",
        lambda agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_deltas.agent_delta_entries",
        lambda agent: [],
    )


def test_partial_lane_request_resolves_only_the_requested_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_non_memory_resolvers(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.memory_reads.load_memory_reads_for_agent_context",
        lambda agent: (_MEMORY_EVENT,),
    )
    agent = make_agent(agent_name=None)

    summary = build_detail_header_summary(agent, lanes=frozenset({"memory"}))

    assert summary.ready_lanes == frozenset({"memory"})
    assert summary.memory_reads == (_MEMORY_EVENT,)
    # Every other lane was not requested, so it stays unresolved rather than
    # paying for xprompts, plan/bead lookups, artifacts, skills, etc.
    assert summary.skill_uses == ()
    assert summary.artifact_file_paths is None
    assert summary.associated_plan is None
    assert summary.phase_bead is None
    assert summary.wait_bead_statuses is None


def test_resolved_empty_lane_is_distinguishable_from_unresolved_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_non_memory_resolvers(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.memory_reads.load_memory_reads_for_agent_context",
        lambda agent: (),
    )
    agent = make_agent(agent_name=None)

    resolved = build_detail_header_summary(agent, lanes=frozenset({"memory"}))
    unresolved = build_detail_header_summary(agent, lanes=frozenset())

    # Both report an empty `memory_reads` tuple, but only one actually asked.
    assert resolved.memory_reads == unresolved.memory_reads == ()
    assert "memory" in resolved.ready_lanes
    assert "memory" not in unresolved.ready_lanes


def test_cache_merge_does_not_blank_a_lane_the_rebuild_did_not_touch() -> None:
    widget = _Widget()
    agent = make_agent()
    full = DetailHeaderSummary(
        memory_reads=(_MEMORY_EVENT,),
        skill_uses=(_OTHER_SKILL_EVENT,),
    )
    cache_detail_header_summary(widget, agent, full)

    # A later worker run only re-resolved `skills`; `memory` must survive.
    partial = DetailHeaderSummary(
        skill_uses=(),
        ready_lanes=frozenset({"skills"}),
    )
    cache_detail_header_summary(widget, agent, partial)

    merged = get_cached_detail_header_summary(widget, agent)
    assert merged is not None
    assert merged.memory_reads == (_MEMORY_EVENT,)
    assert merged.skill_uses == ()
    assert merged.ready_lanes == ALL_DETAIL_CONTEXT_LANES


def test_cache_merge_full_rebuild_replaces_every_lane() -> None:
    widget = _Widget()
    agent = make_agent()
    cache_detail_header_summary(
        widget,
        agent,
        DetailHeaderSummary(memory_reads=(_MEMORY_EVENT,)),
    )

    replacement = DetailHeaderSummary()
    cache_detail_header_summary(widget, agent, replacement)

    assert get_cached_detail_header_summary(widget, agent) is replacement


def test_stationary_selection_settles_into_per_lane_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(_agent_display_header_summary.time, "monotonic", lambda: now)
    agent = make_agent()
    widget = _Widget()
    cache_detail_header_summary(widget, agent, DetailHeaderSummary())

    # The old blanket TTL was 1 s; nothing should be stale here.
    now += 1.0
    assert should_refresh_detail_header_summary(widget, agent) == frozenset()

    # 5.5 s in: only the slow-tools lane (matched to its own 5 s tick) is due.
    now += 4.5
    assert should_refresh_detail_header_summary(widget, agent) == frozenset(
        {"slow-tools"}
    )

    # 10.5 s in: the default-cadence lanes join it, but wait-beads never does.
    now += 5.0
    stale = should_refresh_detail_header_summary(widget, agent)
    assert "slow-tools" in stale
    assert "memory" in stale
    assert "artifacts" in stale
    assert "wait-beads" not in stale


def test_lane_resolution_batches_cover_every_lane_exactly_once() -> None:
    """The streaming worker's batches (bead sase-l6.4) partition every lane.

    A lane missing from every batch would silently never resolve; a lane in
    two batches would be resolved (and published) twice. Both are bugs the
    worker's cheapest-first loop relies on this constant to avoid.
    """
    seen: set[str] = set()
    for batch in LANE_RESOLUTION_BATCHES:
        assert not (seen & batch), f"lane(s) {seen & batch} appear in two batches"
        seen |= batch
    assert seen == ALL_DETAIL_CONTEXT_LANES


def test_detail_header_summary_is_complete() -> None:
    assert not detail_header_summary_is_complete(None)
    assert not detail_header_summary_is_complete(
        DetailHeaderSummary(ready_lanes=frozenset({"memory"}))
    )
    assert detail_header_summary_is_complete(
        DetailHeaderSummary(ready_lanes=ALL_DETAIL_CONTEXT_LANES)
    )


def test_hint_session_widens_every_lane_including_slow_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(_agent_display_header_summary.time, "monotonic", lambda: now)
    agent = make_agent()

    class _App:
        current_tab = "agents"
        _hint_mode_active = True

    class _HintWidget(_Widget):
        app = _App()

    widget = _HintWidget()
    cache_detail_header_summary(widget, agent, DetailHeaderSummary())

    # Past the un-hinted slow-tools cadence, but still well inside the hint
    # session's longer cadence: nothing should renumber under the user.
    now += 6.0
    assert should_refresh_detail_header_summary(widget, agent) == frozenset()

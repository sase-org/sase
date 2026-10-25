"""Questions-lane resolver, cache-key, and freshness tests (phase `lane`).

The `questions` lane loads session question rounds on the lane worker,
keys invalidation on ``(gate_id, gate_state)`` pairs, and never resolves
during the zero-I/O immediate paint. This phase changes no rendering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.widgets.prompt_panel._agent_context import (
    CONTEXT_LANE_ORDER,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    DETAIL_HEADER_TRACE_SPAN_PREFIX,
    build_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary_cache import (
    cache_detail_header_summary,
    get_cached_detail_header_summary,
    immediate_detail_header_summary,
    merge_detail_header_summary_lanes,
    should_refresh_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    ALL_DETAIL_CONTEXT_LANES,
    DetailHeaderSummary,
)
from sase.question_gate_turn.projection import (
    NumberedQuestionRound,
    QuestionEntryView,
    QuestionRoundView,
)
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent as make_member,
    make_gate_member,
)

__all__ = [
    "test_fresh_widget_stales_every_lane_including_questions",
    "test_gate_state_change_stales_only_questions_lane",
    "test_immediate_summary_never_marks_questions_ready",
    "test_merge_keeps_question_rounds",
    "test_partial_lane_request_resolves_only_questions",
    "test_questions_lane_emits_trace_span",
    "test_questions_lane_is_not_a_context_lane",
    "test_resolver_numbers_session_wide_and_filters_scope",
]


class _Widget:
    """A bare panel stand-in; the cache lives on an arbitrary attribute."""


def _question_session() -> tuple[object, object, object, object]:
    root = make_member("alpha--0", role="root")
    plan = make_member("alpha--plan", role="plan", parent_timestamp=root.raw_suffix)
    first = make_member("alpha--1", role="1", parent_timestamp=root.raw_suffix)
    root.followup_agents = [plan, first]

    gate = make_gate_member(
        "alpha--gate", root=plan, gate_id="g0", gate_state="answered"
    )
    gate.gate_kind = "question"
    gate.gate_creator_agent = "alpha--plan"
    plan.runtime_children = [gate]

    gate0 = make_gate_member(
        "alpha--gate-0", root=first, gate_id="g1", gate_state="pending"
    )
    gate0.gate_kind = "question"
    gate0.gate_creator_agent = "alpha--1"
    gate0.role_suffix = "--gate-0"
    first.runtime_children = [gate0]

    for member in (plan, first, gate, gate0):
        member.agent_session_container = root
    return root, plan, first, gate0


def _fake_views(monkeypatch: pytest.MonkeyPatch) -> None:
    views = {
        "g0": QuestionRoundView(
            gate_id="g0",
            status="answered",
            data_state="complete",
            entries=(
                QuestionEntryView(question="First?"),
                QuestionEntryView(question="Second?"),
            ),
        ),
        "g1": QuestionRoundView(
            gate_id="g1",
            status="pending",
            data_state="complete",
            entries=(QuestionEntryView(question="Third?"),),
        ),
    }
    monkeypatch.setattr(
        "sase.question_gate_turn.projection.load_question_round",
        lambda **kwargs: views[kwargs["gate_id"]],
    )


def test_resolver_numbers_session_wide_and_filters_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_views(monkeypatch)
    root, _plan, first, _gate0 = _question_session()

    summary = build_detail_header_summary(root, lanes=frozenset({"questions"}))

    assert summary.ready_lanes == frozenset({"questions"})
    assert [
        (round.view.gate_id, round.first_number) for round in summary.question_rounds
    ] == [("g0", 1), ("g1", 3)]
    assert [round.member_label for round in summary.question_rounds] == [
        "gate",
        "gate-0",
    ]

    asking = build_detail_header_summary(first, lanes=frozenset({"questions"}))
    assert [
        (round.view.gate_id, round.first_number) for round in asking.question_rounds
    ] == [("g1", 3)]


def test_partial_lane_request_resolves_only_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_views(monkeypatch)
    root, _plan, _first, _gate0 = _question_session()

    summary = build_detail_header_summary(root, lanes=frozenset({"questions"}))

    assert summary.question_rounds != ()
    assert summary.memory_reads == ()
    assert summary.artifact_file_paths is None
    assert summary.associated_plan is None


def test_questions_lane_emits_trace_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_views(monkeypatch)
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    root, _plan, _first, _gate0 = _question_session()

    build_detail_header_summary(root, lanes=frozenset({"questions"}))

    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    spans = {row["span"] for row in rows}
    assert f"{DETAIL_HEADER_TRACE_SPAN_PREFIX}.question_rounds" in spans


def test_fresh_widget_stales_every_lane_including_questions() -> None:
    root, _plan, _first, _gate0 = _question_session()

    assert should_refresh_detail_header_summary(_Widget(), root) == (
        ALL_DETAIL_CONTEXT_LANES
    )


def test_gate_state_change_stales_only_questions_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary_cache.time.monotonic",
        lambda: now[0],
    )
    root, _plan, _first, gate0 = _question_session()
    widget = _Widget()
    cache_detail_header_summary(widget, root, DetailHeaderSummary())
    assert get_cached_detail_header_summary(widget, root) is not None

    now[0] += 1.0
    gate0.gate_state = "answered"

    stale = should_refresh_detail_header_summary(widget, root)
    assert stale == frozenset({"questions"})
    # The entry (and every other lane's freshness) survives the mismatch.
    assert get_cached_detail_header_summary(widget, root) is not None


def test_immediate_summary_never_marks_questions_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(**kwargs: object) -> QuestionRoundView:
        raise AssertionError("immediate paint must stay zero-I/O")

    monkeypatch.setattr("sase.question_gate_turn.projection.load_question_round", _fail)
    root, _plan, _first, _gate0 = _question_session()

    summary = immediate_detail_header_summary(_Widget(), root)

    assert "questions" not in summary.ready_lanes
    assert summary.question_rounds == ()


def test_merge_keeps_question_rounds() -> None:
    resolved = DetailHeaderSummary(
        question_rounds=(
            NumberedQuestionRound(view=QuestionRoundView(gate_id="g0"), first_number=1),
        ),
        ready_lanes=frozenset({"questions"}),
    )
    incoming = DetailHeaderSummary(ready_lanes=frozenset({"memory"}))

    merged = merge_detail_header_summary_lanes(resolved, incoming)

    assert merged.ready_lanes == frozenset({"questions", "memory"})
    assert len(merged.question_rounds) == 1


def test_questions_lane_is_not_a_context_lane() -> None:
    assert "questions" in ALL_DETAIL_CONTEXT_LANES
    assert "questions" not in CONTEXT_LANE_ORDER

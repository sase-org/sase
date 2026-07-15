"""Agents-tab metadata rendering tests for associated plan goals."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    _PLAN_GOAL_MAX_CHARS,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_detail_header_summary,
    build_header_text,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_metadata_prefix,
    assert_span_covers,
)


def test_goal_renders_immediately_after_bead_with_warm_italic_style() -> None:
    agent = make_agent(agent_name="sase-1.2")
    summary = DetailHeaderSummary(
        bead_display="sase-1.2 - Render metadata",
        plan_goal="Make agent intent immediately legible.",
    )

    header, _ = build_header_text(agent, summary=summary)

    assert_metadata_prefix(
        header,
        "Name: sase-1.2",
        "Bead: sase-1.2 - Render metadata",
        "Goal: Make agent intent immediately legible.",
    )
    assert_span_covers(
        header,
        "Make agent intent immediately legible.",
        "italic #FFD787",
    )


def test_goal_renders_after_name_when_no_bead_is_present() -> None:
    agent = make_agent(agent_name="planner")
    summary = DetailHeaderSummary(plan_goal="Ship the approved outcome.")

    header, _ = build_header_text(agent, summary=summary)

    assert_metadata_prefix(
        header,
        "Name: planner",
        "Goal: Ship the approved outcome.",
    )


def test_goal_is_absent_without_summary_or_value() -> None:
    agent = make_agent(agent_name="planner")

    cheap_header, _ = build_header_text(agent, cheap=True)
    no_goal_header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(plan_goal=None),
    )

    assert "Goal:" not in cheap_header.plain
    assert "Goal:" not in no_goal_header.plain


def test_long_goal_is_word_boundary_truncated_with_ellipsis() -> None:
    goal = " ".join(f"outcome{index}" for index in range(40))
    agent = make_agent(agent_name="planner")

    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(plan_goal=goal),
    )

    goal_line = header.plain.splitlines()[1].removeprefix("Goal: ")
    assert goal_line.endswith("…")
    assert len(goal_line) <= _PLAN_GOAL_MAX_CHARS + 1
    assert goal_line[:-1] in goal
    assert goal_line[:-1].endswith(tuple(str(index) for index in range(10)))


def test_normalized_goal_stays_on_one_metadata_line() -> None:
    agent = make_agent(agent_name="planner")
    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(
            plan_goal="Resolve plans reliably without blocking navigation."
        ),
    )

    assert header.plain.splitlines()[1] == (
        "Goal: Resolve plans reliably without blocking navigation."
    )


def test_detail_header_summary_resolves_plan_goal_off_hot_render_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="planner")
    calls: list[object] = []

    def resolve(agent_arg: object, *, lookup_session: object) -> str:
        calls.extend((agent_arg, lookup_session))
        return "Keep resolution in the enrichment worker."

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_goal",
        resolve,
    )

    summary = build_detail_header_summary(agent)

    assert summary.plan_goal == "Keep resolution in the enrichment worker."
    assert calls[0] is agent
    assert calls[1].__class__.__name__ == "BeadIssueLookupSession"

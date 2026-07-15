"""Agents-tab metadata rendering tests for associated plan goals."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.style import Style

from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    _PLAN_GOAL_LABEL_WIDTH,
    _PLAN_GOAL_MAX_WIDTH,
    AgentHeader,
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


def _render_header(header: AgentHeader, *, width: int) -> list[str]:
    output = StringIO()
    console = Console(file=output, width=width, color_system=None)
    console.print(header, end="")
    return output.getvalue().splitlines()


def _rendered_goal_lines(header: AgentHeader, *, width: int) -> list[str]:
    lines = _render_header(header, width=width)
    start = next(index for index, line in enumerate(lines) if line.startswith("Goal:"))
    goal_lines = [lines[start]]
    continuation_prefix = " " * _PLAN_GOAL_LABEL_WIDTH
    for line in lines[start + 1 :]:
        if not line.startswith(continuation_prefix):
            break
        goal_lines.append(line)
    return goal_lines


def _reconstruct_word_wrapped_goal(lines: list[str]) -> str:
    value_offset = _PLAN_GOAL_LABEL_WIDTH
    return " ".join(line[value_offset:].rstrip() for line in lines)


def _reconstruct_folded_token(lines: list[str]) -> str:
    value_offset = _PLAN_GOAL_LABEL_WIDTH
    return "".join(line[value_offset:].rstrip() for line in lines)


def test_goal_renders_immediately_after_bead_with_existing_styles() -> None:
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
    assert_span_covers(header, "Goal: ", "bold #87D7FF")
    assert_span_covers(
        header,
        "Make agent intent immediately legible.",
        "italic #FFD787",
    )
    assert _render_header(header, width=120)[:3] == [
        "Name: sase-1.2",
        "Bead: sase-1.2 - Render metadata",
        "Goal: Make agent intent immediately legible.",
    ]
    console = Console(width=120, color_system="truecolor")
    segments = list(console.render(header, console.options))
    assert any(
        segment.text == "Goal: " and segment.style == Style.parse("bold #87D7FF")
        for segment in segments
    )
    assert any(
        segment.text == "Make agent intent immediately legible."
        and segment.style == Style.parse("italic #FFD787")
        for segment in segments
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
    assert _render_header(header, width=120)[:2] == [
        "Name: planner",
        "Goal: Ship the approved outcome.",
    ]


def test_goal_is_absent_without_summary_or_value() -> None:
    agent = make_agent(agent_name="planner")

    cheap_header, _ = build_header_text(agent, cheap=True)
    no_goal_header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(plan_goal=None),
    )

    assert "Goal:" not in cheap_header.plain
    assert "Goal:" not in no_goal_header.plain
    assert not any("Goal:" in line for line in _render_header(cheap_header, width=40))
    assert not any("Goal:" in line for line in _render_header(no_goal_header, width=40))


def test_long_goal_renders_complete_and_caps_wide_lines_at_80_cells() -> None:
    goal = " ".join(f"outcome{index}" for index in range(40))
    agent = make_agent(agent_name="planner")

    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(plan_goal=goal),
    )

    goal_lines = _rendered_goal_lines(header, width=120)
    assert _reconstruct_word_wrapped_goal(goal_lines) == goal
    assert "…" not in "".join(goal_lines)
    assert len(goal_lines) > 1
    assert all(cell_len(line) <= _PLAN_GOAL_MAX_WIDTH for line in goal_lines)


def test_long_goal_reflows_with_hanging_indentation_in_a_narrow_panel() -> None:
    goal = (
        "Keep the complete approved outcome visible through every metadata "
        "refresh and terminal resize."
    )
    agent = make_agent(agent_name="planner")
    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(plan_goal=goal),
    )

    wide_goal_lines = _rendered_goal_lines(header, width=80)
    rendered_lines = _render_header(header, width=32)
    goal_lines = _rendered_goal_lines(header, width=32)

    assert _reconstruct_word_wrapped_goal(wide_goal_lines) == goal
    assert _reconstruct_word_wrapped_goal(goal_lines) == goal
    assert len(goal_lines) > len(wide_goal_lines)
    assert all(cell_len(line) <= 32 for line in goal_lines)
    assert all(line.startswith(" " * _PLAN_GOAL_LABEL_WIDTH) for line in goal_lines[1:])
    goal_start = rendered_lines.index(goal_lines[0])
    assert rendered_lines[goal_start + len(goal_lines)] == "ChangeSpec: test_cl"


@pytest.mark.parametrize(
    "goal",
    [
        "responsive_metadata_rendering_must_never_drop_this_final_suffix",
        "界" * 25 + "終",
    ],
)
def test_oversized_tokens_fold_by_terminal_cell_without_data_loss(goal: str) -> None:
    agent = make_agent(agent_name="planner")
    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(plan_goal=goal),
    )

    goal_lines = _rendered_goal_lines(header, width=24)

    assert _reconstruct_folded_token(goal_lines) == goal
    assert len(goal_lines) > 1
    assert all(cell_len(line) <= 24 for line in goal_lines)
    assert all(line.startswith(" " * _PLAN_GOAL_LABEL_WIDTH) for line in goal_lines[1:])


def test_normalized_short_goal_stays_on_one_metadata_line() -> None:
    agent = make_agent(agent_name="planner")
    goal = "Resolve plans reliably without blocking navigation."
    header, _ = build_header_text(
        agent,
        summary=DetailHeaderSummary(plan_goal=goal),
    )

    assert header.plain.splitlines()[1] == f"Goal: {goal}"
    assert _rendered_goal_lines(header, width=80) == [f"Goal: {goal}"]


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

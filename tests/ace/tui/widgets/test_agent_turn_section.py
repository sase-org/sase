"""Tests for responsive per-turn lanes in the agent detail header."""

from __future__ import annotations

from io import StringIO

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel._agent_turn_section import (
    TURN_LANE_LIMIT,
    ResponsiveTurnSection,
    _AgentTurnLane,
    _GateTurnLane,
    _MonitorTurnLane,
    build_agent_session_turn_lanes,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_AGENT_SESSION_NAME = "session"
_ROOT_SUFFIX = "20260805130000"


def _agent_session_root(
    *,
    role_suffix: str = "--plan",
    agent_session_role: str = "plan",
    **overrides: object,
) -> Agent:
    return make_agent(
        agent_session=_AGENT_SESSION_NAME,
        agent_session_role=agent_session_role,
        plan_chain_root=True,
        raw_suffix=_ROOT_SUFFIX,
        role_suffix=role_suffix,
        **overrides,
    )


def _agent_session_member(
    role_suffix: str, agent_session_role: str, **overrides: object
) -> Agent:
    values: dict[str, object] = {
        "agent_session": _AGENT_SESSION_NAME,
        "agent_session_role": agent_session_role,
        "agent_name": f"{_AGENT_SESSION_NAME}{role_suffix}",
        "parent_timestamp": _ROOT_SUFFIX,
        "raw_suffix": f"{_ROOT_SUFFIX}{role_suffix}",
        "role_suffix": role_suffix,
    }
    values.update(overrides)
    return make_agent(**values)


def _monitor_member(**overrides: object) -> Agent:
    values: dict[str, object] = {
        "monitor_command": "just check",
        "monitor_reason": "Verify the refactor before replying",
    }
    values.update(overrides)
    return _agent_session_member(
        "--mon",
        "monitor",
        **values,
    )


def _gate_member(**overrides: object) -> Agent:
    values: dict[str, object] = {
        "gate_id": "gate-123456",
        "gate_kind": "approval",
        "gate_label": "Approve deploy",
        "gate_reason": "Release needs confirmation",
        "gate_state": "pending",
        "gate_timeout_seconds": 300.0,
    }
    values.update(overrides)
    return _agent_session_member(
        "--gate",
        "gate",
        **values,
    )


def _agent_session(root: Agent, *members: Agent) -> Agent:
    root.followup_agents = list(members)
    return root


def _render(section: ResponsiveTurnSection, *, width: int) -> str:
    stream = StringIO()
    console = Console(
        file=stream,
        width=width,
        force_terminal=False,
        color_system=None,
    )
    console.print(section, end="")
    return stream.getvalue()


def _styles_covering(text: Text, substring: str) -> set[str]:
    start = text.plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


def test_mixed_agent_turn_agent_session_renders_one_lane_per_turn_aligned() -> None:
    agent = _agent_session(
        _agent_session_root(
            model="opus", llm_provider="claude", reasoning_effort="xhigh"
        ),
        _agent_session_member(
            "--code",
            "code",
            model="sonnet",
            llm_provider="claude",
            reasoning_effort="high",
        ),
        _agent_session_member(
            "--reviewer",
            "reviewer",
            model="gpt-5.2",
            llm_provider="codex",
            reasoning_effort="medium",
        ),
    )

    lanes = build_agent_session_turn_lanes(agent)
    lines = ResponsiveTurnSection(lanes).logical_text.plain.splitlines()

    assert lines == [
        "Turns: --plan     · CLAUDE(opus) @ xhigh",
        "       --code     · CLAUDE(sonnet) @ high",
        "       --reviewer · CODEX(gpt-5.2) @ medium",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_mixed_alias_agent_session_keeps_separator_column_aligned() -> None:
    agent = _agent_session(
        _agent_session_root(
            model="opus",
            llm_provider="claude",
            reasoning_effort="xhigh",
            model_alias="large",
        ),
        _agent_session_member(
            "--code",
            "code",
            model="sonnet",
            llm_provider="claude",
            reasoning_effort="high",
            model_alias="medium",
        ),
        _agent_session_member(
            "--reviewer",
            "reviewer",
            model="gpt-5.2",
            llm_provider="codex",
            reasoning_effort="medium",
        ),
    )

    lanes = build_agent_session_turn_lanes(agent)
    lines = ResponsiveTurnSection(lanes).logical_text.plain.splitlines()

    assert lines == [
        "Turns: --plan     · CLAUDE(opus) @ xhigh ← @large",
        "       --code     · CLAUDE(sonnet) @ high ← @medium",
        "       --reviewer · CODEX(gpt-5.2) @ medium",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_mixed_agent_and_monitor_agent_session_keeps_turn_order_and_alignment() -> None:
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"),
        _monitor_member(),
        _agent_session_member("--code", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_agent_session_turn_lanes(agent)
    lines = ResponsiveTurnSection(lanes).logical_text.plain.splitlines()

    assert [type(lane) for lane in lanes] == [
        _AgentTurnLane,
        _MonitorTurnLane,
        _AgentTurnLane,
    ]
    assert lines == [
        "Turns: --plan · CLAUDE(opus)",
        "       --mon  · ⚙ just check",
        "       --code · CLAUDE(sonnet)",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_mixed_agent_monitor_and_gate_agent_session_keeps_turn_order_and_alignment() -> (
    None
):
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"),
        _monitor_member(),
        _gate_member(),
        _agent_session_member("--code", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_agent_session_turn_lanes(agent)
    lines = ResponsiveTurnSection(lanes).logical_text.plain.splitlines()

    assert [type(lane) for lane in lanes] == [
        _AgentTurnLane,
        _MonitorTurnLane,
        _GateTurnLane,
        _AgentTurnLane,
    ]
    assert lines == [
        "Turns: --plan · CLAUDE(opus)",
        "       --mon  · ⚙ just check",
        "       --gate · ⋔ Approve deploy · pending due in 0s",
        "       --code · CLAUDE(sonnet)",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_nested_monitor_appears_after_its_starter_in_turn_lanes() -> None:
    root = _agent_session_root(model="opus", llm_provider="claude")
    coder = _agent_session_member(
        "--code", "code", model="sonnet", llm_provider="claude"
    )
    monitor = _monitor_member()
    review = _agent_session_member(
        "--reviewer", "reviewer", model="gpt-5.2", llm_provider="codex"
    )
    monitor.parent_timestamp = coder.raw_suffix
    root.followup_agents = [coder, review]
    root.runtime_children = [coder, review]
    coder.followup_agents = [monitor]
    coder.runtime_children = [monitor]

    lanes = build_agent_session_turn_lanes(root)

    assert [type(lane) for lane in lanes] == [
        _AgentTurnLane,
        _AgentTurnLane,
        _MonitorTurnLane,
        _AgentTurnLane,
    ]
    assert [lane.label for lane in lanes] == [
        "--plan",
        "--code",
        "--mon",
        "--reviewer",
    ]


def test_monitor_lane_never_renders_stale_model_metadata() -> None:
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"),
        _monitor_member(
            model="sonnet",
            llm_provider="claude",
            monitor_command=(
                "just check-full --all-targets --with-a-long-flag "
                "--and-another-wide-monitor-argument"
            ),
            monitor_reason="Full-suite verification before landing",
        ),
    )

    lines = ResponsiveTurnSection(
        build_agent_session_turn_lanes(agent)
    ).logical_text.plain

    assert "CLAUDE(sonnet)" not in lines
    assert "why" in lines
    assert "Full-suite verification before landing" in lines


def test_uniform_model_agent_session_still_renders_one_lane_per_member() -> None:
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"),
        _agent_session_member("--code", "code", model="opus", llm_provider="claude"),
        _agent_session_member(
            "--reviewer", "reviewer", model="opus", llm_provider="claude"
        ),
    )

    lanes = build_agent_session_turn_lanes(agent)

    assert len(lanes) == 3
    assert [lane.value.plain for lane in lanes if isinstance(lane, _AgentTurnLane)] == [
        "CLAUDE(opus)",
        "CLAUDE(opus)",
        "CLAUDE(opus)",
    ]


def test_member_with_no_model_renders_default_lane() -> None:
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"),
        _agent_session_member("--code", "code", model=None, llm_provider=None),
    )

    lanes = build_agent_session_turn_lanes(agent)

    assert len(lanes) == 2
    assert isinstance(lanes[1], _AgentTurnLane)
    assert lanes[1].value.plain == "default"


def test_member_with_effort_renders_suffix_member_without_does_not() -> None:
    agent = _agent_session(
        _agent_session_root(
            model="opus", llm_provider="claude", reasoning_effort="xhigh"
        ),
        _agent_session_member("--code", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_agent_session_turn_lanes(agent)

    assert isinstance(lanes[0], _AgentTurnLane)
    assert isinstance(lanes[1], _AgentTurnLane)
    assert lanes[0].value.plain == "CLAUDE(opus) @ xhigh"
    assert lanes[1].value.plain == "CLAUDE(sonnet)"


def test_cap_renders_twelve_lanes_plus_tail() -> None:
    members = [
        _agent_session_member(
            f"--m{index:02d}", f"phase-{index:02d}", model="opus", llm_provider="claude"
        )
        for index in range(1, 15)
    ]
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"), *members
    )

    lanes = build_agent_session_turn_lanes(agent)
    assert len(lanes) == 15
    section = ResponsiveTurnSection(
        lanes=lanes[:TURN_LANE_LIMIT],
        hidden_count=len(lanes) - TURN_LANE_LIMIT,
    )
    lines = section.logical_text.plain.splitlines()

    assert len(lines) == TURN_LANE_LIMIT + 1
    assert lines[-1].strip() == "… +3 more turns (see SESSION TURNS)"


def test_gutter_tracks_widest_label_only() -> None:
    agent = _agent_session(
        _agent_session_root(role_suffix="--a", model="opus", llm_provider="claude"),
        _agent_session_member("--bb", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_agent_session_turn_lanes(agent)
    lines = ResponsiveTurnSection(lanes).logical_text.plain.splitlines()

    gutter = max(len("--a"), len("--bb"))
    assert gutter == 4
    assert lines[0] == f"Turns: {'--a'.ljust(gutter)} · CLAUDE(opus)"
    assert lines[1] == f"       {'--bb'.ljust(gutter)} · CLAUDE(sonnet)"


def test_responsive_narrow_width_folds_value_column() -> None:
    agent = _agent_session(
        _agent_session_root(
            model="opus", llm_provider="claude", reasoning_effort="xhigh"
        ),
        _agent_session_member(
            "--code",
            "code",
            model="a-very-long-model-name-that-will-need-to-wrap",
            llm_provider="claude",
        ),
    )
    lanes = build_agent_session_turn_lanes(agent)
    section = ResponsiveTurnSection(lanes)

    lines = _render(section, width=40).splitlines()

    assert len(lines) > len(lanes)
    value_column = section.logical_text.plain.index("CLAUDE(opus)")
    wrapped_lines = lines[len(lanes) :]
    assert all(line.startswith(" " * value_column) for line in wrapped_lines)


def test_responsive_long_alias_chip_folds_under_value_column() -> None:
    agent = _agent_session(
        _agent_session_root(
            model="opus",
            llm_provider="claude",
            reasoning_effort="xhigh",
            model_alias="very_long_launch_alias_name",
        ),
        _agent_session_member("--code", "code", model="sonnet", llm_provider="claude"),
    )
    lanes = build_agent_session_turn_lanes(agent)
    section = ResponsiveTurnSection(lanes)

    lines = _render(section, width=48).splitlines()

    assert len(lines) > len(lanes)
    value_column = section.logical_text.plain.index("CLAUDE(opus)")
    alias_wrap = next(line for line in lines if "@very_long_launch_alias_name" in line)
    assert alias_wrap.startswith(" " * value_column)


def test_responsive_wide_width_matches_logical_text() -> None:
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"),
        _agent_session_member("--code", "code", model="sonnet", llm_provider="claude"),
    )
    lanes = build_agent_session_turn_lanes(agent)
    section = ResponsiveTurnSection(lanes)

    assert _render(section, width=200) == section.logical_text.plain


def test_monitor_command_that_exactly_fits_stays_on_one_line() -> None:
    command = "just check"
    lane = _MonitorTurnLane("--mon", command=command, reason="Should not render")
    section = ResponsiveTurnSection((lane,))
    width = (
        cell_len("Turns: ")
        + cell_len("--mon")
        + cell_len(" · ")
        + cell_len("⚙ ")
        + cell_len(command)
    )

    assert _render(section, width=width).splitlines() == ["Turns: --mon · ⚙ just check"]


def test_monitor_command_one_cell_too_wide_uses_reason_continuation() -> None:
    command = "just check"
    lane = _MonitorTurnLane(
        "--mon",
        command=command,
        reason="Full-suite verification before landing",
    )
    section = ResponsiveTurnSection((lane,))
    exact_width = (
        cell_len("Turns: ")
        + cell_len("--mon")
        + cell_len(" · ")
        + cell_len("⚙ ")
        + cell_len(command)
    )

    lines = _render(section, width=exact_width - 1).splitlines()

    assert lines[0] == "Turns: --mon · ⚙ why"
    assert lines[1].startswith("         ↳ Full-suite")
    assert "just check" not in "\n".join(lines)


def test_monitor_multiline_command_uses_reason_even_when_short() -> None:
    lane = _MonitorTurnLane(
        "--mon",
        command="just check\njust test",
        reason="Two commands run under the monitor",
    )
    section = ResponsiveTurnSection((lane,))

    lines = _render(section, width=120).splitlines()

    assert lines == [
        "Turns: --mon · ⚙ why",
        "         ↳ Two commands run under the monitor",
    ]


def test_monitor_reason_wraps_with_hanging_indent_and_no_overflow() -> None:
    reason = (
        "Full-suite verification before landing so the final report can cite the "
        "combined check result without hiding a failed narrow render"
    )
    lane = _MonitorTurnLane(
        "--mon",
        command="just check-full --include visual --include slow --include all",
        reason=reason,
    )
    section = ResponsiveTurnSection((lane,))
    width = 52

    lines = _render(section, width=width).splitlines()

    assert lines[0] == "Turns: --mon · ⚙ why"
    assert lines[1].startswith("         ↳ Full-suite verification")
    assert all(line.startswith("           ") for line in lines[2:])
    assert all(cell_len(line) <= width for line in lines)


def test_monitor_without_reason_wraps_long_command_as_diagnostic() -> None:
    command = "just check-full --include visual --include slow"
    lane = _MonitorTurnLane("--mon", command=command, reason="  ")
    section = ResponsiveTurnSection((lane,))

    lines = _render(section, width=40).splitlines()

    assert lines[0] == "Turns: --mon · ⚙ cmd"
    assert "just check-full --include" in lines[1]
    assert "visual --include slow" in lines[2]


def test_monitor_empty_command_and_reason_renders_unavailable_placeholder() -> None:
    lane = _MonitorTurnLane("--mon", command="  ", reason=None)
    section = ResponsiveTurnSection((lane,))

    assert _render(section, width=80).splitlines() == ["Turns: --mon · ⚙ unavailable"]


def test_styles_label_and_member_label() -> None:
    agent = _agent_session(
        _agent_session_root(model="opus", llm_provider="claude"),
        _agent_session_member("--code", "code", model="sonnet", llm_provider="claude"),
    )
    lanes = build_agent_session_turn_lanes(agent)
    text = ResponsiveTurnSection(lanes).logical_text

    assert "#FFD700" in _styles_covering(text, "--plan")
    assert "bold #87D7FF" in _styles_covering(text, "Turns: ")

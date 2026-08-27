"""Tests for responsive per-shell lanes in the agent detail header."""

from __future__ import annotations

from io import StringIO

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel._agent_shell_section import (
    SHELL_LANE_LIMIT,
    ResponsiveShellSection,
    _AgentShellLane,
    _GateShellLane,
    _MonitorShellLane,
    build_family_shell_lanes,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_FAMILY_NAME = "family"
_ROOT_SUFFIX = "20260805130000"


def _family_root(
    *, role_suffix: str = "--plan", agent_family_role: str = "plan", **overrides: object
) -> Agent:
    return make_agent(
        agent_family=_FAMILY_NAME,
        agent_family_role=agent_family_role,
        plan_chain_root=True,
        raw_suffix=_ROOT_SUFFIX,
        role_suffix=role_suffix,
        **overrides,
    )


def _family_member(
    role_suffix: str, agent_family_role: str, **overrides: object
) -> Agent:
    values: dict[str, object] = {
        "agent_family": _FAMILY_NAME,
        "agent_family_role": agent_family_role,
        "agent_name": f"{_FAMILY_NAME}{role_suffix}",
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
    return _family_member(
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
    return _family_member(
        "--gate",
        "gate",
        **values,
    )


def _family(root: Agent, *members: Agent) -> Agent:
    root.followup_agents = list(members)
    return root


def _render(section: ResponsiveShellSection, *, width: int) -> str:
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


def test_mixed_agent_shell_family_renders_one_lane_per_shell_aligned() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude", reasoning_effort="xhigh"),
        _family_member(
            "--code",
            "code",
            model="sonnet",
            llm_provider="claude",
            reasoning_effort="high",
        ),
        _family_member(
            "--reviewer",
            "reviewer",
            model="gpt-5.2",
            llm_provider="codex",
            reasoning_effort="medium",
        ),
    )

    lanes = build_family_shell_lanes(agent)
    lines = ResponsiveShellSection(lanes).logical_text.plain.splitlines()

    assert lines == [
        "Shells: --plan     · CLAUDE(opus) @ xhigh",
        "        --code     · CLAUDE(sonnet) @ high",
        "        --reviewer · CODEX(gpt-5.2) @ medium",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_mixed_alias_family_keeps_separator_column_aligned() -> None:
    agent = _family(
        _family_root(
            model="opus",
            llm_provider="claude",
            reasoning_effort="xhigh",
            model_alias="large",
        ),
        _family_member(
            "--code",
            "code",
            model="sonnet",
            llm_provider="claude",
            reasoning_effort="high",
            model_alias="medium",
        ),
        _family_member(
            "--reviewer",
            "reviewer",
            model="gpt-5.2",
            llm_provider="codex",
            reasoning_effort="medium",
        ),
    )

    lanes = build_family_shell_lanes(agent)
    lines = ResponsiveShellSection(lanes).logical_text.plain.splitlines()

    assert lines == [
        "Shells: --plan     · CLAUDE(opus) @ xhigh ← @large",
        "        --code     · CLAUDE(sonnet) @ high ← @medium",
        "        --reviewer · CODEX(gpt-5.2) @ medium",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_mixed_agent_and_monitor_family_keeps_shell_order_and_alignment() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _monitor_member(),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_family_shell_lanes(agent)
    lines = ResponsiveShellSection(lanes).logical_text.plain.splitlines()

    assert [type(lane) for lane in lanes] == [
        _AgentShellLane,
        _MonitorShellLane,
        _AgentShellLane,
    ]
    assert lines == [
        "Shells: --plan · CLAUDE(opus)",
        "        --mon  · ⚙ just check",
        "        --code · CLAUDE(sonnet)",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_mixed_agent_monitor_and_gate_family_keeps_shell_order_and_alignment() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _monitor_member(),
        _gate_member(),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_family_shell_lanes(agent)
    lines = ResponsiveShellSection(lanes).logical_text.plain.splitlines()

    assert [type(lane) for lane in lanes] == [
        _AgentShellLane,
        _MonitorShellLane,
        _GateShellLane,
        _AgentShellLane,
    ]
    assert lines == [
        "Shells: --plan · CLAUDE(opus)",
        "        --mon  · ⚙ just check",
        "        --gate · ⋔ Approve deploy · pending due in 0s",
        "        --code · CLAUDE(sonnet)",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_nested_monitor_appears_after_its_starter_in_shell_lanes() -> None:
    root = _family_root(model="opus", llm_provider="claude")
    coder = _family_member("--code", "code", model="sonnet", llm_provider="claude")
    monitor = _monitor_member()
    review = _family_member(
        "--reviewer", "reviewer", model="gpt-5.2", llm_provider="codex"
    )
    monitor.parent_timestamp = coder.raw_suffix
    root.followup_agents = [coder, review]
    root.runtime_children = [coder, review]
    coder.followup_agents = [monitor]
    coder.runtime_children = [monitor]

    lanes = build_family_shell_lanes(root)

    assert [type(lane) for lane in lanes] == [
        _AgentShellLane,
        _AgentShellLane,
        _MonitorShellLane,
        _AgentShellLane,
    ]
    assert [lane.label for lane in lanes] == [
        "--plan",
        "--code",
        "--mon",
        "--reviewer",
    ]


def test_monitor_lane_never_renders_stale_model_metadata() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
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

    lines = ResponsiveShellSection(build_family_shell_lanes(agent)).logical_text.plain

    assert "CLAUDE(sonnet)" not in lines
    assert "why" in lines
    assert "Full-suite verification before landing" in lines


def test_uniform_model_family_still_renders_one_lane_per_member() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _family_member("--code", "code", model="opus", llm_provider="claude"),
        _family_member("--reviewer", "reviewer", model="opus", llm_provider="claude"),
    )

    lanes = build_family_shell_lanes(agent)

    assert len(lanes) == 3
    assert [
        lane.value.plain for lane in lanes if isinstance(lane, _AgentShellLane)
    ] == [
        "CLAUDE(opus)",
        "CLAUDE(opus)",
        "CLAUDE(opus)",
    ]


def test_member_with_no_model_renders_default_lane() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _family_member("--code", "code", model=None, llm_provider=None),
    )

    lanes = build_family_shell_lanes(agent)

    assert len(lanes) == 2
    assert isinstance(lanes[1], _AgentShellLane)
    assert lanes[1].value.plain == "default"


def test_member_with_effort_renders_suffix_member_without_does_not() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude", reasoning_effort="xhigh"),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_family_shell_lanes(agent)

    assert isinstance(lanes[0], _AgentShellLane)
    assert isinstance(lanes[1], _AgentShellLane)
    assert lanes[0].value.plain == "CLAUDE(opus) @ xhigh"
    assert lanes[1].value.plain == "CLAUDE(sonnet)"


def test_cap_renders_twelve_lanes_plus_tail() -> None:
    members = [
        _family_member(
            f"--m{index:02d}", f"phase-{index:02d}", model="opus", llm_provider="claude"
        )
        for index in range(1, 15)
    ]
    agent = _family(_family_root(model="opus", llm_provider="claude"), *members)

    lanes = build_family_shell_lanes(agent)
    assert len(lanes) == 15
    section = ResponsiveShellSection(
        lanes=lanes[:SHELL_LANE_LIMIT],
        hidden_count=len(lanes) - SHELL_LANE_LIMIT,
    )
    lines = section.logical_text.plain.splitlines()

    assert len(lines) == SHELL_LANE_LIMIT + 1
    assert lines[-1].strip() == "… +3 more shells (see FAMILY SHELLS)"


def test_gutter_tracks_widest_label_only() -> None:
    agent = _family(
        _family_root(role_suffix="--a", model="opus", llm_provider="claude"),
        _family_member("--bb", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_family_shell_lanes(agent)
    lines = ResponsiveShellSection(lanes).logical_text.plain.splitlines()

    gutter = max(len("--a"), len("--bb"))
    assert gutter == 4
    assert lines[0] == f"Shells: {'--a'.ljust(gutter)} · CLAUDE(opus)"
    assert lines[1] == f"        {'--bb'.ljust(gutter)} · CLAUDE(sonnet)"


def test_responsive_narrow_width_folds_value_column() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude", reasoning_effort="xhigh"),
        _family_member(
            "--code",
            "code",
            model="a-very-long-model-name-that-will-need-to-wrap",
            llm_provider="claude",
        ),
    )
    lanes = build_family_shell_lanes(agent)
    section = ResponsiveShellSection(lanes)

    lines = _render(section, width=40).splitlines()

    assert len(lines) > len(lanes)
    value_column = section.logical_text.plain.index("CLAUDE(opus)")
    wrapped_lines = lines[len(lanes) :]
    assert all(line.startswith(" " * value_column) for line in wrapped_lines)


def test_responsive_long_alias_chip_folds_under_value_column() -> None:
    agent = _family(
        _family_root(
            model="opus",
            llm_provider="claude",
            reasoning_effort="xhigh",
            model_alias="very_long_launch_alias_name",
        ),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )
    lanes = build_family_shell_lanes(agent)
    section = ResponsiveShellSection(lanes)

    lines = _render(section, width=48).splitlines()

    assert len(lines) > len(lanes)
    value_column = section.logical_text.plain.index("CLAUDE(opus)")
    alias_wrap = next(line for line in lines if "@very_long_launch_alias_name" in line)
    assert alias_wrap.startswith(" " * value_column)


def test_responsive_wide_width_matches_logical_text() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )
    lanes = build_family_shell_lanes(agent)
    section = ResponsiveShellSection(lanes)

    assert _render(section, width=200) == section.logical_text.plain


def test_monitor_command_that_exactly_fits_stays_on_one_line() -> None:
    command = "just check"
    lane = _MonitorShellLane("--mon", command=command, reason="Should not render")
    section = ResponsiveShellSection((lane,))
    width = (
        cell_len("Shells: ")
        + cell_len("--mon")
        + cell_len(" · ")
        + cell_len("⚙ ")
        + cell_len(command)
    )

    assert _render(section, width=width).splitlines() == [
        "Shells: --mon · ⚙ just check"
    ]


def test_monitor_command_one_cell_too_wide_uses_reason_continuation() -> None:
    command = "just check"
    lane = _MonitorShellLane(
        "--mon",
        command=command,
        reason="Full-suite verification before landing",
    )
    section = ResponsiveShellSection((lane,))
    exact_width = (
        cell_len("Shells: ")
        + cell_len("--mon")
        + cell_len(" · ")
        + cell_len("⚙ ")
        + cell_len(command)
    )

    lines = _render(section, width=exact_width - 1).splitlines()

    assert lines[0] == "Shells: --mon · ⚙ why"
    assert lines[1].startswith("          ↳ Full-suite")
    assert "just check" not in "\n".join(lines)


def test_monitor_multiline_command_uses_reason_even_when_short() -> None:
    lane = _MonitorShellLane(
        "--mon",
        command="just check\njust test",
        reason="Two commands run under the monitor",
    )
    section = ResponsiveShellSection((lane,))

    lines = _render(section, width=120).splitlines()

    assert lines == [
        "Shells: --mon · ⚙ why",
        "          ↳ Two commands run under the monitor",
    ]


def test_monitor_reason_wraps_with_hanging_indent_and_no_overflow() -> None:
    reason = (
        "Full-suite verification before landing so the final report can cite the "
        "combined check result without hiding a failed narrow render"
    )
    lane = _MonitorShellLane(
        "--mon",
        command="just check-full --include visual --include slow --include all",
        reason=reason,
    )
    section = ResponsiveShellSection((lane,))
    width = 52

    lines = _render(section, width=width).splitlines()

    assert lines[0] == "Shells: --mon · ⚙ why"
    assert lines[1].startswith("          ↳ Full-suite verification")
    assert all(line.startswith("            ") for line in lines[2:])
    assert all(cell_len(line) <= width for line in lines)


def test_monitor_without_reason_wraps_long_command_as_diagnostic() -> None:
    command = "just check-full --include visual --include slow"
    lane = _MonitorShellLane("--mon", command=command, reason="  ")
    section = ResponsiveShellSection((lane,))

    lines = _render(section, width=40).splitlines()

    assert lines[0] == "Shells: --mon · ⚙ cmd"
    assert "just check-full --include" in lines[1]
    assert "visual --include slow" in lines[2]


def test_monitor_empty_command_and_reason_renders_unavailable_placeholder() -> None:
    lane = _MonitorShellLane("--mon", command="  ", reason=None)
    section = ResponsiveShellSection((lane,))

    assert _render(section, width=80).splitlines() == ["Shells: --mon · ⚙ unavailable"]


def test_styles_label_and_member_label() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )
    lanes = build_family_shell_lanes(agent)
    text = ResponsiveShellSection(lanes).logical_text

    assert "#FFD700" in _styles_covering(text, "--plan")
    assert "bold #87D7FF" in _styles_covering(text, "Shells: ")

"""Tests for responsive per-member model lanes in the agent detail header."""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.text import Text

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel._agent_model_section import (
    MODEL_LANE_LIMIT,
    ResponsiveModelSection,
    build_family_model_lanes,
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
    return make_agent(
        agent_family=_FAMILY_NAME,
        agent_family_role=agent_family_role,
        parent_timestamp=_ROOT_SUFFIX,
        role_suffix=role_suffix,
        **overrides,
    )


def _family(root: Agent, *members: Agent) -> Agent:
    root.followup_agents = list(members)
    return root


def _render(section: ResponsiveModelSection, *, width: int) -> str:
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


def test_mixed_model_family_renders_one_lane_per_member_aligned() -> None:
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

    lanes = build_family_model_lanes(agent)
    lines = ResponsiveModelSection(lanes).logical_text.plain.splitlines()

    assert lines == [
        "Model: --plan     · CLAUDE(opus) @ xhigh",
        "       --code     · CLAUDE(sonnet) @ high",
        "       --reviewer · CODEX(gpt-5.2) @ medium",
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

    lanes = build_family_model_lanes(agent)
    lines = ResponsiveModelSection(lanes).logical_text.plain.splitlines()

    assert lines == [
        "Model: --plan     · CLAUDE(opus) @ xhigh ← @large",
        "       --code     · CLAUDE(sonnet) @ high ← @medium",
        "       --reviewer · CODEX(gpt-5.2) @ medium",
    ]
    dot_positions = {line.index("·") for line in lines}
    assert len(dot_positions) == 1


def test_uniform_model_family_still_renders_one_lane_per_member() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _family_member("--code", "code", model="opus", llm_provider="claude"),
        _family_member("--reviewer", "reviewer", model="opus", llm_provider="claude"),
    )

    lanes = build_family_model_lanes(agent)

    assert len(lanes) == 3
    assert [value.plain for _label, value in lanes] == [
        "CLAUDE(opus)",
        "CLAUDE(opus)",
        "CLAUDE(opus)",
    ]


def test_member_with_no_model_renders_default_lane() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _family_member("--code", "code", model=None, llm_provider=None),
    )

    lanes = build_family_model_lanes(agent)

    assert len(lanes) == 2
    assert lanes[1][1].plain == "default"


def test_member_with_effort_renders_suffix_member_without_does_not() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude", reasoning_effort="xhigh"),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_family_model_lanes(agent)

    assert lanes[0][1].plain == "CLAUDE(opus) @ xhigh"
    assert lanes[1][1].plain == "CLAUDE(sonnet)"


def test_cap_renders_twelve_lanes_plus_tail() -> None:
    members = [
        _family_member(
            f"--m{index:02d}", f"phase-{index:02d}", model="opus", llm_provider="claude"
        )
        for index in range(1, 15)
    ]
    agent = _family(_family_root(model="opus", llm_provider="claude"), *members)

    lanes = build_family_model_lanes(agent)
    assert len(lanes) == 15
    section = ResponsiveModelSection(
        lanes=lanes[:MODEL_LANE_LIMIT],
        hidden_count=len(lanes) - MODEL_LANE_LIMIT,
    )
    lines = section.logical_text.plain.splitlines()

    assert len(lines) == MODEL_LANE_LIMIT + 1
    assert lines[-1].strip() == "… +3 more members (see FAMILY MEMBERS)"


def test_gutter_tracks_widest_label_only() -> None:
    agent = _family(
        _family_root(role_suffix="--a", model="opus", llm_provider="claude"),
        _family_member("--bb", "code", model="sonnet", llm_provider="claude"),
    )

    lanes = build_family_model_lanes(agent)
    lines = ResponsiveModelSection(lanes).logical_text.plain.splitlines()

    gutter = max(len("--a"), len("--bb"))
    assert gutter == 4
    assert lines[0] == f"Model: {'--a'.ljust(gutter)} · CLAUDE(opus)"
    assert lines[1] == f"       {'--bb'.ljust(gutter)} · CLAUDE(sonnet)"


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
    lanes = build_family_model_lanes(agent)
    section = ResponsiveModelSection(lanes)

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
    lanes = build_family_model_lanes(agent)
    section = ResponsiveModelSection(lanes)

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
    lanes = build_family_model_lanes(agent)
    section = ResponsiveModelSection(lanes)

    assert _render(section, width=200) == section.logical_text.plain


def test_styles_label_and_member_label() -> None:
    agent = _family(
        _family_root(model="opus", llm_provider="claude"),
        _family_member("--code", "code", model="sonnet", llm_provider="claude"),
    )
    lanes = build_family_model_lanes(agent)
    text = ResponsiveModelSection(lanes).logical_text

    assert "#FFD700" in _styles_covering(text, "--plan")
    assert "bold #87D7FF" in _styles_covering(text, "Model: ")

"""Tests for responsive wait lanes in the agent detail header."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_display_header_metadata import (
    append_agent_metadata_fields,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_wait_section import (
    WAIT_SECTION_ID,
    ResponsiveWaitSection,
    build_wait_lanes,
)
from sase.core.wait_dependency_resolution import TribeWaitBinding
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _lanes(agent, **overrides):
    arguments = {
        "agent_status_buckets": None,
        "clan_wait_member_statuses": None,
        "tribe_wait_bindings": None,
        "wait_bead_statuses": None,
        "runner_queue_ahead_count": None,
    }
    arguments.update(overrides)
    return build_wait_lanes(agent, **arguments)


def _render(section: ResponsiveWaitSection, *, width: int) -> str:
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


def test_agents_and_beads_share_one_aligned_value_column() -> None:
    lanes = _lanes(
        make_agent(
            status="WAITING",
            waiting_for=["agent-one"],
            waiting_for_beads=["bead-one"],
        )
    )

    lines = ResponsiveWaitSection(lanes).logical_text.plain.splitlines()

    assert lines == [
        "Wait: [agents] agent-one",
        "      [beads]  bead-one",
    ]
    assert lines[0].index("agent-one") == lines[1].index("bead-one")
    assert lines[1].startswith(" " * 6)


def test_gutter_width_tracks_only_present_lanes() -> None:
    agents_and_beads = _lanes(
        make_agent(
            status="WAITING",
            waiting_for=["agent-one"],
            waiting_for_beads=["bead-one"],
        )
    )
    time_only = _lanes(
        make_agent(status="WAITING", wait_duration=300),
    )

    agents_and_beads_lines = ResponsiveWaitSection(
        agents_and_beads
    ).logical_text.plain.splitlines()
    time_line = ResponsiveWaitSection(time_only).logical_text.plain.splitlines()[0]

    assert agents_and_beads_lines[0].index("agent-one") - len("Wait: ") == 9
    assert agents_and_beads_lines[1].index("bead-one") - len("Wait: ") == 9
    assert time_line == "Wait: [time] 5m"
    assert time_line.index("5m") - len("Wait: ") == 7


def test_lane_order_is_agents_tribes_beads_time_runners() -> None:
    lanes = _lanes(
        make_agent(
            status="WAITING",
            waiting_for=["agent-one", "@epic"],
            waiting_for_beads=["bead-one"],
            wait_duration=300,
            wait_runners=2,
            slot_requested_at="2026-07-28T12:00:00Z",
        )
    )

    assert tuple(tag for tag, _value in lanes) == (
        "agents",
        "tribes",
        "beads",
        "time",
        "runners",
    )
    assert [
        line[6 : line.index("]") + 1]
        for line in ResponsiveWaitSection(lanes).logical_text.plain.splitlines()
    ] == ["[agents]", "[tribes]", "[beads]", "[time]", "[runners]"]


def test_pending_tribe_wait_uses_tribe_lane_without_unknown_glyph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_wait_section."
        "named_tribe_identity_colors",
        lambda _names: {"epic": "#123456"},
    )
    agent = make_agent(
        status="WAITING",
        raw_suffix="20260728120000",
        waiting_for=["@epic"],
    )

    text = ResponsiveWaitSection(_lanes(agent)).logical_text

    assert text.plain == "Wait: [tribes] @epic (next launch)\n"
    assert "?" not in text.plain
    assert "bold #123456" in _styles_covering(text, "@epic")


def test_reserved_tribe_wait_uses_unresolvable_marker_not_pending_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_wait_section."
        "named_tribe_identity_colors",
        lambda _names: {"default": "#654321"},
    )
    agent = make_agent(
        status="WAITING",
        raw_suffix="20260728120000",
        waiting_for=["@default"],
    )

    text = ResponsiveWaitSection(
        _lanes(
            agent,
            tribe_wait_bindings={
                (agent.identity, "@default"): TribeWaitBinding(
                    tribe="default",
                    state="reserved",
                )
            },
        )
    ).logical_text

    assert text.plain == ("Wait: [tribes] @default ! (reserved - never resolves)\n")
    assert "?" not in text.plain
    assert "(next launch)" not in text.plain
    assert "bold #654321" in _styles_covering(text, "@default")
    assert "bold #FF5F5F" in _styles_covering(text, "!")


def test_bound_tribe_wait_names_entity_and_status() -> None:
    agent = make_agent(
        status="WAITING",
        raw_suffix="20260728120000",
        waiting_for=["@epic"],
    )
    binding = TribeWaitBinding(
        tribe="epic",
        state="bound",
        kind="agent",
        name="epic.builder",
    )

    text = ResponsiveWaitSection(
        _lanes(
            agent,
            agent_status_buckets={"epic.builder": "Done"},
            tribe_wait_bindings={(agent.identity, "@epic"): binding},
        )
    ).logical_text

    assert text.plain == "Wait: [tribes] @epic → epic.builder ✓\n"
    assert "?" not in text.plain


def test_rendered_wrap_keeps_hanging_indent() -> None:
    dependencies = [f"dependency-{index}" for index in range(12)]
    lanes = _lanes(
        make_agent(status="WAITING", waiting_for=dependencies),
    )
    section = ResponsiveWaitSection(lanes)

    lines = _render(section, width=60).splitlines()

    assert len(lines) > 1
    value_column = section.logical_text.plain.index(dependencies[0])
    assert all(line.startswith(" " * value_column) for line in lines[1:])
    assert all(not line.startswith("dependency-") for line in lines[1:])


def test_logical_text_equals_unwrapped_render() -> None:
    lanes = _lanes(
        make_agent(
            status="WAITING",
            waiting_for=["agent-one", "agent-two"],
            waiting_for_beads=["bead-one"],
        )
    )
    section = ResponsiveWaitSection(lanes)

    assert _render(section, width=200) == section.logical_text.plain


def test_tag_styles_are_category_specific() -> None:
    lanes = _lanes(
        make_agent(
            status="WAITING",
            waiting_for=["agent-one"],
            waiting_for_beads=["bead-one"],
        )
    )
    text = ResponsiveWaitSection(lanes).logical_text

    assert "dim #AF87FF" in _styles_covering(text, "[agents]")
    assert "dim #FFAF00" in _styles_covering(text, "[beads]")


def test_no_wait_state_renders_no_lanes_or_field() -> None:
    agent = make_agent(status="RUNNING")

    assert _lanes(agent) == ()
    header, _ = build_header_text(agent, cheap=True)
    assert "Wait:" not in header.plain


def test_queued_state_keeps_single_line_queue_field() -> None:
    agent = make_agent(
        status="QUEUED",
        waiting_for=["suppressed"],
        wait_duration=300,
        wait_runners=2,
        slot_requested_at="2026-07-28T12:00:00Z",
        runner_slot_queue_position=1,
        runner_slot_queue_size=2,
    )

    header, _ = build_header_text(agent, cheap=True)

    assert "Queue: #1 of 2" in header.plain
    assert "Wait:" not in header.plain


@pytest.mark.parametrize(
    "explicit_wait",
    [
        {"wait_runners_explicit": True},
        {"wait_priority": 5, "wait_priority_explicit": True},
    ],
)
def test_queued_explicit_wait_renders_runner_lane_only(
    explicit_wait: dict[str, object],
) -> None:
    agent = make_agent(
        status="QUEUED",
        waiting_for=["suppressed"],
        wait_runners=2,
        slot_requested_at="2026-07-28T12:00:00Z",
        runner_slot_queue_position=1,
        runner_slot_queue_size=2,
        **explicit_wait,
    )

    header, _ = build_header_text(agent, cheap=True)

    assert "Queue: #1 of 2" in header.plain
    assert "Wait: [runners]" in header.plain
    assert "[agents]" not in header.plain


def test_responsive_range_covers_exact_logical_wait_block() -> None:
    text = Text("prefix\n")
    ranges: dict[str, tuple[int, int]] = {}
    metadata = append_agent_metadata_fields(
        text,
        make_agent(
            status="WAITING",
            waiting_for=["agent-one"],
            waiting_for_beads=["bead-one"],
        ),
        cheap=True,
        hint_state=None,
        summary=None,
        agent_status_buckets=None,
        cached_bead_display=lambda _agent: None,
        responsive_ranges=ranges,
    )

    section = metadata.wait_section
    assert section is not None
    start, end = ranges[WAIT_SECTION_ID]
    prefix = text.plain[:start]
    block = text.plain[start:end]
    suffix = text.plain[end:]
    assert block == section.logical_text.plain
    assert block.endswith("\n")
    assert prefix + block + suffix == text.plain

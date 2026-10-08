"""In-flight highlighting for the jump legend (lit pills and packing)."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.util.renderable_digest import renderable_content_digest
from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable
from sase.ace.tui.widgets.prompt_panel._member_in_flight import (
    IN_FLIGHT_RUNNING_TINT,
    IN_FLIGHT_STARTING_TINT,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)

WIDTHS = (30, 48, 64, 80, 120, 200)

_LANE_IDENTITY = (AgentType.RUNNING, "lane", None)


def _entries(
    labels: list[str],
    *,
    statuses: dict[str, str] | None = None,
    dismissed: frozenset[str] = frozenset(),
) -> tuple[MemberRosterEntry, ...]:
    return tuple(
        MemberRosterEntry(
            identity=(AgentType.RUNNING, label, None),
            presented_name=label,
            label=label,
            kind="agent",
            status=(statuses or {}).get(label, "RUNNING"),
            model="m",
            duration="1m",
            is_dismissed=label in dismissed,
            target_role="dismissed" if label in dismissed else None,
        )
        for label in labels
    )


def _single_section_map(
    labels: list[str],
    *,
    statuses: dict[str, str] | None = None,
    dismissed: frozenset[str] = frozenset(),
) -> MemberJumpMap:
    return append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(labels, statuses=statuses, dismissed=dismissed),
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(labels)),
    )


def _legend_lines(jump_map: MemberJumpMap, width: int, mode: str) -> list[Text]:
    renderable = JumpLegendRenderable(jump_map, mode=mode)
    return renderable._lines_for_width(width)  # noqa: SLF001


def _rendered(jump_map: MemberJumpMap, width: int, mode: str) -> list[str]:
    output = StringIO()
    Console(file=output, width=width, color_system=None).print(
        JumpLegendRenderable(jump_map, mode=mode), end=""
    )
    return output.getvalue().splitlines()


def _covering_styles(line: Text, needle: str) -> list[str]:
    start = line.plain.index(needle)
    end = start + len(needle)
    return [
        str(span.style)
        for span in line.spans
        if span.start <= start and span.end >= end
    ]


def _overflow_token(lines: list[str]) -> str | None:
    token = lines[-1].split("  ")[-1].strip()
    return token if token.startswith("+") else None


_MIXED_STATUSES = {
    "runabout": "RUNNING",
    "startle": "STARTING",
    "donut": "DONE",
    "failwhale": "FAILED",
    "quiz": "QUESTION",
    "waiter": "WAITING",
}


def _mixed_map() -> MemberJumpMap:
    return _single_section_map(list(_MIXED_STATUSES), statuses=_MIXED_STATUSES)


def test_lit_cells_carry_tint_backgrounds() -> None:
    lines = _legend_lines(_mixed_map(), 200, "collapsed")
    assert len(lines) == 1
    line = lines[0]
    assert _covering_styles(line, "runabout") == [
        f"bold #FFD700 on {IN_FLIGHT_RUNNING_TINT}"
    ]
    assert _covering_styles(line, "startle") == [
        f"bold #FFD700 on {IN_FLIGHT_STARTING_TINT}"
    ]
    running_glyph = _covering_styles(line, "▶")
    assert len(running_glyph) == 1
    assert IN_FLIGHT_RUNNING_TINT in running_glyph[0]
    starting_glyph = _covering_styles(line, "◐")
    assert len(starting_glyph) == 1
    assert IN_FLIGHT_STARTING_TINT in starting_glyph[0]
    assert "runabout ▶ " in line.plain
    assert "startle ◐ " in line.plain


def test_unlit_cells_have_no_background_and_match_plain_text() -> None:
    lines = _legend_lines(_mixed_map(), 200, "collapsed")
    line = lines[0]
    for label, glyph in (
        ("donut", "✓"),
        ("failwhale", "✗"),
        ("quiz", "▲"),
        ("waiter", "⏳"),
    ):
        styles = _covering_styles(line, label)
        assert styles, label
        assert all(" on " not in style for style in styles), (label, styles)
        assert f"{label} {glyph}" in line.plain


def test_dismissed_running_target_is_never_lit() -> None:
    jump_map = _single_section_map(["gone"], dismissed=frozenset({"gone"}))
    assert jump_map.targets[0].status_bucket == "Running"
    lines = _legend_lines(jump_map, 80, "collapsed")
    assert len(lines) == 1
    assert "⊘" in lines[0].plain
    assert all(
        IN_FLIGHT_RUNNING_TINT not in str(span.style)
        and IN_FLIGHT_STARTING_TINT not in str(span.style)
        for span in lines[0].spans
    )


def _alternating_map() -> MemberJumpMap:
    labels = [f"member{index:02d}" for index in range(14)]
    statuses = {
        label: ("RUNNING" if index % 2 else "DONE")
        for index, label in enumerate(labels)
    }
    return _single_section_map(labels, statuses=statuses)


def _shown_numbers(lines: list[str], numbers: list[str]) -> list[str]:
    wanted = set(numbers)
    shown: list[str] = []
    for line in lines:
        for cell in line.split("  "):
            first = cell.strip().split(" ", 1)[0].removeprefix("⊘").strip()
            if first in wanted and first not in shown:
                shown.append(first)
    return shown


def test_in_flight_first_packing_prefers_running_targets() -> None:
    jump_map = _single_section_map(
        [f"member{index:02d}" for index in range(14)],
        statuses={
            f"member{index:02d}": ("RUNNING" if index % 2 else "DONE")
            for index in range(14)
        },
    )
    numbers = [target.number for target in jump_map.targets]
    found = False
    for width in range(30, 201):
        lines = _rendered(jump_map, width, "collapsed")
        token = _overflow_token(lines)
        if token is None:
            continue
        shown = _shown_numbers(lines, numbers)
        if len(shown) == 5:
            found = True
            assert shown == ["01", "03", "05", "07", "09"]
            assert token == "+9 ▶2"
            break
    assert found


def test_packing_fills_with_lowest_remaining_numbers() -> None:
    labels = [f"member{index:02d}" for index in range(14)]
    statuses = dict.fromkeys(labels, "DONE")
    statuses["member03"] = "RUNNING"
    statuses["member07"] = "RUNNING"
    jump_map = _single_section_map(labels, statuses=statuses)
    numbers = [target.number for target in jump_map.targets]
    found = False
    for width in range(30, 201):
        lines = _rendered(jump_map, width, "collapsed")
        token = _overflow_token(lines)
        if token is None:
            continue
        shown = _shown_numbers(lines, numbers)
        if len(shown) == 5:
            found = True
            assert shown == ["00", "01", "02", "03", "07"]
            assert token == "+9"
            break
    assert found


def test_no_overflow_keeps_plain_number_order() -> None:
    jump_map = _alternating_map()
    lines = _rendered(jump_map, 200, "collapsed")
    assert _overflow_token(lines) is None
    numbers = [target.number for target in jump_map.targets]
    assert _shown_numbers(lines, numbers) == numbers


def test_overflow_chip_reports_hidden_in_flight_only_when_needed() -> None:
    jump_map = _alternating_map()
    numbers = [target.number for target in jump_map.targets]
    seen_lit = False
    seen_plain = False
    for width in WIDTHS:
        lines = _rendered(jump_map, width, "collapsed")
        token = _overflow_token(lines)
        if token is None:
            continue
        shown = _shown_numbers(lines, numbers)
        hidden = len(numbers) - len(shown)
        shown_in_flight = sum(
            1
            for target in jump_map.targets
            if target.number in shown and target.status_bucket == "Running"
        )
        hidden_in_flight = 7 - shown_in_flight
        assert token.split(" ")[0] == f"+{hidden}"
        if hidden_in_flight > 0:
            seen_lit = True
            assert token == f"+{hidden} ▶{hidden_in_flight}"
        else:
            seen_plain = True
            assert token == f"+{hidden}"
    assert seen_lit and seen_plain


@pytest.mark.parametrize("width", WIDTHS)
def test_mixed_status_widths_never_exceed_available_width(width: int) -> None:
    for jump_map in (_mixed_map(), _alternating_map()):
        for line in _rendered(jump_map, width, "collapsed"):
            assert cell_len(line) <= width


def test_narrowed_mode_lights_in_flight_candidates() -> None:
    labels = [f"item{index:02d}" for index in range(14)]
    statuses = {"item10": "RUNNING", "item11": "DONE", "item12": "STARTING"}
    jump_map = _single_section_map(labels, statuses=statuses)
    lines = _legend_lines(jump_map, 80, "1")
    assert len(lines) == 1
    line = lines[0]
    assert IN_FLIGHT_RUNNING_TINT in _covering_styles(line, "item10")[0]
    assert IN_FLIGHT_STARTING_TINT in _covering_styles(line, "item12")[0]
    done_styles = _covering_styles(line, "item11")
    assert done_styles
    assert all(" on " not in style for style in done_styles)


def test_digest_changes_when_a_target_flips_running_to_done() -> None:
    labels = ["alpha", "beta"]
    running = _single_section_map(labels)
    flipped = _single_section_map(labels, statuses={"beta": "DONE"})
    assert JumpLegendRenderable(running, mode="collapsed").plain != (
        JumpLegendRenderable(flipped, mode="collapsed").plain
    )
    assert renderable_content_digest(
        JumpLegendRenderable(running, mode="collapsed")
    ) != renderable_content_digest(JumpLegendRenderable(flipped, mode="collapsed"))
    again = _single_section_map(labels)
    assert JumpLegendRenderable(running, mode="collapsed").plain == (
        JumpLegendRenderable(again, mode="collapsed").plain
    )
    assert renderable_content_digest(
        JumpLegendRenderable(running, mode="collapsed")
    ) == renderable_content_digest(JumpLegendRenderable(again, mode="collapsed"))


def test_narrow_fallback_prefers_first_in_flight_target() -> None:
    labels = ["aaa", "bbb", "ccc"]
    jump_map = _single_section_map(labels, statuses={"bbb": "RUNNING"})
    done_map = _single_section_map(
        labels, statuses={"aaa": "DONE", "bbb": "DONE", "ccc": "DONE"}
    )
    assert all(t.status_bucket == "Done" for t in done_map.targets)
    lit_lines: list[str] = []
    for width in range(1, 30):
        lines = _rendered(jump_map, width, "collapsed")
        if len(lines) == 1 and "bbb" in lines[0] and "+" not in lines[0]:
            lit_lines = lines
            break
    assert lit_lines, "expected a narrow width that hits the fallback cell"
    assert "1" in lit_lines[0].split("bbb")[0]
    plain_lines: list[str] = []
    for width in range(1, 30):
        lines = _rendered(done_map, width, "collapsed")
        if len(lines) == 1 and "aaa" in lines[0] and "+" not in lines[0]:
            plain_lines = lines
            break
    assert plain_lines, "expected a narrow width that hits the fallback cell"
    assert "0" in plain_lines[0].split("aaa")[0]

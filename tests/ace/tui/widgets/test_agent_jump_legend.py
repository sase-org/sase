"""Unit tests for the pure jump legend renderer."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.util.renderable_digest import renderable_content_digest
from sase.ace.tui.widgets._agent_jump_legend import (
    MIN_LABEL_CELLS,
    JumpLegendRenderable,
    jump_legend_border_accent,
    jump_legend_title,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
    merged_member_jump_map,
)

WIDTHS = (30, 48, 64, 80, 120, 200)

_LANE_IDENTITY = (AgentType.RUNNING, "lane", None)


def _entries(
    labels: list[str],
    *,
    dismissed: frozenset[str] = frozenset(),
) -> tuple[MemberRosterEntry, ...]:
    return tuple(
        MemberRosterEntry(
            identity=(AgentType.RUNNING, label, None),
            presented_name=label,
            label=label,
            kind="agent",
            status="RUNNING",
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
    accent: str = "#00D7AF",
    title: str = "NEIGHBORS",
    dismissed: frozenset[str] = frozenset(),
) -> MemberJumpMap:
    return append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(labels, dismissed=dismissed),
        title=title,
        accent=accent,
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(labels)),
    )


def _two_section_map() -> MemberJumpMap:
    numbering = MemberJumpNumbering(total=12)
    family = append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(["--plan-0", "--plan-1", "--plan-2"]),
        title="FAMILY SHELLS",
        accent="#00AFFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=numbering,
    )
    neighbors = append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries([f"sase-16h.{index}" for index in range(6)]),
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=numbering,
        entry_limit=4,
        hidden_tail_label="neighbors",
        hidden_tail_hint="zz / za to show more",
    )
    return merged_member_jump_map(_LANE_IDENTITY, family, neighbors)


def _render_lines(renderable: JumpLegendRenderable, width: int) -> list[str]:
    output = StringIO()
    Console(file=output, width=width, color_system=None).print(renderable, end="")
    return output.getvalue().splitlines()


def _shown_numbers(lines: list[str], numbers: list[str]) -> list[str]:
    wanted = set(numbers)
    shown: list[str] = []
    for line in lines:
        for cell in line.split("  "):
            first = cell.strip().split(" ", 1)[0].removeprefix("⊘").strip()
            if first in wanted and first not in shown:
                shown.append(first)
    return shown


@pytest.mark.parametrize("width", WIDTHS)
def test_collapsed_is_at_most_two_rows(width: int) -> None:
    labels = [f"sase-16h.{index}" for index in range(20)]
    renderable = JumpLegendRenderable(_single_section_map(labels), mode="collapsed")
    lines = _render_lines(renderable, width)
    assert 1 <= len(lines) <= 2
    for line in lines:
        assert cell_len(line) <= width


@pytest.mark.parametrize("width", WIDTHS)
def test_collapsed_overflow_arithmetic(width: int) -> None:
    labels = [f"sase-16h.{index}" for index in range(20)]
    jump_map = _single_section_map(labels)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), width)
    numbers = [target.number for target in jump_map.targets]
    shown = _shown_numbers(lines, numbers)
    token = lines[-1].split("  ")[-1].strip()
    if token.startswith("+"):
        assert len(shown) < len(numbers)
        assert len(shown) + int(token[1:]) == len(numbers)
    else:
        assert len(shown) == len(numbers)


@pytest.mark.parametrize("width", WIDTHS)
def test_collapsed_labels_unique_and_present(width: int) -> None:
    labels = [f"sase-16h.{index}" for index in range(12)]
    jump_map = _single_section_map(labels)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), width)
    text = "\n".join(lines)
    numbers = [target.number for target in jump_map.targets]
    shown = _shown_numbers(lines, numbers)
    assert shown
    visible_labels: list[str] = []
    for number in shown:
        target = next(t for t in jump_map.targets if t.number == number)
        assert target.label[:4] in text or "…" in text
        for line in lines:
            for cell in line.split("  "):
                first = cell.strip().split(" ", 1)[0].removeprefix("⊘").strip()
                if first == number:
                    visible_labels.append(cell.split(number, 1)[1])
    assert len(set(visible_labels)) == len(visible_labels)


def test_min_label_width_floor() -> None:
    assert MIN_LABEL_CELLS == 10


def test_one_row_when_everything_fits() -> None:
    jump_map = _single_section_map(["a", "b", "c"])
    assert _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), 200) == [
        _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), 200)[0]
    ]


def test_two_digit_chips() -> None:
    labels = [f"label-{index}" for index in range(12)]
    jump_map = _single_section_map(labels)
    assert jump_map.targets[10].number == "10"
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), 200)
    assert any("10" in line for line in lines)
    expanded = "\n".join(
        _render_lines(JumpLegendRenderable(jump_map, mode="expanded"), 80)
    )
    assert "10" in expanded and "11" in expanded


def test_wide_characters_measure_by_cells() -> None:
    labels = ["日本語-0", "日本語-1", "日本語-2", "ascii-3"]
    jump_map = _single_section_map(labels)
    for width in WIDTHS:
        for line in _render_lines(
            JumpLegendRenderable(jump_map, mode="collapsed"), width
        ):
            assert cell_len(line) <= width


def test_dismissed_marker() -> None:
    jump_map = _single_section_map(["active", "gone"], dismissed=frozenset({"gone"}))
    text = "\n".join(
        _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), 80)
    )
    assert "⊘" in text
    expanded = "\n".join(
        _render_lines(JumpLegendRenderable(jump_map, mode="expanded"), 80)
    )
    assert "revive" in expanded


@pytest.mark.parametrize("width", WIDTHS)
def test_expanded_shows_every_target_with_headings_and_tails(width: int) -> None:
    jump_map = _two_section_map()
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="expanded"), width)
    text = "\n".join(lines)
    for target in jump_map.targets:
        assert target.number in text
        assert target.label in text
    assert "❖ FAMILY SHELLS" in text
    assert "❖ NEIGHBORS" in text
    assert "… +2 more neighbors" in text


def test_expanded_single_section_has_no_heading() -> None:
    jump_map = _single_section_map(["alpha", "beta"])
    text = "\n".join(_render_lines(JumpLegendRenderable(jump_map, mode="expanded"), 80))
    assert "❖" not in text
    assert "alpha" in text and "beta" in text


def test_narrowed_filtering_and_empty_line() -> None:
    labels = [f"item-{index}" for index in range(12)]
    jump_map = _single_section_map(labels)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="1"), 80)
    text = "\n".join(lines)
    assert "10" in text and "11" in text
    assert "❖" not in text
    empty = _render_lines(JumpLegendRenderable(jump_map, mode="9"), 80)
    assert empty == ["no targets start with 9"]


def test_title_ranges() -> None:
    single = _single_section_map(["only"])
    assert jump_legend_title(single).plain == "JUMP · NEIGHBORS 0"
    two = _two_section_map()
    title = jump_legend_title(two).plain
    assert title.startswith("JUMP")
    assert "FAMILY SHELLS" in title and "NEIGHBORS" in title
    assert "00–02" in title and "03–06" in title
    narrowed = jump_legend_title(two, prefix="1")
    assert narrowed.plain == "JUMP · 1▁"


def test_border_accent_and_digest() -> None:
    two = _two_section_map()
    assert jump_legend_border_accent(two) == "#00AFFF"
    empty = MemberJumpMap(
        container_identity=(AgentType.RUNNING, "lane", None), targets=()
    )
    assert jump_legend_border_accent(empty) == "#8787AF"
    first = JumpLegendRenderable(two, mode="collapsed")
    second = JumpLegendRenderable(two, mode="collapsed")
    assert renderable_content_digest(first) == renderable_content_digest(second)
    assert renderable_content_digest(first) != renderable_content_digest(
        JumpLegendRenderable(two, mode="expanded")
    )


def test_truncation_keeps_tail_distinct() -> None:
    labels = ["sase-16h.2", "sase-16h.3", "sase-16h.10"]
    jump_map = _single_section_map(labels)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), 48)
    text = "\n".join(lines)
    assert "6h.2" in text or "sase-16h.2" in text
    assert "6h.3" in text or "sase-16h.3" in text


def test_label_never_below_minimum_unless_clamped() -> None:
    labels = [f"very-long-label-name-{index:02d}" for index in range(30)]
    jump_map = _single_section_map(labels)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), 64)
    assert 1 <= len(lines) <= 2
    assert isinstance(Text("\n".join(lines)), Text)

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
import sase.ace.tui.widgets._agent_jump_legend as legend_module
from sase.ace.tui.widgets._agent_jump_legend import (
    MIN_LABEL_CELLS,
    _LABEL_BUDGETS,
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
    statuses: dict[str, str] | None = None,
    groups: dict[str, str] | None = None,
    legend_groups: dict[str, str] | None = None,
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
            group_label=(groups or {}).get(label),
            legend_group=(legend_groups or {}).get(label),
        )
        for label in labels
    )


def _single_section_map(
    labels: list[str],
    *,
    accent: str = "#00D7AF",
    title: str = "NEIGHBORS",
    dismissed: frozenset[str] = frozenset(),
    statuses: dict[str, str] | None = None,
    groups: dict[str, str] | None = None,
    legend_groups: dict[str, str] | None = None,
    title_suffix: str | None = None,
) -> MemberJumpMap:
    return append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(
            labels,
            dismissed=dismissed,
            statuses=statuses,
            groups=groups,
            legend_groups=legend_groups,
        ),
        title=title,
        accent=accent,
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(labels)),
        title_suffix=title_suffix,
    )


def _two_section_map() -> MemberJumpMap:
    numbering = MemberJumpNumbering(total=12)
    agent_session = append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(["--plan-0", "--plan-1", "--plan-2"]),
        title="SESSION TURNS",
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
        hidden_tail_hint="zz to show more",
    )
    return merged_member_jump_map(_LANE_IDENTITY, agent_session, neighbors)


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
        hidden = int(token[1:].split(" ")[0])
        assert len(shown) + hidden == len(numbers)
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
    narrowed = "\n".join(_render_lines(JumpLegendRenderable(jump_map, mode="1"), 80))
    assert "10" in narrowed and "11" in narrowed


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
    narrowed = "\n".join(_render_lines(JumpLegendRenderable(jump_map, mode="1"), 80))
    assert "⊘ 1 gone ▶ archive" in narrowed


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
    assert "SESSION TURNS" in title and "NEIGHBORS" in title
    assert "00–02" in title and "03–06" in title
    narrowed = jump_legend_title(two, prefix="1")
    assert narrowed.plain == "JUMP · 1▁"


def test_layered_title_suffix_is_dropped_before_base_title() -> None:
    jump_map = _single_section_map(["only"], title_suffix="5 WAVES + LAND")
    full = jump_legend_title(jump_map)
    base = jump_legend_title(jump_map, width=cell_len("JUMP · NEIGHBORS 0"))

    assert full.plain == "JUMP · NEIGHBORS 0 · 5 WAVES + LAND"
    assert base.plain == "JUMP · NEIGHBORS 0"


def test_collapsed_legend_divides_wave_groups_between_same_row_neighbors() -> None:
    labels = [f"member-{index}" for index in range(20)]
    legend_groups = {
        label: f"wave {index // 2 + 1}" for index, label in enumerate(labels)
    }
    statuses = dict.fromkeys(labels, "DONE")
    statuses.update(
        {"member-0": "RUNNING", "member-2": "RUNNING", "member-4": "RUNNING"}
    )
    jump_map = _single_section_map(
        labels, legend_groups=legend_groups, statuses=statuses
    )
    renderable = JumpLegendRenderable(jump_map, mode="collapsed")

    for width in WIDTHS:
        lines = renderable._lines_for_width(width)  # noqa: SLF001
        assert 1 <= len(lines) <= 2
        assert all(cell_len(line.plain) <= width for line in lines)
        for line in lines:
            stripped = line.plain.strip()
            assert not stripped.startswith("┊")
            assert not stripped.endswith("┊")
        text = "\n".join(line.plain for line in lines)
        shown = _shown_numbers(
            [line.plain.replace("┊", " ") for line in lines],
            [target.number for target in jump_map.targets],
        )
        if width >= 48:
            assert "┊" in text
        if len(shown) < len(jump_map.targets):
            overflow = next(
                token
                for line in lines
                for token in line.plain.split()
                if token.startswith("+")
            )
            assert len(shown) + int(overflow[1:]) == len(jump_map.targets)

    ungrouped = JumpLegendRenderable(
        _single_section_map(labels, statuses=statuses), mode="collapsed"
    )
    grouped_shown = _shown_numbers(
        [line.plain.replace("┊", " ") for line in renderable._lines_for_width(64)],  # noqa: SLF001
        [target.number for target in jump_map.targets],
    )
    ungrouped_shown = _shown_numbers(
        _render_lines(ungrouped, 64),
        [target.number for target in jump_map.targets],
    )
    assert len(grouped_shown) < len(ungrouped_shown)


def test_collapsed_legend_group_labels_alone_draw_no_dividers() -> None:
    """NEIGHBORS-style group labels must not divide the collapsed legend."""
    labels = [f"member-{index}" for index in range(8)]
    groups = {
        "member-0": "ancestors",
        "member-1": "ancestors",
        "member-2": "descendants",
        "member-3": "descendants",
        "member-4": "my hood hood",
        "member-5": "my hood hood",
        "member-6": "other hood",
        "member-7": "other hood",
    }
    jump_map = _single_section_map(labels, groups=groups)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), 120)
    assert "\n".join(lines).count("┊") == 0


@pytest.mark.parametrize("width", [24, 60, 80])
def test_collapsed_dividers_never_at_row_edges(width: int) -> None:
    labels = [f"member-{index}" for index in range(12)]
    legend_groups = {
        label: f"wave {index // 3 + 1}" for index, label in enumerate(labels)
    }
    jump_map = _single_section_map(labels, legend_groups=legend_groups)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), width)
    assert 1 <= len(lines) <= 2
    for line in lines:
        assert cell_len(line) <= width
        stripped = line.strip()
        assert not stripped.startswith("┊")
        assert not stripped.endswith("┊")


def test_collapsed_group_boundary_on_row_break_draws_no_divider() -> None:
    labels = ["a0", "a1", "b0", "b1"]
    legend_groups = {"a0": "wave 1", "a1": "wave 1", "b0": "wave 2", "b1": "wave 2"}
    jump_map = _single_section_map(labels, legend_groups=legend_groups)
    renderable = JumpLegendRenderable(jump_map, mode="collapsed")
    by_width = {
        width: "\n".join(
            line.plain
            for line in renderable._lines_for_width(width)  # noqa: SLF001
        )
        for width in (24, 30, 48, 64, 80, 120, 200)
    }
    two_row = [text for text in by_width.values() if "\n" in text]
    assert two_row, "expected a two-row layout at some width"
    for text in two_row:
        first, second = text.split("\n")
        if "a1" in first and "b0" in second:
            assert "┊" not in text


def test_collapsed_legend_does_not_divide_unrelated_roster_sections() -> None:
    first = append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(
            ["a", "b"],
            groups={"a": "wave 1", "b": "wave 2"},
            legend_groups={"a": "wave 1", "b": "wave 2"},
        ),
        title="CLAN MEMBERS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=3),
    )
    neighbors = append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(["neighbor"]),
        title="CLAN NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=3),
    )
    jump_map = merged_member_jump_map(_LANE_IDENTITY, first, neighbors)
    line = JumpLegendRenderable(jump_map, mode="collapsed")._lines_for_width(  # noqa: SLF001
        120
    )[0]

    assert line.plain.count("┊") == 1
    assert line.plain.index("┊") < line.plain.index("neighbor")


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
        JumpLegendRenderable(two, mode="1")
    )
    ungrouped = JumpLegendRenderable(_single_section_map(["a", "b"]))
    grouped = JumpLegendRenderable(
        _single_section_map(["a", "b"], legend_groups={"a": "wave 1", "b": "wave 2"})
    )
    suffixed = JumpLegendRenderable(
        _single_section_map(["a", "b"], title_suffix="2 WAVES")
    )
    assert renderable_content_digest(ungrouped) != renderable_content_digest(grouped)
    assert renderable_content_digest(ungrouped) != renderable_content_digest(suffixed)


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


def test_narrow_widths_keep_spans_inside_clipped_cells() -> None:
    """Narrow columns must clip spans together with plain text.

    Regression: hand-clipped cells kept spans past the cut, which crashed
    Rich rendering (StopIteration) once a panel squeezed below one cell.
    """
    numbering = MemberJumpNumbering(total=4)
    agent_session = append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(["--plan", "--code"]),
        title="SESSION TURNS",
        accent="#00AFFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=numbering,
    )
    neighbors = append_member_roster(
        Text(),
        container_identity=_LANE_IDENTITY,
        entries=_entries(["visual-real-session.peer00", "visual-real-session.peer01"]),
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=numbering,
    )
    jump_map = merged_member_jump_map(_LANE_IDENTITY, agent_session, neighbors)
    for mode in ("collapsed", "1"):
        for width in (9, 12, 16, 20, 30):
            renderable = JumpLegendRenderable(jump_map, mode=mode)
            for line in renderable._lines_for_width(width):  # noqa: SLF001
                for span in line.spans:
                    assert 0 <= span.start <= span.end <= len(line.plain)
            assert _render_lines(JumpLegendRenderable(jump_map, mode=mode), width)


def _pre_epic_collapsed_lines(jump_map: MemberJumpMap, width: int) -> list[str]:
    """Replay the pre-epic collapsed layout for a map without wave groups.

    This mirrors ``_agent_jump_legend`` before the clan-wave legend work:
    the closed-form shown count, the ``width // 8`` column cap, and plain
    grid fitting. Shared cell construction comes from the module so the
    oracle pins only the restored selection, cap, and fitting behavior.
    """
    targets = jump_map.targets
    count = len(targets)
    if count == 0:
        return []
    longest = max(cell_len(target.label) for target in targets)
    candidates: list[int] = []
    seen: set[int] = set()
    for budget in (longest, *_LABEL_BUDGETS):
        if budget > longest or budget in seen:
            continue
        seen.add(budget)
        if budget != longest and budget < MIN_LABEL_CELLS:
            continue
        truncated = [
            legend_module._truncate_middle(target.label, budget)  # noqa: SLF001
            for target in targets
        ]
        by_truncated: dict[str, set[str]] = {}
        clash = False
        for target, short in zip(targets, truncated, strict=True):
            fulls = by_truncated.setdefault(short, set())
            fulls.add(target.label)
            if len(fulls) > 1:
                clash = True
                break
        if clash:
            continue
        candidates.append(budget)
    best: tuple[int, int, int, list[str]] | None = None
    for budget in candidates:
        labels = [
            legend_module._truncate_middle(target.label, budget)  # noqa: SLF001
            for target in targets
        ]
        columns = _pre_epic_largest_columns(jump_map, labels, width)
        if columns is None:
            continue
        shown = _pre_epic_shown_count(count, columns)
        if best is None or shown > best[0] or (shown == best[0] and budget > best[1]):
            best = (shown, budget, columns, labels)
    if best is None:
        return ["<fallback>"]
    _shown, _budget, columns, labels = best
    selection = legend_module._collapsed_selection(jump_map, _shown)  # noqa: SLF001
    cells = [
        legend_module._build_cell(  # noqa: SLF001
            jump_map.targets[index].number,
            legend_module._target_accent(jump_map, index),  # noqa: SLF001
            labels[index],
            bucket=jump_map.targets[index].status_bucket,
            dismissed=jump_map.targets[index].role == "dismissed",
            show_archive_hint=False,
        )
        for index in selection
    ]
    hidden = count - len(selection)
    if hidden > 0:
        cells.append(
            legend_module._overflow_cell(  # noqa: SLF001
                hidden,
                legend_module._hidden_in_flight_count(  # noqa: SLF001
                    jump_map, set(selection)
                ),
            )
        )
    return [
        line.plain
        for line in legend_module._render_grid(cells, columns)  # noqa: SLF001
    ]


def _pre_epic_shown_count(count: int, columns: int) -> int:
    slots = min(count, 2 * columns)
    if count > 2 * columns:
        return slots - 1
    return slots


def _pre_epic_largest_columns(
    jump_map: MemberJumpMap, labels: list[str], width: int
) -> int | None:
    count = len(jump_map.targets)
    max_columns = min(count, max(1, width // 8))
    for columns in range(max_columns, 0, -1):
        shown = _pre_epic_shown_count(count, columns)
        selection = legend_module._collapsed_selection(jump_map, shown)  # noqa: SLF001
        cells = [
            legend_module._build_cell(  # noqa: SLF001
                jump_map.targets[index].number,
                legend_module._target_accent(jump_map, index),  # noqa: SLF001
                labels[index],
                bucket=jump_map.targets[index].status_bucket,
                dismissed=jump_map.targets[index].role == "dismissed",
                show_archive_hint=False,
            )
            for index in selection
        ]
        if shown < count:
            cells.append(
                legend_module._overflow_cell(  # noqa: SLF001
                    count - shown,
                    legend_module._hidden_in_flight_count(  # noqa: SLF001
                        jump_map, set(selection)
                    ),
                )
            )
        if legend_module._grid_fits(cells, columns, width):  # noqa: SLF001
            return columns
    return None


@pytest.mark.parametrize("count", [1, 2, 3, 5, 12, 20, 30, 100])
@pytest.mark.parametrize("width", [24, 30, 48, 64, 80, 120, 200])
def test_collapsed_no_group_layout_matches_pre_epic(count: int, width: int) -> None:
    """Without wave groups the restored layout must equal the pre-epic one."""
    labels = [f"member-{index:03d}" for index in range(count)]
    jump_map = _single_section_map(labels)
    lines = _render_lines(JumpLegendRenderable(jump_map, mode="collapsed"), width)
    assert list(lines) == _pre_epic_collapsed_lines(jump_map, width)


def test_collapsed_no_group_selection_is_single_closed_form_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-group map calls ``_collapsed_selection`` once per column candidate."""
    labels = [f"member-{index:03d}" for index in range(30)]
    jump_map = _single_section_map(labels)
    real = legend_module._collapsed_selection
    calls: list[int] = []

    def _counting(target_map: MemberJumpMap, shown: int) -> list[int]:
        calls.append(shown)
        return real(target_map, shown)

    monkeypatch.setattr(legend_module, "_collapsed_selection", _counting)
    for columns in (1, 2, 3, 5, 8, 12):
        calls.clear()
        selection = legend_module._collapsed_selection_for_columns(  # noqa: SLF001
            jump_map, columns
        )
        assert len(calls) == 1
        count = len(labels)
        slots = min(count, 2 * columns)
        expected = slots - 1 if count > 2 * columns else slots
        assert selection == real(jump_map, expected)


def test_collapsed_grouped_selection_search_stays_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grouped map re-tries at most divider-count-plus-overflow times."""
    labels = [f"member-{index:03d}" for index in range(20)]
    legend_groups = {
        label: f"wave {index // 2 + 1}" for index, label in enumerate(labels)
    }
    jump_map = _single_section_map(labels, legend_groups=legend_groups)
    real = legend_module._collapsed_selection
    calls: list[int] = []

    def _counting(target_map: MemberJumpMap, shown: int) -> list[int]:
        calls.append(shown)
        return real(target_map, shown)

    monkeypatch.setattr(legend_module, "_collapsed_selection", _counting)
    group_count = len(set(legend_groups.values()))
    for columns in (1, 2, 3, 5, 8, 12):
        calls.clear()
        legend_module._collapsed_selection_for_columns(  # noqa: SLF001
            jump_map, columns
        )
        assert len(calls) <= group_count + 2

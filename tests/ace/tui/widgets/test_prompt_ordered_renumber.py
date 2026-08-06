"""Ordered-run scanning, Prettier-compatible renumbering, and edit planning."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._paired_text_editing import TextEdit
from sase.ace.tui.widgets._prompt_ordered_editing import (
    MAX_ORDERED_RUN_ITEMS,
    find_ordered_run,
    plan_ordered_list_edit,
    _prompt_ordered_sibling_prefix,
    _renumber_ordered_runs,
)


def _renumber(lines: list[str], *anchor_rows: int) -> list[str]:
    return _renumber_ordered_runs(lines, anchor_rows or (0,)).lines


# --------------------------------------------------------------------------
# Run scanning
# --------------------------------------------------------------------------


def test_run_collects_consecutive_siblings() -> None:
    run = find_ordered_run(["1. one", "2. two", "3. three"], 1)

    assert run is not None
    assert [item.row for item in run.items] == [0, 1, 2]
    assert run.oversized is False


def test_run_spans_blank_lines_in_a_loose_list() -> None:
    run = find_ordered_run(["1. one", "", "2. two", "", "3. three"], 0)

    assert run is not None
    assert [item.row for item in run.items] == [0, 2, 4]


def test_run_spans_owned_continuation_lines() -> None:
    lines = ["1. one", "   wrapped", "2. two"]

    run = find_ordered_run(lines, 0)

    assert run is not None
    assert [item.row for item in run.items] == [0, 2]


def test_run_stops_at_prose_at_the_run_indent() -> None:
    run = find_ordered_run(["1. one", "prose", "4. two"], 0)

    assert run is not None
    assert [item.row for item in run.items] == [0]


def test_run_stops_at_a_delimiter_change() -> None:
    run = find_ordered_run(["1. one", "2) two"], 0)

    assert run is not None
    assert [item.row for item in run.items] == [0]


def test_run_skips_nested_items() -> None:
    lines = ["1. one", "   1. nested", "   2. nested", "2. two"]

    run = find_ordered_run(lines, 0)

    assert run is not None
    assert [item.row for item in run.items] == [0, 3]


def test_nested_run_is_its_own_run() -> None:
    lines = ["1. one", "   1. nested", "   2. nested", "2. two"]

    run = find_ordered_run(lines, 1)

    assert run is not None
    assert [item.row for item in run.items] == [1, 2]


def test_run_is_none_off_a_list() -> None:
    assert find_ordered_run(["prose"], 0) is None
    assert find_ordered_run(["1. one"], 5) is None


# --------------------------------------------------------------------------
# Style detection and renumbering
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["1. a", "3. b", "7. c"], ["1. a", "2. b", "3. c"]),
        (["5. a", "6. b", "7. c"], ["5. a", "6. b", "7. c"]),
        (["1. a", "1. b", "1. c"], ["1. a", "1. b", "1. c"]),
        (["1. a", "1. b", "5. c"], ["1. a", "1. b", "1. c"]),
        (["9. a", "1. b", "5. c"], ["9. a", "1. b", "1. c"]),
        (["0. a", "1. b", "1. c"], ["0. a", "1. b", "1. c"]),
        (["0. a", "1. b", "4. c"], ["0. a", "1. b", "2. c"]),
        (["3. a"], ["3. a"]),
        (["1) a", "9) b"], ["1) a", "2) b"]),
        (["007. a", "2. b"], ["7. a", "8. b"]),
    ],
    ids=[
        "sequential-gaps",
        "sequential-start-preserved",
        "repeat-style",
        "repeat-style-wins",
        "repeat-style-keeps-first-number",
        "zero-start-repeat-style",
        "zero-start-sequential",
        "single-item",
        "paren-delimiter",
        "leading-zeros-normalized",
    ],
)
def test_renumber_matches_prettier_style_rules(
    lines: list[str],
    expected: list[str],
) -> None:
    assert _renumber(lines) == expected


def test_renumber_spans_blank_lines() -> None:
    assert _renumber(["1. a", "", "4. b", "", "9. c"]) == [
        "1. a",
        "",
        "2. b",
        "",
        "3. c",
    ]


def test_renumber_leaves_a_prose_split_run_alone() -> None:
    assert _renumber(["1. a", "prose", "4. b"]) == ["1. a", "prose", "4. b"]


def test_renumber_leaves_nested_runs_alone() -> None:
    lines = ["1. a", "   1. n", "   5. n", "4. b"]

    assert _renumber(lines) == ["1. a", "   1. n", "   5. n", "2. b"]


def test_renumber_only_touches_the_anchored_run() -> None:
    lines = ["1. a", "5. b", "", "prose", "", "1. x", "9. y"]

    assert _renumber(lines, 0) == ["1. a", "2. b", "", "prose", "", "1. x", "9. y"]


def test_renumber_is_scoped_by_delimiter() -> None:
    assert _renumber(["1. a", "2. b", "7) c"]) == ["1. a", "2. b", "7) c"]


def test_renumber_shifts_owned_blocks_when_a_marker_grows() -> None:
    lines = ["9. a", "2. b", "     wrapped", "1. c"]

    assert _renumber(lines) == ["9. a", "10. b", "      wrapped", "11. c"]


def test_renumber_shifts_owned_blocks_when_a_marker_shrinks() -> None:
    lines = ["1. a", "10. b", "    wrapped"]

    assert _renumber(lines) == ["1. a", "2. b", "   wrapped"]


def test_renumber_shrink_only_removes_spaces_that_exist() -> None:
    lines = ["1. a", "100. b", "  wrapped by hand"]

    # The under-indented line is not owned, so it is left untouched.
    assert _renumber(lines) == ["1. a", "2. b", "  wrapped by hand"]


def test_renumber_reports_column_shifts_for_the_cursor() -> None:
    result = _renumber_ordered_runs(["9. a", "2. b"], (0,))

    assert result.lines == ["9. a", "10. b"]
    assert result.adjust_column(1, 3) == 4
    assert result.adjust_column(1, 0) == 0
    assert result.adjust_column(0, 3) == 3


def test_renumber_handles_two_anchors_in_different_runs() -> None:
    lines = ["1. a", "5. b", "", "prose", "", "1. x", "9. y"]

    assert _renumber(lines, 0, 6) == [
        "1. a",
        "2. b",
        "",
        "prose",
        "",
        "1. x",
        "2. y",
    ]


def test_renumber_degrades_silently_on_an_oversized_run() -> None:
    lines = [f"{index + 1}. item" for index in range(MAX_ORDERED_RUN_ITEMS + 5)]
    lines[10] = "99. item"

    assert _renumber(lines) == lines


def test_renumber_is_a_no_op_off_a_list() -> None:
    assert _renumber(["prose", "more prose"]) == ["prose", "more prose"]


# --------------------------------------------------------------------------
# The inserted-number rule
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lines", "row", "increment", "expected"),
    [
        (["1. a", "2. b"], 1, True, "3. "),
        (["1. a", "2. b"], 0, True, "2. "),
        (["1. a", "2. b"], 0, False, "1. "),
        (["1. a", "1. b"], 1, True, "1. "),
        (["1. a", "1. b"], 1, False, "1. "),
        (["9. a", "1. b"], 1, True, "1. "),
        (["9. a", "1. b"], 0, False, "9. "),
        (["5. a"], 0, True, "6. "),
        (["1. a", "7. b"], 1, True, "3. "),
        (["  3) a"], 0, True, "  4) "),
        (["1. a", "   wrapped"], 1, True, "2. "),
        (["prose"], 0, True, None),
    ],
    ids=[
        "after-last",
        "after-first",
        "before-first",
        "repeat-style",
        "repeat-style-above",
        "repeat-style-after-first",
        "repeat-style-before-first",
        "single-item",
        "normalized-before-increment",
        "indent-and-delimiter-copied",
        "continuation-line",
        "not-a-list",
    ],
)
def test_prompt_ordered_sibling_prefix(
    lines: list[str],
    row: int,
    increment: bool,
    expected: str | None,
) -> None:
    assert _prompt_ordered_sibling_prefix(lines, row, increment=increment) == expected


# --------------------------------------------------------------------------
# Single-edit planning
# --------------------------------------------------------------------------


def _apply(text: str, plan: TextEdit) -> str:
    return text[: plan.start] + plan.text + text[plan.end :]


def _plan(
    text: str, new_lines: list[str], row: int = 0, col: int = 0
) -> TextEdit | None:
    """Plan a structural edit with no run anchored, i.e. the diff step alone."""
    return plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(),
        cursor_row=row,
        cursor_col=col,
    )


def test_plan_returns_none_without_changes() -> None:
    assert _plan("1. a\n2. b", ["1. a", "2. b"]) is None


@pytest.mark.parametrize(
    ("text", "new_lines"),
    [
        ("a\nb", ["a", "x", "b"]),
        ("a", ["a", "x"]),
        ("a\nb", ["x", "a", "b"]),
        ("a\nb\nc", ["a", "c"]),
        ("a\nb\nc", ["a", "B", "c"]),
    ],
    ids=["insert-middle", "append", "prepend", "delete", "replace"],
)
def test_plan_rebuilds_the_document(
    text: str,
    new_lines: list[str],
) -> None:
    plan = _plan(text, new_lines)

    assert plan is not None
    assert _apply(text, plan) == "\n".join(new_lines)


def test_plan_spans_only_the_changed_rows() -> None:
    plan = _plan("1. a\n2. b\n3. c", ["1. a", "2. B", "3. c"], 1, 3)

    assert plan is not None
    assert plan.text == "2. B"
    assert plan.start == len("1. a\n")
    assert plan.end == len("1. a\n2. b")


def test_plan_ordered_list_edit_renumbers_in_one_edit() -> None:
    text = "1. a\n2. b"
    new_lines = ["1. a", "2. ", "2. b"]

    plan = plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(1,),
        cursor_row=1,
        cursor_col=3,
    )

    assert plan is not None
    assert _apply(text, plan) == "1. a\n2. \n3. b"
    assert plan.cursor == len("1. a\n2. ")


def test_plan_ordered_list_edit_style_override_beats_a_duplicated_number() -> None:
    text = "1. a\n2. b"
    # An item opened *above* the run's first one duplicates its number, which
    # reads exactly like Prettier's ``1. / 1.`` repeat convention.
    new_lines = ["1. ", "1. a", "2. b"]

    plan = plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(0,),
        cursor_row=0,
        cursor_col=3,
        style_override=False,
    )

    assert plan is not None
    assert _apply(text, plan) == "1. \n2. a\n3. b"


def test_plan_ordered_list_edit_style_override_can_force_repeat_style() -> None:
    text = "1. a\n1. b"
    new_lines = ["1. ", "1. a", "1. b"]

    plan = plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(0,),
        cursor_row=0,
        cursor_col=3,
        style_override=True,
    )

    assert plan is not None
    assert _apply(text, plan) == "1. \n1. a\n1. b"


def test_plan_ordered_list_edit_tracks_the_cursor_across_a_width_change() -> None:
    text = "9. a\n10. b"
    # A sibling grown below item one, before renumbering widens its marker.
    new_lines = ["9. a", "9. ", "10. b"]

    plan = plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(1,),
        cursor_row=1,
        cursor_col=3,
    )

    assert plan is not None
    assert _apply(text, plan) == "9. a\n10. \n11. b"
    assert plan.cursor == len("9. a\n10. ")


def test_plan_ordered_list_edit_still_edits_when_renumbering_is_skipped() -> None:
    lines = [f"{index + 1}. item" for index in range(MAX_ORDERED_RUN_ITEMS + 5)]
    lines[10] = "99. item"
    text = "\n".join(lines)
    new_lines = [*lines[:11], "1. ", *lines[11:]]

    plan = plan_ordered_list_edit(
        text,
        new_lines,
        anchor_rows=(11,),
        cursor_row=11,
        cursor_col=3,
    )

    assert plan is not None
    assert _apply(text, plan) == "\n".join(new_lines)

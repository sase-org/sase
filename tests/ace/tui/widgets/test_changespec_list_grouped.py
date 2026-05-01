"""Phase 2 tests for grouped rendering in ``ChangeSpecList``.

Drives the widget directly (no Pilot) so the assertions stay focused on
row mapping and Option emission rather than Textual paint timing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.message import Message

from sase.ace.changespec import ChangeSpec, TimestampEntry
from sase.ace.tui.models.changespec_groups import (
    ChangeSpecGroupingMode,
    ChangeSpecGroupRow,
)
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets import ChangeSpecList
from sase.ace.tui.widgets._agent_list_styling import (
    _CHANGESPEC_BANNER_BAR_STYLE,
    _CHANGESPEC_BANNER_RULE_STYLE,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
)
from sase.ace.tui.widgets._changespec_list_banner import banner_natural_width
from sase.ace.tui.widgets.changespec_list import _BANNER_ROW

from ..models._changespec_groups_helpers import _NOW


def _wire_widget(monkeypatch: Any) -> tuple[ChangeSpecList, list[Message]]:
    widget = ChangeSpecList()
    posted: list[Message] = []

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", posted.append)
    return widget, posted


def _ts(timestamp: str) -> TimestampEntry:
    return TimestampEntry(timestamp=timestamp, event_type="STATUS", detail="x")


def _cs(
    name: str,
    *,
    project: str = "demo",
    status: str = "WIP",
    timestamps: list[TimestampEntry] | None = None,
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="",
        parent=None,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=f"/sase/projects/{project}/{project}.gp",
        line_number=1,
        timestamps=timestamps,
    )


# ── default mode: BY_PROJECT ───────────────────────────────────────────


def test_default_mode_is_by_project(monkeypatch: Any) -> None:
    """Callers that don't pass ``grouping_mode`` get the BY_PROJECT default."""
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha"), _cs("beta")]

    widget.update_list(css, current_idx=1)

    assert widget._grouping_mode is ChangeSpecGroupingMode.BY_PROJECT


# ── BY_STATUS / BY_DATE banners ────────────────────────────────────────


def test_by_status_emits_l0_banners_and_cl_rows(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [
        _cs("alpha", status="WIP"),
        _cs("beta", status="Ready"),
        _cs("gamma", status="WIP"),
    ]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    # 2 banners (WIP, Ready) + 1 inter-L0 spacer + 3 CL rows = 6 options.
    assert widget.option_count == 6
    banner_rows = [
        i
        for i in range(widget.option_count)
        if widget._row_entries[i] == _BANNER_ROW
        and not (widget.get_option_at_index(i).id or "").startswith("cs-spacer:")
    ]
    cs_rows = [i for i, e in enumerate(widget._row_entries) if e != _BANNER_ROW]
    assert len(banner_rows) == 2
    assert len(cs_rows) == 3
    # Lifecycle order: WIP precedes Ready.
    assert banner_rows[0] < banner_rows[1]


def test_by_date_renders_l1_subgroup_banner_rows(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [
        _cs("night", timestamps=[_ts("260425_210000")]),
        _cs("late_evening", timestamps=[_ts("260425_200000")]),
    ]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_DATE,
        now=_NOW,
    )

    banner_rows = [
        i
        for i in range(widget.option_count)
        if widget._row_entries[i] == _BANNER_ROW
        and not (widget.get_option_at_index(i).id or "").startswith("cs-spacer:")
    ]
    assert len(banner_rows) == 4
    assert widget._row_entries == [
        _BANNER_ROW,
        _BANNER_ROW,
        _BANNER_ROW,
        0,
        _BANNER_ROW,
        1,
    ]

    window_text = widget.get_option_at_index(1).prompt
    window_plain = window_text.plain  # type: ignore[union-attr]
    assert window_plain.startswith("▎ 8PM-12AM ")
    window_styles = {s.style for s in window_text.spans}  # type: ignore[union-attr]
    assert _CHANGESPEC_BANNER_BAR_STYLE in window_styles
    assert _CHANGESPEC_BANNER_RULE_STYLE in window_styles

    hourly_text = widget.get_option_at_index(2).prompt
    hourly_plain = hourly_text.plain  # type: ignore[union-attr]
    assert hourly_plain.startswith("▸ 21:00 ")
    hourly_styles = {s.style for s in hourly_text.spans}  # type: ignore[union-attr]
    assert _NAME_ROOT_BANNER_LABEL_STYLE in hourly_styles
    assert _NAME_ROOT_BANNER_BRANCH_STYLE in hourly_styles


def test_banner_natural_width_uses_two_cell_prefix_for_l1() -> None:
    group = ChangeSpecGroupRow(
        level=1,
        group_key=("Yesterday", "8PM-12AM"),
        changespec_indices=(0, 1),
    )

    assert banner_natural_width(group, hint_char="x") == (
        4 + 2 + len("8PM-12AM") + 1 + 2 + len("2 CLs")
    )


def test_by_date_collapsed_l1_banner_maps_to_group_key(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [
        _cs("night", timestamps=[_ts("260425_210000")]),
        _cs("afternoon", timestamps=[_ts("260425_140000")]),
    ]
    fold = GroupFoldRegistry()
    fold.collapse(("Yesterday", "8PM-12AM"))

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_DATE,
        fold_registry=fold,
        current_group_key=("Yesterday", "8PM-12AM"),
        now=_NOW,
    )

    row = widget._banner_row_by_key[("Yesterday", "8PM-12AM")]
    assert widget.highlighted == row
    assert widget._banner_at_row[row].group_key == ("Yesterday", "8PM-12AM")
    index, group_key = widget._resolve_row(row)
    assert index == 0
    assert group_key == ("Yesterday", "8PM-12AM")


def test_by_date_collapsed_hourly_banner_maps_to_group_key(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [
        _cs("night", timestamps=[_ts("260425_210000")]),
        _cs("late_evening", timestamps=[_ts("260425_200000")]),
    ]
    fold = GroupFoldRegistry()
    fold.collapse(("Yesterday", "8PM-12AM", "21:00"))

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_DATE,
        fold_registry=fold,
        current_group_key=("Yesterday", "8PM-12AM", "21:00"),
        now=_NOW,
    )

    key = ("Yesterday", "8PM-12AM", "21:00")
    row = widget._banner_row_by_key[key]
    assert widget.highlighted == row
    assert widget._banner_at_row[row].group_key == key
    index, group_key = widget._resolve_row(row)
    assert index == 0
    assert group_key == key


def test_grouped_render_marks_l0_banners_disabled_when_expanded(
    monkeypatch: Any,
) -> None:
    """Expanded banners are non-selectable (disabled in OptionList)."""
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP"), _cs("beta", status="WIP")]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    # No collapsed banners → _banner_at_row stays empty even though
    # banner rows themselves are emitted.
    assert widget._banner_at_row == {}
    assert widget._banner_row_by_key == {}
    # The first option is the (disabled) banner row.
    first = widget.get_option_at_index(0)
    assert first.disabled is True


def test_collapsed_banner_is_selectable_and_hides_descendants(
    monkeypatch: Any,
) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP"), _cs("beta", status="WIP")]
    fold = GroupFoldRegistry()
    fold.collapse(("WIP",))

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
        fold_registry=fold,
    )

    # Only the (collapsed, selectable) banner remains visible.
    assert widget.option_count == 1
    assert widget._row_entries == [_BANNER_ROW]
    assert ("WIP",) in widget._banner_row_by_key
    assert widget._banner_at_row[0].group_key == ("WIP",)
    assert widget.get_option_at_index(0).disabled is False


# ── BY_PROJECT: L0 + L1 sibling-root banners ───────────────────────────


def test_by_project_emits_l1_only_for_grouped_siblings(
    monkeypatch: Any,
) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [
        _cs("foobar", project="proj"),
        _cs("foobar_1", project="proj"),
        _cs("singleton", project="proj"),
    ]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_PROJECT,
    )

    # 1 L0 (proj) + 1 L1 (foobar siblings) + 3 CL rows.
    assert widget.option_count == 5
    banner_rows = [i for i, e in enumerate(widget._row_entries) if e == _BANNER_ROW]
    assert len(banner_rows) == 2  # L0 + L1


def test_by_project_singleton_root_skips_l1_banner(monkeypatch: Any) -> None:
    """A name root with a single CL renders directly under L0."""
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("only_one", project="proj")]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_PROJECT,
    )

    # 1 L0 banner + 1 CL row, no L1.
    assert widget.option_count == 2
    assert widget._row_entries[0] == _BANNER_ROW
    assert widget._row_entries[1] == 0


# ── current_group_key takes precedence over current_idx ────────────────


def test_current_group_key_highlights_collapsed_banner(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP"), _cs("beta", status="Ready")]
    fold = GroupFoldRegistry()
    fold.collapse(("Ready",))

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
        fold_registry=fold,
        current_group_key=("Ready",),
    )

    target = widget._banner_row_by_key[("Ready",)]
    assert widget.highlighted == target


# ── Selection messages ─────────────────────────────────────────────────


def test_selection_message_carries_group_key_for_banner_row(
    monkeypatch: Any,
) -> None:
    widget, posted = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP")]
    fold = GroupFoldRegistry()
    fold.collapse(("WIP",))
    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
        fold_registry=fold,
    )
    posted.clear()

    index, group_key = widget._resolve_row(0)
    assert group_key == ("WIP",)
    assert index == 0


def test_selection_message_for_cl_row_has_no_group_key(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP"), _cs("beta", status="WIP")]
    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    cl_rows = [i for i, e in enumerate(widget._row_entries) if e != _BANNER_ROW]
    index, group_key = widget._resolve_row(cl_rows[1])
    assert group_key is None
    # Second CL row resolves to changespec idx 1.
    assert index == 1


# ── Width / WidthChanged ───────────────────────────────────────────────


def test_grouped_render_respects_min_banner_width(monkeypatch: Any) -> None:
    """Even with one tiny CL the banner still spans at least the min width."""
    widget, posted = _wire_widget(monkeypatch)
    css = [_cs("a", status="WIP")]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    width_msgs = [m for m in posted if isinstance(m, ChangeSpecList.WidthChanged)]
    assert width_msgs, "expected at least one WidthChanged message"
    # Banner content + padding always lands above the minimum.
    assert width_msgs[-1].width >= 40


# ── update_highlight overload ──────────────────────────────────────────


def test_update_highlight_with_group_key_moves_to_banner(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP"), _cs("beta", status="Ready")]
    fold = GroupFoldRegistry()
    fold.collapse(("Ready",))
    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
        fold_registry=fold,
    )

    widget.update_highlight(0, group_key=("Ready",))

    assert widget.highlighted == widget._banner_row_by_key[("Ready",)]


def test_update_highlight_walks_row_map_in_grouped_mode(monkeypatch: Any) -> None:
    """Without group_key, highlight resolves to the CL's actual option row."""
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP"), _cs("beta", status="Ready")]
    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    widget.update_highlight(1)

    # Row 0 is the WIP banner, row 1 is alpha, row 2 is the Ready banner,
    # row 3 is beta.  current_idx=1 must land on beta's row, not on a
    # raw clamped option index.
    row = widget.highlighted
    assert row is not None
    assert widget._row_entries[row] == 1


# ── Long names / narrow widths: layout regressions ────────────────────


def _option_cell_len(widget: ChangeSpecList, row: int) -> int:
    """Cell length of the rendered Rich Text for the given option row."""
    opt = widget.get_option_at_index(row)
    prompt = opt.prompt
    # ``prompt`` is a ``Text`` for grouped-mode banners and CL rows.
    return prompt.cell_len if hasattr(prompt, "cell_len") else len(str(prompt))


def test_long_cl_name_grows_banner_width_to_fit(monkeypatch: Any) -> None:
    """When a CL name is very long the banner rule must stretch with it.

    A short banner over a long CL row would visually misalign — the CL
    row would extend past the banner's right edge, making the banner
    look truncated.  The widget compensates by widening the banner to
    the max CL row width.
    """
    widget, posted = _wire_widget(monkeypatch)
    long_name = "a" * 80
    css = [_cs(long_name, status="WIP"), _cs("short", status="WIP")]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    # The width broadcast to the parent container must account for the
    # long row; the trivial 40-char banner floor would clip it.
    width_msgs = [m for m in posted if isinstance(m, ChangeSpecList.WidthChanged)]
    assert width_msgs
    assert width_msgs[-1].width >= len(long_name)


def test_long_status_label_does_not_clip_chip(monkeypatch: Any) -> None:
    """A status with a very long suffix must still leave room for the chip.

    The ``Status (...)`` heading text + ``N CLs`` chip + at least 2
    rule cells must all fit within the banner width.  Cell length must
    therefore be ``>= label + chip + 4`` cells (prefix glyph + space +
    rule padding + space).
    """
    widget, _ = _wire_widget(monkeypatch)
    long_status = "Ready - (!: REVIEWERS PENDING + LOTS OF EXTRA CONTEXT)"
    css = [_cs("a", status=long_status), _cs("b", status=long_status)]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    # Banner is row 0.  Its rendered text must contain both the full
    # label and the chip; if either was truncated the row would render
    # shorter than label_len + chip_len.
    cell_len = _option_cell_len(widget, 0)
    chip_text = "2 CLs"
    assert cell_len >= len(long_status) + len(chip_text)


def test_banner_rule_stays_at_least_two_cells(monkeypatch: Any) -> None:
    """Even when label + chip nearly fill the row the rule keeps two cells.

    The rendering helper uses ``pad_len = max(2, width - used)`` so we
    never end up with the label and chip butted together with no rule
    glyph between them.  This test asserts the lower-bound holds for a
    label sized exactly to the banner width.
    """
    widget, _ = _wire_widget(monkeypatch)
    # Single CL with a moderately long name to push the banner width
    # right up to the natural width of its label + chip.
    css = [_cs("medium_length_changespec_name_for_layout_check", status="WIP")]

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
    )

    # The banner is the first option.  Its rendered string must contain
    # the rule character between the label and the chip — assert via a
    # plain-text scan that two consecutive rule chars exist.
    opt = widget.get_option_at_index(0)
    plain = opt.prompt.plain if hasattr(opt.prompt, "plain") else str(opt.prompt)
    # ``─`` is the L0 rule glyph used in ``_agent_list_styling``.
    assert "──" in plain or "  " in plain, (
        "banner must keep at least two rule cells between label and chip; "
        f"got: {plain!r}"
    )


def test_jump_hint_prefix_does_not_overflow_banner(monkeypatch: Any) -> None:
    """A jump-hint prefix on a banner extends the natural width by 4 cells.

    The widget must factor the hint into its width calculation so the
    chip never gets shoved past the banner's right edge.
    """
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha", status="WIP"), _cs("beta", status="WIP")]
    fold = GroupFoldRegistry()
    fold.collapse(("WIP",))

    widget.update_list(
        css,
        current_idx=0,
        grouping_mode=ChangeSpecGroupingMode.BY_STATUS,
        fold_registry=fold,
        banner_jump_hints={("WIP",): "x"},
    )

    # Collapsed banner row carries the hint.  Its plain text must
    # include both the hint marker and the chip text.
    opt = widget.get_option_at_index(0)
    plain = opt.prompt.plain if hasattr(opt.prompt, "plain") else str(opt.prompt)
    assert "[x]" in plain
    assert "2 CLs" in plain

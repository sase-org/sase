"""Phase 2 tests for grouped rendering in ``ChangeSpecList``.

Drives the widget directly (no Pilot) so the assertions stay focused on
row mapping and Option emission rather than Textual paint timing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.message import Message

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets import ChangeSpecList
from sase.ace.tui.widgets.changespec_list import _BANNER_ROW


def _wire_widget(monkeypatch: Any) -> tuple[ChangeSpecList, list[Message]]:
    widget = ChangeSpecList()
    posted: list[Message] = []

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", posted.append)
    return widget, posted


def _cs(name: str, *, project: str = "demo", status: str = "WIP") -> ChangeSpec:
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
    )


# ── FLAT mode: backward-compatible row mapping ─────────────────────────


def test_flat_render_populates_row_entries_identity(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha"), _cs("beta"), _cs("gamma")]

    widget.update_list(css, current_idx=0)

    assert widget._row_entries == [0, 1, 2]
    assert widget._banner_at_row == {}
    assert widget._banner_row_by_key == {}
    assert widget._grouping_mode is ChangeSpecGroupingMode.FLAT
    # Flat-mode option count matches the CL count exactly so the
    # patch-row gate (option_count == len(_changespecs)) keeps working.
    assert widget.option_count == len(css)


def test_flat_render_default_mode_is_unchanged(monkeypatch: Any) -> None:
    """Callers that don't pass ``grouping_mode`` get the original behavior."""
    widget, _ = _wire_widget(monkeypatch)
    css = [_cs("alpha"), _cs("beta")]

    widget.update_list(css, current_idx=1)

    assert widget._grouping_mode is ChangeSpecGroupingMode.FLAT
    # Highlight resolves to the CL row, not a banner.
    assert widget.highlighted == 1


# ── BY_STATUS / BY_DATE: L0 banners only, no L1 ────────────────────────


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

    # 2 banners (WIP, Ready) + 3 CL rows = 5 options.
    assert widget.option_count == 5
    # _row_entries shape: BANNER, cs, cs, BANNER, cs.
    banner_rows = [i for i, e in enumerate(widget._row_entries) if e == _BANNER_ROW]
    cs_rows = [i for i, e in enumerate(widget._row_entries) if e != _BANNER_ROW]
    assert len(banner_rows) == 2
    assert len(cs_rows) == 3
    # Lifecycle order: WIP precedes Ready.
    assert banner_rows[0] < banner_rows[1]


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


def test_flat_render_width_unchanged_by_grouping_path(monkeypatch: Any) -> None:
    """Flat path width calc is independent of the grouped-mode min."""
    widget, posted = _wire_widget(monkeypatch)
    css = [_cs("alpha")]

    widget.update_list(css, current_idx=0)

    width_msgs = [m for m in posted if isinstance(m, ChangeSpecList.WidthChanged)]
    assert width_msgs
    # Flat-mode width comes from CL content + 8 padding; should be much
    # smaller than the grouped-mode floor of ~48 (40 banner + 8 pad) for
    # this trivially-named CL.
    assert width_msgs[-1].width < 40


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

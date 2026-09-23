"""Pure tests for the labeled top-bar cluster helpers."""

from __future__ import annotations

import itertools

from sase.ace.tui.proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE
from sase.ace.tui.widgets.top_bar_group import (
    TOP_BAR_SEPARATOR,
    TopBarGroup,
    choose_top_bar_density,
    filled_count_chip,
    separator_visibility,
)


def test_separator_visibility_matches_joined_groups_over_all_subsets() -> None:
    """Every visibility subset joins exactly like visible texts with dots."""
    texts = ["procs:  2 ", "monitors:  1 ", "updates:  3 ", "a", "b", "c", "inbox: 0"]
    for bits in itertools.product([False, True], repeat=7):
        visible = list(bits)
        flags = separator_visibility(visible)
        assert len(flags) == 6
        # Rebuild the row the cluster would render: visible groups joined
        # by the separator wherever the flag is set.
        parts: list[str] = []
        for index, show in enumerate(visible):
            if not show:
                continue
            if parts:
                # The flag before this group must be set iff a previous
                # group is visible.
                assert flags[index - 1] == any(visible[:index])
                parts.append(TOP_BAR_SEPARATOR.strip())
            parts.append(texts[index])
        joined = f" {TOP_BAR_SEPARATOR.strip()} ".join(
            texts[i] for i, v in enumerate(visible) if v
        )
        # No leading, trailing, or doubled separators by construction.
        assert not joined.startswith("·")
        assert not joined.endswith("·")
        assert "··" not in joined
        assert "·  ·" not in joined


def test_separator_visibility_examples() -> None:
    assert separator_visibility([]) == ()
    assert separator_visibility([True]) == ()
    assert separator_visibility([False, False]) == (False,)
    assert separator_visibility([True, False, True]) == (False, True)
    assert separator_visibility([True, True, True]) == (True, True)
    assert separator_visibility([False, True, True]) == (False, True)


def test_choose_top_bar_density_at_fit_boundary() -> None:
    assert choose_top_bar_density(10, full_cells=10) == "full"
    assert choose_top_bar_density(9, full_cells=10) == "compact"
    assert choose_top_bar_density(100, full_cells=10) == "full"
    assert choose_top_bar_density(0, full_cells=0) == "full"


def test_filled_count_chip_style_and_zero() -> None:
    chip = filled_count_chip(2, PROC_GEAR_HUE)
    assert chip.plain == " 2 "
    assert chip.style == f"bold #1a1a1a on {PROC_GEAR_HUE}"
    assert filled_count_chip(1, MONITOR_GEAR_HUE).plain == " 1 "
    assert filled_count_chip(0, PROC_GEAR_HUE).plain == ""
    assert filled_count_chip(-3, PROC_GEAR_HUE).plain == ""


class _ProbeGroup(TopBarGroup):
    GROUP_LABEL = "probes"


def test_label_composition_full_compact_and_hidden() -> None:
    from rich.text import Text

    group = _ProbeGroup()
    # Hidden initially renders empty.
    assert group.group_visible is False
    assert group.full_cells == 0
    assert group.compact_cells == 0

    group._set_body(Text(" 2 ", style="bold #1a1a1a on #48CAE4"))
    assert group.group_visible is True
    assert group.full_cells > group.compact_cells > 0
    # Full shows the dim label plus the body.
    full = group._composed_text()
    assert full.plain == "probes:  2 "
    # Compact drops the label but keeps the body.
    group.set_density("compact")
    assert group._composed_text().plain == " 2 "
    # Hiding collapses to empty in either density.
    group._set_body(Text(""))
    assert group._composed_text().plain == ""
    assert group.full_cells == 0


def test_set_body_noops_on_identical_body() -> None:
    from rich.text import Text

    group = _ProbeGroup()
    body = Text(" 2 ", style="bold #1a1a1a on #48CAE4")
    assert group._set_body(body) is True
    assert group._set_body(body.copy()) is False
    assert group.set_density("full") is False
    assert group.set_density("compact") is True
    assert group.set_density("compact") is False

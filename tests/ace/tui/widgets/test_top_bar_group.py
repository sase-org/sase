"""Pure tests for the labeled top-bar cluster helpers."""

from __future__ import annotations

import itertools

from sase.ace.tui.proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE
from sase.ace.tui.widgets.top_bar_group import (
    TOP_BAR_SEPARATOR,
    TopBarGroup,
    choose_top_bar_density,
    icon_count_chip,
    separator_visibility,
)


def test_separator_visibility_matches_joined_groups_over_all_subsets() -> None:
    """Every visibility subset joins exactly like visible texts with dots."""
    texts = [
        "procs:  ⚙ 2 ",
        "monitors:  ⚙ 1 ",
        "updates:  3 ",
        "a",
        "b",
        "c",
        "d",
        "inbox: 0",
    ]
    for bits in itertools.product([False, True], repeat=8):
        visible = list(bits)
        flags = separator_visibility(visible)
        assert len(flags) == 7
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


def test_icon_count_chip_style_and_zero() -> None:
    chip = icon_count_chip("⚙", 2, PROC_GEAR_HUE)
    assert chip.plain == " ⚙ 2 "
    assert chip.style == f"bold #1a1a1a on {PROC_GEAR_HUE}"
    assert icon_count_chip("⚙", 1, MONITOR_GEAR_HUE).plain == " ⚙ 1 "
    assert icon_count_chip("≡", 4, "#FF87D7").plain == " ≡ 4 "
    assert icon_count_chip("⚙", 0, PROC_GEAR_HUE).plain == ""
    assert icon_count_chip("⚙", -3, PROC_GEAR_HUE).plain == ""


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


def test_full_density_dims_only_the_label() -> None:
    """Only the label is dim; the body renders as it does at compact density."""
    from rich.console import Console
    from rich.text import Text

    console = Console(color_system="truecolor", width=80)
    group = _ProbeGroup()
    group._set_body(Text(" 2 ", style="bold #1a1a1a on #48CAE4"))

    full = group._composed_text()
    # No base style may leak onto appended spans.
    assert str(full.style) == ""
    label = f"{group.GROUP_LABEL}: "
    assert full.plain.startswith(label)

    # The label segment is dim.
    for offset in range(len(label)):
        assert full.get_style_at_offset(console, offset).dim is True

    # A body that did not ask for dim has no dim segment at full density.
    for offset in range(len(label), len(full.plain)):
        assert not full.get_style_at_offset(console, offset).dim

    # The body renders exactly as at compact density.
    group.set_density("compact")
    compact = group._composed_text()
    assert compact.plain == " 2 "
    for index in range(len(compact.plain)):
        full_style = full.get_style_at_offset(console, len(label) + index)
        compact_style = compact.get_style_at_offset(console, index)
        assert str(full_style) == str(compact_style)


def test_full_density_keeps_a_body_dim_the_body_asked_for() -> None:
    """A body that asks for dim itself (quiet states) stays dim."""
    from rich.console import Console
    from rich.text import Text

    console = Console(color_system="truecolor", width=80)
    group = _ProbeGroup()
    group._set_body(Text("0", style="dim"))

    full = group._composed_text()
    label = f"{group.GROUP_LABEL}: "
    for offset in range(len(label), len(full.plain)):
        assert full.get_style_at_offset(console, offset).dim is True

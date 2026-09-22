"""Height regimes for the Agents-tab tribe stack.

When the sum of natural panel heights fits the agent-list container,
the first panel fills leftover space while later panels are sized to
exactly fit their content (Fits regime). When it overflows, compact panels
are protected with fixed cell heights where possible while larger cropped
panels keep fractional sizing.
"""

from __future__ import annotations

from typing import Any

from textual.css.scalar import Unit

from ._agent_panels_display_helpers import (
    _FakeApp,
    _Size,
    _agent,
    _pw,
    _three_panel_agents,
    _two_tribe_assigned_panel_agents,
)


def test_fits_regime_main_panel_absorbs_leftover() -> None:
    # 3 panels with option counts 2 / 4 / 6 -> naturals 4 / 6 / 8 plus
    # two separator rows = 20 <= 30.
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=30)

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    # The first panel gets the flexible height so it absorbs any leftover
    # space in the column.
    assert main.styles.height.unit is Unit.FRACTION
    assert main.styles.height.value == 1.0
    assert apple.styles.height.unit is Unit.CELLS
    assert apple.styles.height.value == 6.0
    assert banana.styles.height.unit is Unit.CELLS
    assert banana.styles.height.value == 8.0


def test_collapsed_no_tribe_panel_moves_last_and_stays_fixed() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[8, 4, 6], container_height=30)
    app._collapsed_panel_keys.add(None)
    app._sync_panel_group()

    app._refresh_panel_widgets(jump_hints=None)

    apple = _pw(app, "apple")
    banana = _pw(app, "banana")
    no_tribe = _pw(app, None)
    assert app._panel_group.panel_keys == ["apple", "banana", None]
    assert apple.styles.height.unit is Unit.FRACTION
    assert apple.styles.height.value == 1.0
    assert banana.styles.height.unit is Unit.CELLS
    assert banana.styles.height.value == 8.0
    assert no_tribe.render_collapsed_calls == 1
    assert no_tribe.styles.height.unit is Unit.CELLS
    assert no_tribe.styles.height.value == 2.0
    assert "-collapsed-panel" in no_tribe._classes


def test_separator_rows_are_included_in_fit_boundary() -> None:
    # Naturals are 4 / 6 / 8. Without separators this would fit in 19 rows,
    # but the two separator rows make the stack cost 20 and force cropping.
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=19)

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    assert main.styles.height.unit is Unit.CELLS
    assert main.styles.height.value == 4.0
    assert apple.styles.height.unit is Unit.CELLS
    assert apple.styles.height.value == 6.0
    assert banana.styles.height.unit is Unit.FRACTION
    assert banana.styles.height.value == 7.0


def test_overflow_regime_protects_small_tribe_panel_before_large_panel() -> None:
    # @apple has only a banner + agent row, so it should stay at natural
    # height while the larger @banana panel absorbs the cropping pressure.
    agents = _two_tribe_assigned_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 25], container_height=12)

    app._refresh_panel_widgets(jump_hints=None)

    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    assert apple.styles.height.unit is Unit.CELLS
    assert apple.styles.height.value == 4.0
    assert banana.styles.height.unit is Unit.FRACTION
    assert banana.styles.height.value == 26.0  # option_count 25 + 1


def test_overflow_regime_keeps_small_no_tribe_panel_natural() -> None:
    # The ascending-height protection pass keeps the no_tribe panel's natural
    # height (8) fixed while the larger tribe panels absorb cropping pressure.
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[6, 20, 20], container_height=20)

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    assert main.styles.height.unit is Unit.CELLS
    assert main.styles.height.value == 8.0
    assert apple.styles.height.unit is Unit.FRACTION
    assert apple.styles.height.value == 21.0
    assert banana.styles.height.unit is Unit.FRACTION
    assert banana.styles.height.value == 21.0


def test_overflow_regime_leaves_large_no_tribe_panel_fractional() -> None:
    # Naturals are 24 / 3 / 3 plus two separators, so the 32-row stack barely
    # overflows its 30-row container. The compact tribe panels stay fully visible
    # while the large no_tribe panel absorbs all remaining rows.
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[22, 1, 1], container_height=30)

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    assert main.styles.height.unit is Unit.FRACTION
    assert main.styles.height.value == 23.0
    assert apple.styles.height.unit is Unit.CELLS
    assert apple.styles.height.value == 3.0
    assert banana.styles.height.unit is Unit.CELLS
    assert banana.styles.height.value == 3.0


def test_overflow_regime_shares_multiple_large_panels_proportionally() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[10, 20, 30], container_height=20)

    app._refresh_panel_widgets(jump_hints=None)

    main = _pw(app, None)
    apple = _pw(app, "apple")
    banana = _pw(app, "banana")

    assert main.styles.height.unit is Unit.FRACTION
    assert main.styles.height.value == 11.0
    assert apple.styles.height.unit is Unit.FRACTION
    assert apple.styles.height.value == 21.0
    assert banana.styles.height.unit is Unit.FRACTION
    assert banana.styles.height.value == 31.0


def test_single_panel_fills_container() -> None:
    # A single no_tribe panel absorbs the full column height via a fractional
    # unit, so it extends to the bottom even when its natural height (5) is
    # smaller than the container.
    agents = [_agent(name="u1", tribe=None, suffix="t1")]
    app = _FakeApp(agents, option_counts=[3], container_height=40)

    app._refresh_panel_widgets(jump_hints=None)

    main = app._panel_widgets["agent-list-panel"]
    assert main.styles.height.unit is Unit.FRACTION
    assert main.styles.height.value == 1.0


def test_pre_mount_zero_height_leaves_styles_alone() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=0)

    app._refresh_panel_widgets(jump_hints=None)

    for widget in app._panel_widgets.values():
        assert widget.styles.height is None


def test_reapply_does_not_rebuild_option_lists() -> None:
    """Resize path re-runs height math without calling ``update_list``."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=30)

    app._refresh_panel_widgets(jump_hints=None)
    rebuilds_after_initial = {
        wid: w.update_list_calls for wid, w in app._panel_widgets.items()
    }

    # Simulate a layout cycle that shrinks the container, then re-run only
    # the height computation (no option-list rebuild).
    app._container.size = _Size(height=12)
    widgets: Any = list(app._panel_widgets.values())
    app._apply_panel_heights(app._container, widgets)

    # No additional update_list calls — only heights changed.
    for wid, prior in rebuilds_after_initial.items():
        assert app._panel_widgets[wid].update_list_calls == prior

    # Heights flipped to the overflow regime.
    main = app._panel_widgets["agent-list-panel"]
    assert main.styles.height.unit is Unit.FRACTION
    assert main.styles.height.value == 3.0  # option_count 2 + 1

"""Tests for fold-aware CLs-tab navigation, folding, and jump hints.

Phase 4 of the CLs-tab ChangeSpec grouping feature
(``sdd/plans/202604/changespec_group_headings.md``):

* ``j`` / ``k`` walks visible CL rows plus collapsed banner rows in
  render order.
* ``h`` / ``l`` / ``H`` / ``L`` operate on CL groups.
* Focus re-anchors after fold mutations so the cursor never lands on a
  hidden row.
* Jump hints include collapsed banner targets.
* Stale ``_current_changespec_group_key`` is dropped after a reload
  whose query no longer produces the focused group.
"""

from __future__ import annotations

from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.changespec._grouping_nav import (
    ChangeSpecGroupingNavMixin,
)
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry

from .models._changespec_groups_helpers import _cs


class _NavApp(ChangeSpecGroupingNavMixin):
    """Minimal harness exposing the grouping-navigation mixin.

    Mirrors the AceApp attribute surface the mixin reads.  The
    ``_refresh_display`` stub records calls so tests can assert that
    banner-only navigation transitions still trigger a refresh.
    """

    def __init__(
        self,
        changespecs: list[ChangeSpec],
        *,
        mode: ChangeSpecGroupingMode = ChangeSpecGroupingMode.BY_PROJECT,
        current_idx: int = 0,
    ) -> None:
        self.current_tab = "changespecs"  # type: ignore[assignment]
        self.changespecs = changespecs
        self.current_idx = current_idx
        self._changespec_grouping_mode = mode
        self._changespec_group_fold_registry = GroupFoldRegistry()
        self._current_changespec_group_key: tuple[str, ...] | None = None
        self.refresh_calls = 0

    def _refresh_display(self) -> None:
        self.refresh_calls += 1


def _make_three_project_specs() -> list[ChangeSpec]:
    """Two CLs in project ``alpha`` and one in project ``beta``."""
    return [
        _cs("a_one", project="alpha"),
        _cs("a_two", project="alpha"),
        _cs("b_one", project="beta"),
    ]


# ---------------------------------------------------------------------------
# Navigation stops
# ---------------------------------------------------------------------------


def test_navigation_stops_skip_expanded_banners() -> None:
    app = _NavApp(_make_three_project_specs())
    stops = app._changespec_navigation_stops()
    # All banners are expanded so only CL stops appear.
    assert stops == [
        ("changespec", 0),
        ("changespec", 1),
        ("changespec", 2),
    ]


def test_navigation_stops_include_collapsed_banner() -> None:
    app = _NavApp(_make_three_project_specs())
    app._changespec_group_fold_registry.collapse(("alpha",))
    stops = app._changespec_navigation_stops()
    # ``alpha`` collapses to a single banner stop hiding its two CLs;
    # ``beta`` stays expanded with its single CL row.
    assert stops == [
        ("banner", ("alpha",)),
        ("changespec", 2),
    ]


# ---------------------------------------------------------------------------
# j/k movement
# ---------------------------------------------------------------------------


def test_navigate_steps_through_collapsed_banner_then_cl() -> None:
    app = _NavApp(_make_three_project_specs())
    app._changespec_group_fold_registry.collapse(("alpha",))

    # Stops are [("banner", ("alpha",)), ("changespec", 2)] — current_idx
    # 0 sits inside the now-collapsed alpha group, so the nearest CL stop
    # is beta at pos 1, and ``+1`` wraps to the alpha banner at pos 0.
    app._navigate_changespec_panel(1)
    assert app._current_changespec_group_key == ("alpha",)
    assert app.current_idx == 0

    # Forward again: banner → CL.
    app._navigate_changespec_panel(1)
    assert app._current_changespec_group_key is None
    assert app.current_idx == 2

    # Backward from the beta CL: back to the alpha banner.
    app._navigate_changespec_panel(-1)
    assert app._current_changespec_group_key == ("alpha",)


def test_navigate_banner_to_cl_triggers_refresh_even_when_idx_unchanged() -> None:
    specs = _make_three_project_specs()
    # Force current_idx onto the first CL of the only-collapsed group so
    # banner→CL stepping lands on the same global index.
    app = _NavApp(specs, current_idx=2)
    app._changespec_group_fold_registry.collapse(("alpha",))
    app._current_changespec_group_key = ("alpha",)

    # Banner→CL with current_idx unchanged must still drive a refresh.
    app._navigate_changespec_panel(1)
    assert app._current_changespec_group_key is None
    assert app.refresh_calls == 1


# ---------------------------------------------------------------------------
# h / l / H / L
# ---------------------------------------------------------------------------


def test_collapse_focused_cl_group_snaps_to_banner() -> None:
    app = _NavApp(_make_three_project_specs(), current_idx=0)
    changed = app._collapse_changespec_group_fold()
    assert changed is True
    assert app._changespec_group_fold_registry.is_collapsed(("alpha",))
    assert app._current_changespec_group_key == ("alpha",)


def test_collapse_focused_banner_collapses_it() -> None:
    app = _NavApp(_make_three_project_specs())
    app._current_changespec_group_key = ("alpha",)
    changed = app._collapse_changespec_group_fold()
    assert changed is True
    assert app._changespec_group_fold_registry.is_collapsed(("alpha",))


def test_expand_collapsed_banner_reanchors_focus_to_first_cl() -> None:
    app = _NavApp(_make_three_project_specs())
    app._changespec_group_fold_registry.collapse(("alpha",))
    app._current_changespec_group_key = ("alpha",)

    changed = app._expand_changespec_group_fold()
    assert changed is True
    assert not app._changespec_group_fold_registry.is_collapsed(("alpha",))
    # First visible CL of the expanded group becomes the focused row.
    assert app._current_changespec_group_key is None
    assert app.current_idx == 0


def test_collapse_all_collapses_visible_l0_banners() -> None:
    app = _NavApp(_make_three_project_specs(), current_idx=2)
    changed = app._collapse_all_changespec_group_folds()
    assert changed is True
    assert app._changespec_group_fold_registry.is_collapsed(("alpha",))
    assert app._changespec_group_fold_registry.is_collapsed(("beta",))
    # Focus snaps to the deepest enclosing collapsed banner of the
    # previously focused CL.
    assert app._current_changespec_group_key == ("beta",)


def test_collapse_all_collapses_only_deepest_visible_cl_group_level() -> None:
    specs = [
        _cs("foobar_1", project="proj"),
        _cs("foobar_2", project="proj"),
        _cs("solo", project="proj"),
    ]
    app = _NavApp(specs, current_idx=0)

    changed = app._collapse_all_changespec_group_folds()
    assert changed is True
    assert not app._changespec_group_fold_registry.is_collapsed(("proj",))
    assert app._changespec_group_fold_registry.is_collapsed(("proj", "foobar"))
    assert app._current_changespec_group_key == ("proj", "foobar")


def test_collapse_all_collapses_next_deepest_cl_group_level() -> None:
    specs = [
        _cs("foobar_1", project="proj"),
        _cs("foobar_2", project="proj"),
        _cs("solo", project="proj"),
    ]
    app = _NavApp(specs, current_idx=0)
    app._changespec_group_fold_registry.collapse(("proj", "foobar"))

    changed = app._collapse_all_changespec_group_folds()
    assert changed is True
    assert app._changespec_group_fold_registry.is_collapsed(("proj",))
    assert app._changespec_group_fold_registry.is_collapsed(("proj", "foobar"))
    assert app._current_changespec_group_key == ("proj",)


def test_expand_all_peels_one_level_off_visible_collapsed_banners() -> None:
    app = _NavApp(_make_three_project_specs())
    app._changespec_group_fold_registry.collapse(("alpha",))
    app._changespec_group_fold_registry.collapse(("beta",))
    app._current_changespec_group_key = ("alpha",)

    changed = app._expand_all_changespec_group_folds()
    assert changed is True
    assert not app._changespec_group_fold_registry.is_collapsed(("alpha",))
    assert not app._changespec_group_fold_registry.is_collapsed(("beta",))
    # ``L`` clears any banner focus so j/k can re-anchor on a CL row.
    assert app._current_changespec_group_key is None


# ---------------------------------------------------------------------------
# Jump hints
# ---------------------------------------------------------------------------


def test_jump_targets_include_collapsed_banner_in_render_order() -> None:
    app = _NavApp(_make_three_project_specs())
    app._changespec_group_fold_registry.collapse(("alpha",))
    targets = app._changespec_jump_targets()
    assert targets == [
        ("banner", ("alpha",)),
        ("changespec", 2),
    ]


# ---------------------------------------------------------------------------
# Banner focus validity after reload
# ---------------------------------------------------------------------------


def test_banner_focus_valid_when_group_still_present() -> None:
    app = _NavApp(_make_three_project_specs())
    app._current_changespec_group_key = ("alpha",)
    assert app._changespec_banner_focus_still_valid() is True


def test_banner_focus_invalid_when_group_filtered_out() -> None:
    # Drop the two ``alpha`` CLs — only ``beta`` remains.
    app = _NavApp([_cs("b_one", project="beta")])
    app._current_changespec_group_key = ("alpha",)
    assert app._changespec_banner_focus_still_valid() is False


def test_banner_focus_valid_when_unset() -> None:
    app = _NavApp(_make_three_project_specs())
    assert app._changespec_banner_focus_still_valid() is True


# ---------------------------------------------------------------------------
# Action wiring (j/k from BasicNavigationMixin)
# ---------------------------------------------------------------------------


class _NavActionApp(_NavApp):
    """Adds the ``j``/``k`` actions on top of the grouping mixin."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._jk_perf_count = 0

    # The action implementation lives in BasicNavigationMixin.  Splice
    # the relevant behavior here so the test stays focused on the CL
    # branch without dragging in the agents/AXE wiring.
    def action_next_changespec(self) -> None:
        self._navigate_changespec_panel(1)

    def action_prev_changespec(self) -> None:
        self._navigate_changespec_panel(-1)


def test_jk_in_grouped_mode_walks_collapsed_banner_stops() -> None:
    app = _NavActionApp(_make_three_project_specs(), current_idx=0)
    app._changespec_group_fold_registry.collapse(("alpha",))

    app.action_next_changespec()
    # Stops are [("banner", alpha), ("changespec", 2)]; idx=0 (inside
    # alpha) anchors at pos=1 (closest CL), and +1 wraps to alpha banner.
    assert app._current_changespec_group_key == ("alpha",)

    app.action_next_changespec()
    # Banner → beta CL.
    assert app._current_changespec_group_key is None
    assert app.current_idx == 2


# ---------------------------------------------------------------------------
# h / l / H / L action dispatch (AgentFoldingMixin)
# ---------------------------------------------------------------------------


def test_hooks_or_collapse_routes_to_cl_grouped_collapse() -> None:
    from sase.ace.tui.actions.agents._folding import AgentFoldingMixin

    class _FoldHarness(_NavApp, AgentFoldingMixin):
        def __init__(self, specs: list[ChangeSpec]) -> None:
            _NavApp.__init__(self, specs)

    app = _FoldHarness(_make_three_project_specs())
    app.action_hooks_or_collapse()
    assert app._changespec_group_fold_registry.is_collapsed(("alpha",))
    assert app.refresh_calls == 1

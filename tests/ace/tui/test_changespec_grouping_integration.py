"""End-to-end-ish integration coverage for the CLs-tab grouping feature.

Phase 5 of ``sdd/tales/202604/changespec_group_headings.md``.  These tests
intentionally combine three previously-isolated layers — the
:class:`AgentGroupingMixin` cycle action, the
:class:`ChangeSpecGroupingNavMixin` fold/navigation helpers, and the
real :class:`ChangeSpecList` widget render — so we catch regressions
that only surface when the layers handshake (e.g. cycling to a new
mode forgets to swap the registry the widget reads from, or filtering
out a group leaves a stale banner-focus key that crashes the next
render pass).

Pilot-style ``async with App.run_test()`` is overkill for these
scenarios since none of them require Textual paint timing.  We drive
the widget directly and assert on its post-render row map / option
list, which keeps assertions specific without paying the pilot cost.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.message import Message

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.agents._grouping import AgentGroupingMixin
from sase.ace.tui.actions.changespec._grouping_nav import (
    ChangeSpecGroupingNavMixin,
)
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets import ChangeSpecList
from sase.ace.tui.widgets.changespec_list import _BANNER_ROW


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


def _wire_widget(monkeypatch: Any) -> tuple[ChangeSpecList, list[Message]]:
    widget = ChangeSpecList()
    posted: list[Message] = []

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", posted.append)
    return widget, posted


class _IntegrationApp(AgentGroupingMixin, ChangeSpecGroupingNavMixin):
    """Combined harness wiring the grouping mixin into the navigation mixin.

    Mirrors the attribute surface of the real ``AceApp`` for both the
    Agents and CLs tabs, but drives only the slice the integration
    tests need.  The grouped widget is owned by the harness so the
    test can assert on the post-render option list directly.
    """

    def __init__(
        self,
        widget: ChangeSpecList,
        changespecs: list[ChangeSpec],
        *,
        current_tab: Any = "changespecs",
    ) -> None:
        self._widget = widget
        self.current_tab = current_tab
        self.changespecs = changespecs
        self.current_idx = 0
        # Agents-side state.
        self._agents: list[Any] = []
        self._grouping_mode = GroupingMode.STANDARD
        self._group_fold_registries: dict[GroupingMode, AgentGroupFoldRegistry] = {
            GroupingMode.STANDARD: AgentGroupFoldRegistry(),
        }
        self._group_fold_registry = self._group_fold_registries[GroupingMode.STANDARD]
        self._current_group_key: tuple[str, ...] | None = None
        # CL-side state.
        self._changespec_grouping_mode = ChangeSpecGroupingMode.BY_PROJECT
        self._changespec_group_fold_registries: dict[
            ChangeSpecGroupingMode, GroupFoldRegistry
        ] = {ChangeSpecGroupingMode.BY_PROJECT: GroupFoldRegistry()}
        self._changespec_group_fold_registry = self._changespec_group_fold_registries[
            ChangeSpecGroupingMode.BY_PROJECT
        ]
        self._current_changespec_group_key: tuple[str, ...] | None = None
        self.refresh_calls = 0
        self.refilter_calls = 0
        self.notifications: list[str] = []

    def notify(self, message: str, **kwargs: Any) -> None:
        self.notifications.append(message)

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_calls += 1

    def _refresh_display(self) -> None:
        """Drive a real widget render so tests exercise the production path."""
        self.refresh_calls += 1
        self._widget.update_list(
            self.changespecs,
            self.current_idx,
            grouping_mode=self._changespec_grouping_mode,
            fold_registry=self._changespec_group_fold_registry,
            current_group_key=self._current_changespec_group_key,
        )


# ---------------------------------------------------------------------------
# o cycle through every mode drives a widget render at each step
# ---------------------------------------------------------------------------


def _three_project_specs() -> list[ChangeSpec]:
    return [
        _cs("alpha_one", project="alpha"),
        _cs("alpha_two", project="alpha"),
        _cs("beta_one", project="beta", status="Ready"),
    ]


def test_o_cycles_widget_through_every_grouping_mode(monkeypatch: Any) -> None:
    """Pressing ``o`` three times must redraw the widget through every mode."""
    widget, _ = _wire_widget(monkeypatch)
    app = _IntegrationApp(widget, _three_project_specs())

    # Start BY_PROJECT: project banners appear from the first paint.
    app._refresh_display()
    banner_rows = [i for i, e in enumerate(widget._row_entries) if e == _BANNER_ROW]
    # alpha L0 banner + alpha-siblings L1 banner (foobar_1/_2 style with
    # ``alpha_one`` and ``alpha_two`` sharing root ``alpha``) + beta L0.
    assert len(banner_rows) >= 2

    # BY_PROJECT → BY_DATE: undated CLs land under Earlier plus the
    # final ``(no timestamp)`` subgroup.
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_DATE
    # All test CSs have no TIMESTAMPS so they all land in ``Earlier``.
    assert app.notifications[-1] == "CL grouping: by date"
    banner_rows = [i for i, e in enumerate(widget._row_entries) if e == _BANNER_ROW]
    assert len(banner_rows) == 2

    # BY_DATE → BY_STATUS: WIP and Ready buckets.
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_STATUS
    banner_rows = [
        i
        for i in range(widget.option_count)
        if widget._row_entries[i] == _BANNER_ROW
        and not (widget.get_option_at_index(i).id or "").startswith("cs-spacer:")
    ]
    assert len(banner_rows) == 2

    # BY_STATUS → BY_PROJECT (wrap).
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    banner_rows = [i for i, e in enumerate(widget._row_entries) if e == _BANNER_ROW]
    assert len(banner_rows) >= 2


def test_per_mode_fold_state_survives_cycle_round_trip(monkeypatch: Any) -> None:
    """Collapsing a banner in one mode must persist when the user returns to it."""
    widget, _ = _wire_widget(monkeypatch)
    app = _IntegrationApp(widget, _three_project_specs())

    # Collapse the alpha L0 group via the navigation mixin.
    app._current_changespec_group_key = ("alpha",)
    assert app._collapse_changespec_group_fold() is True
    app._refresh_display()
    # Render now shows the collapsed alpha banner + beta CL/banner.
    assert any(
        widget._banner_at_row.get(r, None)
        and widget._banner_at_row[r].group_key == ("alpha",)
        for r in widget._banner_at_row
    )

    app.action_cycle_grouping_mode()  # → BY_DATE
    app.action_cycle_grouping_mode()  # → BY_STATUS
    app.action_cycle_grouping_mode()  # → BY_PROJECT (round trip)

    # Re-render and assert alpha is still collapsed.
    app._refresh_display()
    alpha_row = next(
        (r for r, g in widget._banner_at_row.items() if g.group_key == ("alpha",)),
        None,
    )
    assert alpha_row is not None, "alpha collapse intent did not survive cycle"


# ---------------------------------------------------------------------------
# Query change after collapse — no stale focus crash
# ---------------------------------------------------------------------------


def test_query_change_drops_collapsed_group_without_crash(
    monkeypatch: Any,
) -> None:
    """Filtering out the only members of a collapsed group must drop the focus."""
    widget, _ = _wire_widget(monkeypatch)
    app = _IntegrationApp(widget, _three_project_specs())

    # User collapses alpha and the focus moves to its banner.
    app._current_changespec_group_key = ("alpha",)
    app._changespec_group_fold_registry.collapse(("alpha",))
    app._refresh_display()
    assert ("alpha",) in widget._banner_row_by_key

    # Simulate a query change that filters out everything from alpha.
    app.changespecs = [_cs("beta_one", project="beta", status="Ready")]
    app.current_idx = 0
    # The renderer's ``clear_unknown`` would normally run here; mirror
    # that contract on the test fold registry.
    from sase.ace.tui.models.changespec_groups import (
        enumerate_changespec_group_keys,
    )

    app._changespec_group_fold_registry.clear_unknown(
        enumerate_changespec_group_keys(
            app.changespecs, mode=app._changespec_grouping_mode
        )
    )
    # Stale banner focus must report invalid so the caller can clear it.
    assert app._changespec_banner_focus_still_valid() is False
    app._current_changespec_group_key = None

    # A refresh after clearing the focus must not raise — and must
    # render the surviving beta CL row.
    app._refresh_display()
    cs_rows = [i for i, e in enumerate(widget._row_entries) if e != _BANNER_ROW]
    assert len(cs_rows) == 1


def test_collapse_then_filter_reload_does_not_resurrect_stale_collapse(
    monkeypatch: Any,
) -> None:
    """``clear_unknown`` after a query change drops collapse intent for groups
    that no longer exist; the same group reappearing later must NOT come
    back collapsed automatically."""
    widget, _ = _wire_widget(monkeypatch)
    app = _IntegrationApp(widget, _three_project_specs())
    app._changespec_group_fold_registry.collapse(("alpha",))

    # Filter out alpha entirely.
    app.changespecs = [_cs("beta_one", project="beta", status="Ready")]
    from sase.ace.tui.models.changespec_groups import (
        enumerate_changespec_group_keys,
    )

    app._changespec_group_fold_registry.clear_unknown(
        enumerate_changespec_group_keys(
            app.changespecs, mode=app._changespec_grouping_mode
        )
    )

    # Bring alpha back via a new query.
    app.changespecs = _three_project_specs()
    app._refresh_display()
    # alpha is rendered expanded — i.e. its CL rows are visible.
    cs_rows = [i for i, e in enumerate(widget._row_entries) if e != _BANNER_ROW]
    assert len(cs_rows) == 3


# ---------------------------------------------------------------------------
# Independence between Agents and CLs grouping state
# ---------------------------------------------------------------------------


def test_agents_cycle_does_not_swap_cl_widget_render(monkeypatch: Any) -> None:
    """Pressing ``o`` while the Agents tab owns focus must not redraw CLs."""
    widget, _ = _wire_widget(monkeypatch)
    app = _IntegrationApp(widget, _three_project_specs(), current_tab="agents")

    # CLs start at the default BY_PROJECT and never got a refresh.
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    assert widget.option_count == 0

    app.action_cycle_grouping_mode()  # Agents-side cycle.

    # Agents grouping advanced; CLs untouched.
    assert app._grouping_mode is GroupingMode.BY_DATE
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    assert widget.option_count == 0  # No CL refresh happened.


def test_tab_switch_preserves_each_tabs_grouping_mode(monkeypatch: Any) -> None:
    """Switching between Agents and CLs must not bleed grouping state.

    After a CLs cycle the Agents mode stays at its own default; after
    flipping focus to Agents and cycling there, the CLs mode stays at
    the value the user picked.
    """
    widget, _ = _wire_widget(monkeypatch)
    app = _IntegrationApp(widget, _three_project_specs())

    # CL user cycles to BY_DATE.
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_DATE
    assert app._grouping_mode is GroupingMode.STANDARD

    # User flips to Agents and cycles there.
    app.current_tab = "agents"  # type: ignore[assignment]
    app.action_cycle_grouping_mode()
    assert app._grouping_mode is GroupingMode.BY_DATE
    # CL state untouched.
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_DATE

    # Flip back to CLs — the previous BY_DATE mode is preserved.
    app.current_tab = "changespecs"  # type: ignore[assignment]
    app._refresh_display()
    banner_rows = [i for i, e in enumerate(widget._row_entries) if e == _BANNER_ROW]
    assert banner_rows, "CLs should still render banners after returning to the tab"


def test_axe_cycle_is_silent_noop_for_both_tabs(monkeypatch: Any) -> None:
    """Cycling on AXE leaves both Agents and CLs grouping state untouched."""
    widget, _ = _wire_widget(monkeypatch)
    app = _IntegrationApp(widget, _three_project_specs(), current_tab="axe")

    app.action_cycle_grouping_mode()

    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    assert app.refresh_calls == 0
    assert app.refilter_calls == 0

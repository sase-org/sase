"""Tests for the CLs-tab grouping-mode cycle action.

Covers Phase 3 of the CLs-tab ChangeSpec grouping feature
(``plans/202604/changespec_group_headings.md``):

* Cycle order ``BY_PROJECT → BY_DATE → BY_STATUS → BY_PROJECT``.
* Per-mode fold-state preservation across cycles, with no leakage from
  the Agents-tab fold registries.
* Banner focus is reset on every cycle.
* Non-CL tabs (Agents / AXE) ignore the CL cycle helper, and AXE is a
  silent no-op for the public action even if the focused tab.
* Cycling is session-local and does not write grouping-mode state files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agents._grouping import AgentGroupingMixin
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry


class _StubApp(AgentGroupingMixin):
    """Minimal harness exposing the grouping mixin for both tabs."""

    def __init__(self, current_tab: str = "changespecs") -> None:
        self.current_tab = current_tab  # type: ignore[assignment]
        self.current_idx = 0
        # Agents-side state — lets the dispatcher coexist with the
        # existing Agents tests without crashing if accidentally hit.
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
        # Recording stubs.
        self.refilter_calls = 0
        self.refresh_calls = 0
        self.notifications: list[str] = []

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_calls += 1

    def _refresh_display(self) -> None:
        self.refresh_calls += 1

    def notify(self, message: str, **kwargs: Any) -> None:
        self.notifications.append(message)


# ---------------------------------------------------------------------------
# Cycle order + wrap
# ---------------------------------------------------------------------------


def test_cycle_advances_by_project_to_by_date() -> None:
    app = _StubApp()
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_DATE
    assert app.refresh_calls == 1


def test_cycle_advances_by_date_to_by_status() -> None:
    app = _StubApp()
    app._changespec_grouping_mode = ChangeSpecGroupingMode.BY_DATE
    app._changespec_group_fold_registry = app._ensure_changespec_mode_registry(
        ChangeSpecGroupingMode.BY_DATE
    )
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_STATUS


def test_cycle_wraps_back_to_by_project() -> None:
    app = _StubApp()
    app._changespec_grouping_mode = ChangeSpecGroupingMode.BY_STATUS
    app._changespec_group_fold_registry = app._ensure_changespec_mode_registry(
        ChangeSpecGroupingMode.BY_STATUS
    )
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT


def test_three_cycles_returns_to_by_project() -> None:
    app = _StubApp()
    for _ in range(3):
        app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    assert app.refresh_calls == 3


# ---------------------------------------------------------------------------
# Per-mode fold registry preservation
# ---------------------------------------------------------------------------


def test_fold_state_preserved_after_cycle_round_trip() -> None:
    app = _StubApp()
    project_registry = app._changespec_group_fold_registry
    project_registry.collapse(("projA",))

    app.action_cycle_grouping_mode()  # BY_PROJECT → BY_DATE
    by_date_registry = app._changespec_group_fold_registry
    assert by_date_registry is not project_registry
    # Fresh registry: BY_PROJECT collapse intent does not bleed across modes.
    assert by_date_registry.is_collapsed(("projA",)) is False
    by_date_registry.collapse(("Today",))

    app.action_cycle_grouping_mode()  # → BY_STATUS
    app.action_cycle_grouping_mode()  # → BY_PROJECT (round trip)
    assert app._changespec_group_fold_registry is project_registry
    assert app._changespec_group_fold_registry.is_collapsed(("projA",))


def test_per_mode_registry_dict_grows_lazily() -> None:
    app = _StubApp()
    assert set(app._changespec_group_fold_registries) == {
        ChangeSpecGroupingMode.BY_PROJECT
    }
    app.action_cycle_grouping_mode()  # → BY_DATE
    app.action_cycle_grouping_mode()  # → BY_STATUS
    assert set(app._changespec_group_fold_registries) == set(ChangeSpecGroupingMode)


# ---------------------------------------------------------------------------
# Banner focus reset on cycle
# ---------------------------------------------------------------------------


def test_cycle_clears_current_changespec_group_key() -> None:
    """Banner focus from the previous mode is meaningless in the new mode."""
    app = _StubApp()
    app._current_changespec_group_key = ("projA",)
    app.action_cycle_grouping_mode()
    assert app._current_changespec_group_key is None


# ---------------------------------------------------------------------------
# Tab dispatch
# ---------------------------------------------------------------------------


def test_cycle_on_axe_tab_is_silent_noop() -> None:
    """The cycle key has no grouping target on AXE — both sides untouched."""
    app = _StubApp(current_tab="axe")
    app.action_cycle_grouping_mode()
    assert app.refilter_calls == 0
    assert app.refresh_calls == 0
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT


def test_cycle_on_agents_tab_does_not_touch_cl_state() -> None:
    """Agents cycle leaves the CL grouping mode untouched, and vice versa."""
    app = _StubApp(current_tab="agents")
    app.action_cycle_grouping_mode()
    assert app._grouping_mode is GroupingMode.BY_DATE
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    assert app.refresh_calls == 0
    assert app.refilter_calls == 1


def test_cycle_on_cls_tab_does_not_touch_agents_state() -> None:
    app = _StubApp(current_tab="changespecs")
    app.action_cycle_grouping_mode()
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_DATE
    assert app.refilter_calls == 0
    assert app.refresh_calls == 1


# ---------------------------------------------------------------------------
# No persistence
# ---------------------------------------------------------------------------


def test_cycle_does_not_create_grouping_mode_files(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    app = _StubApp()
    app.action_cycle_grouping_mode()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_DATE
    assert not (tmp_path / ".sase" / "changespec_grouping_mode.txt").exists()
    assert not (tmp_path / ".sase" / "grouping_mode.txt").exists()


# ---------------------------------------------------------------------------
# Toast surface
# ---------------------------------------------------------------------------


def test_cycle_emits_cl_grouping_toast() -> None:
    """The toast distinguishes the CL cycle from the Agents cycle."""
    app = _StubApp()
    app.action_cycle_grouping_mode()
    assert app.notifications == ["CL grouping: by date"]


# ---------------------------------------------------------------------------
# Reverse cycle (`O`)
# ---------------------------------------------------------------------------


def test_reverse_cycle_advances_by_project_to_by_status() -> None:
    app = _StubApp()
    app.action_cycle_grouping_mode_reverse()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_STATUS
    assert app.refresh_calls == 1


def test_reverse_cycle_advances_by_status_to_by_date() -> None:
    app = _StubApp()
    app._changespec_grouping_mode = ChangeSpecGroupingMode.BY_STATUS
    app._changespec_group_fold_registry = app._ensure_changespec_mode_registry(
        ChangeSpecGroupingMode.BY_STATUS
    )
    app.action_cycle_grouping_mode_reverse()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_DATE


def test_reverse_cycle_wraps_back_to_by_project() -> None:
    app = _StubApp()
    app._changespec_grouping_mode = ChangeSpecGroupingMode.BY_DATE
    app._changespec_group_fold_registry = app._ensure_changespec_mode_registry(
        ChangeSpecGroupingMode.BY_DATE
    )
    app.action_cycle_grouping_mode_reverse()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT


def test_three_reverse_cycles_returns_to_by_project() -> None:
    app = _StubApp()
    for _ in range(3):
        app.action_cycle_grouping_mode_reverse()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    assert app.refresh_calls == 3


def test_forward_then_reverse_returns_to_by_project() -> None:
    app = _StubApp()
    app.action_cycle_grouping_mode()
    app.action_cycle_grouping_mode_reverse()
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT


def test_reverse_cycle_on_axe_tab_is_silent_noop() -> None:
    app = _StubApp(current_tab="axe")
    app.action_cycle_grouping_mode_reverse()
    assert app.refilter_calls == 0
    assert app.refresh_calls == 0
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT

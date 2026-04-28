"""Tests for the Agents-tab grouping-mode cycle action.

Covers Phase 3 of the cyclable grouping/sorting modes feature
(``plans/202604/agents_tab_grouping_modes.md``):

* Cycle order ``STANDARD → BY_DATE → BY_STATUS → STANDARD``.
* Per-mode fold-state preservation across mode cycles.
* Tree shape after cycling matches the new mode's L0 (project /
  date bucket / status bucket).
* Non-agents tabs are a silent no-op — the cycle key only acts on Agents.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._grouping import AgentGroupingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    build_agent_tree,
    enumerate_group_keys,
)
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry


class _StubApp(AgentGroupingMixin):
    """Minimal harness exposing the grouping mixin in isolation."""

    def __init__(self, agents: list[Agent], current_tab: str = "agents") -> None:
        self.current_tab = current_tab  # type: ignore[assignment]
        self.current_idx = 0
        self._agents = agents
        self._grouping_mode = GroupingMode.STANDARD
        self._group_fold_registries: dict[GroupingMode, AgentGroupFoldRegistry] = {
            GroupingMode.STANDARD: AgentGroupFoldRegistry(),
        }
        self._group_fold_registry = self._group_fold_registries[GroupingMode.STANDARD]
        self._current_group_key: tuple[str, ...] | None = None
        # CL-side state is required by the action's tab dispatch even
        # when the test never enters the CLs branch — the dispatcher
        # references these attributes during type-narrowing setup.
        self._changespec_grouping_mode = ChangeSpecGroupingMode.BY_PROJECT
        self._changespec_group_fold_registries: dict[
            ChangeSpecGroupingMode, GroupFoldRegistry
        ] = {ChangeSpecGroupingMode.BY_PROJECT: GroupFoldRegistry()}
        self._changespec_group_fold_registry = self._changespec_group_fold_registries[
            ChangeSpecGroupingMode.BY_PROJECT
        ]
        self._current_changespec_group_key: tuple[str, ...] | None = None
        self.refilter_calls = 0
        self.scroll_calls = 0
        self.refresh_calls = 0
        self.notifications: list[str] = []

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_calls += 1

    def _refresh_display(self) -> None:
        self.refresh_calls += 1

    def action_scroll_to_top(self) -> None:
        self.scroll_calls += 1

    def notify(self, message: str, **kwargs: Any) -> None:  # pragma: no cover
        self.notifications.append(message)


def _agent(
    *,
    cl_name: str = "demo",
    project: str = "proj",
    status: str = "RUNNING",
    start_time: datetime | None = datetime(2026, 4, 25, 12, 0, 0),
    wait_until: str | None = None,
    retried_as_timestamp: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=f"/r/{project}/proj.gp",
        status=status,
        start_time=start_time,
        wait_until=wait_until,
        retried_as_timestamp=retried_as_timestamp,
    )


# ---------------------------------------------------------------------------
# Cycle order + wrap
# ---------------------------------------------------------------------------


def test_cycle_advances_standard_to_by_date() -> None:
    app = _StubApp([_agent()])
    app.action_cycle_grouping_mode()
    assert app._grouping_mode is GroupingMode.BY_DATE
    assert app.refilter_calls == 1


def test_cycle_advances_by_date_to_by_status() -> None:
    app = _StubApp([_agent()])
    app._grouping_mode = GroupingMode.BY_DATE
    app._group_fold_registry = app._ensure_mode_registry(GroupingMode.BY_DATE)
    app.action_cycle_grouping_mode()
    assert app._grouping_mode is GroupingMode.BY_STATUS
    assert app.refilter_calls == 1


def test_cycle_wraps_back_to_standard() -> None:
    app = _StubApp([_agent()])
    app._grouping_mode = GroupingMode.BY_STATUS
    app._group_fold_registry = app._ensure_mode_registry(GroupingMode.BY_STATUS)
    app.action_cycle_grouping_mode()
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app.refilter_calls == 1


def test_three_cycles_returns_to_standard() -> None:
    app = _StubApp([_agent()])
    app.action_cycle_grouping_mode()
    app.action_cycle_grouping_mode()
    app.action_cycle_grouping_mode()
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app.refilter_calls == 3


# ---------------------------------------------------------------------------
# Per-mode fold registry preservation
# ---------------------------------------------------------------------------


def test_fold_state_preserved_after_cycle_round_trip() -> None:
    """Collapse a STANDARD-mode banner; cycle through and back; collapse persists."""
    a = _agent(cl_name="cl-a", project="projA")
    b = _agent(cl_name="cl-b", project="projB")
    app = _StubApp([a, b])
    standard_registry = app._group_fold_registries[GroupingMode.STANDARD]
    standard_registry.collapse(("projA",))
    assert standard_registry.is_collapsed(("projA",))

    app.action_cycle_grouping_mode()  # → BY_DATE
    assert app._grouping_mode is GroupingMode.BY_DATE
    by_date_registry = app._group_fold_registry
    assert by_date_registry is not standard_registry
    # Fresh registry: STANDARD's collapse intent does not bleed across modes.
    assert by_date_registry.is_collapsed(("projA",)) is False

    by_date_registry.collapse(("Today",))

    app.action_cycle_grouping_mode()  # → BY_STATUS
    app.action_cycle_grouping_mode()  # → STANDARD
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._group_fold_registry is standard_registry
    assert app._group_fold_registry.is_collapsed(("projA",)) is True

    # And the BY_DATE registry still holds its own collapse.
    app.action_cycle_grouping_mode()  # → BY_DATE
    assert app._group_fold_registry is by_date_registry
    assert app._group_fold_registry.is_collapsed(("Today",)) is True


def test_per_mode_registry_dict_grows_lazily() -> None:
    app = _StubApp([_agent()])
    assert set(app._group_fold_registries) == {GroupingMode.STANDARD}
    app.action_cycle_grouping_mode()  # → BY_DATE
    assert set(app._group_fold_registries) == {
        GroupingMode.STANDARD,
        GroupingMode.BY_DATE,
    }
    app.action_cycle_grouping_mode()  # → BY_STATUS
    assert set(app._group_fold_registries) == set(GroupingMode)


# ---------------------------------------------------------------------------
# Banner focus is reset on cycle
# ---------------------------------------------------------------------------


def test_cycle_clears_current_group_key() -> None:
    """Banner focus from the previous mode is meaningless in the new mode."""
    app = _StubApp([_agent()])
    app._current_group_key = ("projA",)
    app.action_cycle_grouping_mode()
    assert app._current_group_key is None


# ---------------------------------------------------------------------------
# Tree shape after cycling
# ---------------------------------------------------------------------------


def test_tree_shape_changes_when_mode_changes() -> None:
    """Cycling to BY_DATE swaps the L0 banner from project to date bucket."""
    a = _agent(cl_name="cl-a", project="projA")
    app = _StubApp([a])
    now = datetime(2026, 4, 25, 18, 0, 0)
    standard_keys = enumerate_group_keys(app._agents, mode=app._grouping_mode, now=now)
    assert ("projA",) in standard_keys

    app.action_cycle_grouping_mode()  # → BY_DATE
    by_date_keys = enumerate_group_keys(app._agents, mode=app._grouping_mode, now=now)
    # L0 is now a date bucket, not a project name.
    assert ("Today",) in by_date_keys
    assert ("projA",) not in by_date_keys


def test_build_tree_after_cycle_uses_active_mode_registry() -> None:
    """A collapse persisted in BY_DATE only suppresses agents while in BY_DATE."""
    a = _agent(cl_name="cl-a", project="projA")
    app = _StubApp([a])
    now = datetime(2026, 4, 25, 18, 0, 0)

    app.action_cycle_grouping_mode()  # → BY_DATE
    app._group_fold_registry.collapse(("Today",))
    by_date_tree = build_agent_tree(
        app._agents,
        fold_registry=app._group_fold_registry,
        mode=app._grouping_mode,
        now=now,
    )
    # The single agent is hidden under the collapsed Today banner.
    agent_rows = [e for e in by_date_tree if e.kind == "agent"]
    assert agent_rows == []

    app.action_cycle_grouping_mode()  # → BY_STATUS — fresh registry
    by_status_tree = build_agent_tree(
        app._agents,
        fold_registry=app._group_fold_registry,
        mode=app._grouping_mode,
        now=now,
    )
    agent_rows = [e for e in by_status_tree if e.kind == "agent"]
    # New mode, no collapse intent — agent reappears.
    assert len(agent_rows) == 1


# ---------------------------------------------------------------------------
# Non-agents tab dispatch
# ---------------------------------------------------------------------------


def test_cycle_on_changespecs_tab_does_not_touch_agents_state() -> None:
    """CLs cycle goes through the CL branch; Agents grouping stays put."""
    app = _StubApp([_agent()], current_tab="changespecs")
    app.action_cycle_grouping_mode()
    assert app.scroll_calls == 0
    assert app.refilter_calls == 0
    assert app._grouping_mode is GroupingMode.STANDARD


def test_cycle_on_axe_tab_is_silent_noop() -> None:
    app = _StubApp([_agent()], current_tab="axe")
    app.action_cycle_grouping_mode()
    assert app.scroll_calls == 0
    assert app.refilter_calls == 0
    assert app.refresh_calls == 0
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT


# ---------------------------------------------------------------------------
# Persistence on cycle
# ---------------------------------------------------------------------------


def test_cycle_persists_new_mode(tmp_path: Path) -> None:
    """After cycling, the new mode is written to disk."""
    test_file = tmp_path / "grouping_mode.txt"
    with patch("sase.ace.grouping_mode_state._GROUPING_MODE_FILE", test_file):
        app = _StubApp([_agent()])
        app.action_cycle_grouping_mode()
        assert test_file.read_text() == GroupingMode.BY_DATE.value


# ---------------------------------------------------------------------------
# Reverse cycle (`O`)
# ---------------------------------------------------------------------------


def test_reverse_cycle_advances_standard_to_by_status() -> None:
    app = _StubApp([_agent()])
    app.action_cycle_grouping_mode_reverse()
    assert app._grouping_mode is GroupingMode.BY_STATUS
    assert app.refilter_calls == 1


def test_reverse_cycle_advances_by_status_to_by_date() -> None:
    app = _StubApp([_agent()])
    app._grouping_mode = GroupingMode.BY_STATUS
    app._group_fold_registry = app._ensure_mode_registry(GroupingMode.BY_STATUS)
    app.action_cycle_grouping_mode_reverse()
    assert app._grouping_mode is GroupingMode.BY_DATE
    assert app.refilter_calls == 1


def test_reverse_cycle_wraps_back_to_standard() -> None:
    app = _StubApp([_agent()])
    app._grouping_mode = GroupingMode.BY_DATE
    app._group_fold_registry = app._ensure_mode_registry(GroupingMode.BY_DATE)
    app.action_cycle_grouping_mode_reverse()
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app.refilter_calls == 1


def test_three_reverse_cycles_returns_to_standard() -> None:
    app = _StubApp([_agent()])
    app.action_cycle_grouping_mode_reverse()
    app.action_cycle_grouping_mode_reverse()
    app.action_cycle_grouping_mode_reverse()
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app.refilter_calls == 3


def test_forward_then_reverse_returns_to_standard() -> None:
    app = _StubApp([_agent()])
    app.action_cycle_grouping_mode()
    app.action_cycle_grouping_mode_reverse()
    assert app._grouping_mode is GroupingMode.STANDARD


def test_reverse_cycle_on_axe_tab_is_silent_noop() -> None:
    app = _StubApp([_agent()], current_tab="axe")
    app.action_cycle_grouping_mode_reverse()
    assert app.refilter_calls == 0
    assert app.refresh_calls == 0
    assert app._grouping_mode is GroupingMode.STANDARD

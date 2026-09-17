"""Tests for the Agents-tab grouping-mode selection action.

The Agents tab now chooses a grouping mode directly. The old cycle actions
remain for Artifacts/Patches but are no-ops on Agents.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agents._grouping import AgentGroupingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    build_agent_tree,
    enumerate_group_keys,
)
from sase.ace.tui.models.patch_groups import PatchGroupingMode
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
        # Patch-side state is required by the action's tab dispatch even
        # when the test never enters the Patches branch — the dispatcher
        # references these attributes during type-narrowing setup.
        self._patch_grouping_mode = PatchGroupingMode.BY_PROJECT
        self._patch_group_fold_registries: dict[
            PatchGroupingMode, GroupFoldRegistry
        ] = {PatchGroupingMode.BY_PROJECT: GroupFoldRegistry()}
        self._patch_group_fold_registry = self._patch_group_fold_registries[
            PatchGroupingMode.BY_PROJECT
        ]
        self._current_patch_group_key: tuple[str, ...] | None = None
        self.refilter_calls = 0
        self.scroll_calls = 0
        self.refresh_calls = 0
        self.notifications: list[str] = []
        self.scheduled: list[Any] = []

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_calls += 1

    def _refresh_display(self) -> None:
        self.refresh_calls += 1

    def action_scroll_to_top(self) -> None:
        self.scroll_calls += 1

    def notify(self, message: str, **kwargs: Any) -> None:  # pragma: no cover
        self.notifications.append(message)

    def call_later(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        self.scheduled.append((callback, args, kwargs))

    def _spawn_grouping_mode_save_task(self, target: str, coro_factory: Any) -> None:
        del target
        self.scheduled.append((coro_factory, (), {}))


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
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=start_time,
        wait_until=wait_until,
        retried_as_timestamp=retried_as_timestamp,
    )


# ---------------------------------------------------------------------------
# Explicit selection
# ---------------------------------------------------------------------------


def test_set_grouping_mode_changes_standard_to_by_date() -> None:
    app = _StubApp([_agent()])
    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    assert app._grouping_mode is GroupingMode.BY_DATE
    assert app.refilter_calls == 1


def test_set_grouping_mode_changes_by_date_to_by_status() -> None:
    app = _StubApp([_agent()])
    app._grouping_mode = GroupingMode.BY_DATE
    app._group_fold_registry = app._ensure_mode_registry(GroupingMode.BY_DATE)
    app._set_agents_grouping_mode(GroupingMode.BY_STATUS)
    assert app._grouping_mode is GroupingMode.BY_STATUS
    assert app.refilter_calls == 1


def test_set_grouping_mode_changes_by_machine_to_standard() -> None:
    app = _StubApp([_agent()])
    app._grouping_mode = GroupingMode.BY_MACHINE
    app._group_fold_registry = app._ensure_mode_registry(GroupingMode.BY_MACHINE)
    app._set_agents_grouping_mode(GroupingMode.STANDARD)
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app.refilter_calls == 1


def test_set_grouping_mode_changes_by_status_to_by_machine() -> None:
    app = _StubApp([_agent()])
    app._grouping_mode = GroupingMode.BY_STATUS
    app._group_fold_registry = app._ensure_mode_registry(GroupingMode.BY_STATUS)
    app._set_agents_grouping_mode(GroupingMode.BY_MACHINE)
    assert app._grouping_mode is GroupingMode.BY_MACHINE
    assert app.refilter_calls == 1


def test_setting_current_grouping_mode_is_strict_noop() -> None:
    app = _StubApp([_agent()])
    app._set_agents_grouping_mode(GroupingMode.STANDARD)
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app.refilter_calls == 0
    assert app.notifications == []
    assert app.scheduled == []


def test_old_cycle_actions_are_noops_on_agents() -> None:
    app = _StubApp([_agent()])
    app.action_cycle_grouping_mode()
    app.action_cycle_grouping_mode_reverse()
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app.refilter_calls == 0
    assert app.notifications == []
    assert app.scheduled == []


# ---------------------------------------------------------------------------
# Per-mode fold registry preservation
# ---------------------------------------------------------------------------


def test_fold_state_preserved_after_mode_round_trip() -> None:
    """Collapse a STANDARD-mode banner; switch away and back; collapse persists."""
    a = _agent(cl_name="cl-a", project="projA")
    b = _agent(cl_name="cl-b", project="projB")
    app = _StubApp([a, b])
    standard_registry = app._group_fold_registries[GroupingMode.STANDARD]
    standard_registry.collapse(("projA",))
    assert standard_registry.is_collapsed(("projA",))

    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    assert app._grouping_mode is GroupingMode.BY_DATE
    by_date_registry = app._group_fold_registry
    assert by_date_registry is not standard_registry
    # Fresh registry: STANDARD's collapse intent does not bleed across modes.
    assert by_date_registry.is_collapsed(("projA",)) is False

    by_date_registry.collapse(("Today",))

    app._set_agents_grouping_mode(GroupingMode.BY_STATUS)
    app._set_agents_grouping_mode(GroupingMode.BY_MACHINE)
    app._set_agents_grouping_mode(GroupingMode.STANDARD)
    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._group_fold_registry is standard_registry
    assert app._group_fold_registry.is_collapsed(("projA",)) is True

    # And the BY_DATE registry still holds its own collapse.
    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    assert app._group_fold_registry is by_date_registry
    assert app._group_fold_registry.is_collapsed(("Today",)) is True


def test_per_mode_registry_dict_grows_lazily() -> None:
    app = _StubApp([_agent()])
    assert set(app._group_fold_registries) == {GroupingMode.STANDARD}
    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    assert set(app._group_fold_registries) == {
        GroupingMode.STANDARD,
        GroupingMode.BY_DATE,
    }
    app._set_agents_grouping_mode(GroupingMode.BY_STATUS)
    assert set(app._group_fold_registries) == {
        GroupingMode.STANDARD,
        GroupingMode.BY_DATE,
        GroupingMode.BY_STATUS,
    }
    app._set_agents_grouping_mode(GroupingMode.BY_MACHINE)
    assert set(app._group_fold_registries) == set(GroupingMode)


# ---------------------------------------------------------------------------
# Banner focus is reset on mode changes
# ---------------------------------------------------------------------------


def test_grouping_mode_change_clears_current_group_key() -> None:
    """Banner focus from the previous mode is meaningless in the new mode."""
    app = _StubApp([_agent()])
    app._current_group_key = ("projA",)
    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    assert app._current_group_key is None


# ---------------------------------------------------------------------------
# Tree shape after changing mode
# ---------------------------------------------------------------------------


def test_tree_shape_changes_when_mode_changes() -> None:
    """BY_DATE swaps the L0 banner from project to date bucket."""
    a = _agent(cl_name="cl-a", project="projA")
    app = _StubApp([a])
    now = datetime(2026, 4, 25, 18, 0, 0)
    standard_keys = enumerate_group_keys(app._agents, mode=app._grouping_mode, now=now)
    assert ("projA",) in standard_keys

    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    by_date_keys = enumerate_group_keys(app._agents, mode=app._grouping_mode, now=now)
    # L0 is now a date bucket, not a project name.
    assert ("Today",) in by_date_keys
    assert ("projA",) not in by_date_keys


def test_build_tree_after_mode_change_uses_active_mode_registry() -> None:
    """A collapse persisted in BY_DATE only suppresses agents while in BY_DATE."""
    a = _agent(cl_name="cl-a", project="projA")
    app = _StubApp([a])
    now = datetime(2026, 4, 25, 18, 0, 0)

    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
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

    app._set_agents_grouping_mode(GroupingMode.BY_STATUS)
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


def test_cycle_on_patches_tab_does_not_touch_agents_state() -> None:
    """Patches cycle goes through the PR branch; Agents grouping stays put."""
    app = _StubApp([_agent()], current_tab="patches")
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
    assert app._patch_grouping_mode is PatchGroupingMode.BY_PROJECT


# ---------------------------------------------------------------------------
# Persistence on selection
# ---------------------------------------------------------------------------


def test_selection_schedules_grouping_mode_save(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Selecting schedules persistence without writing on the key path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    app = _StubApp([_agent()])
    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    assert app._grouping_mode is GroupingMode.BY_DATE
    assert not (tmp_path / ".sase" / "grouping_mode.txt").exists()

    callback, args, kwargs = app.scheduled[0]
    assert args == ()
    assert kwargs == {}
    asyncio.run(callback())
    assert (tmp_path / ".sase" / "grouping_mode.txt").read_text() == "by_date\n"


def test_rapid_agent_selections_save_latest_mode() -> None:
    app = _StubApp([_agent()])
    saved: list[tuple[str, object]] = []

    def _save_now(target: str, mode: object) -> bool:
        saved.append((target, mode))
        return True

    app._save_grouping_mode_now = _save_now  # type: ignore[method-assign]

    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    app._set_agents_grouping_mode(GroupingMode.BY_STATUS)
    app._set_agents_grouping_mode(GroupingMode.BY_MACHINE)
    app._set_agents_grouping_mode(GroupingMode.STANDARD)

    assert len(app.scheduled) == 1
    callback, args, kwargs = app.scheduled.pop(0)
    assert args == ()
    assert kwargs == {}
    asyncio.run(callback())
    assert saved == [("agents", GroupingMode.BY_DATE)]

    assert len(app.scheduled) == 1
    callback, _, _ = app.scheduled.pop(0)
    asyncio.run(callback())
    assert saved == [
        ("agents", GroupingMode.BY_DATE),
        ("agents", GroupingMode.STANDARD),
    ]


def test_latest_agent_grouping_save_failure_warns() -> None:
    app = _StubApp([_agent()])

    def _save_now(target: str, mode: object) -> bool:
        del target, mode
        return False

    app._save_grouping_mode_now = _save_now  # type: ignore[method-assign]

    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    callback, _, _ = app.scheduled.pop(0)
    asyncio.run(callback())

    assert app.notifications[-1] == "Could not save Agents grouping preference"


def test_stale_agent_grouping_save_failure_is_suppressed() -> None:
    app = _StubApp([_agent()])

    def _save_now(target: str, mode: object) -> bool:
        del target, mode
        return False

    app._save_grouping_mode_now = _save_now  # type: ignore[method-assign]

    app._set_agents_grouping_mode(GroupingMode.BY_DATE)
    app._set_agents_grouping_mode(GroupingMode.BY_STATUS)
    callback, _, _ = app.scheduled.pop(0)
    asyncio.run(callback())

    assert "Could not save Agents grouping preference" not in app.notifications


# ---------------------------------------------------------------------------
def test_reverse_cycle_on_axe_tab_is_silent_noop() -> None:
    app = _StubApp([_agent()], current_tab="axe")
    app.action_cycle_grouping_mode_reverse()
    assert app.refilter_calls == 0
    assert app.refresh_calls == 0
    assert app._grouping_mode is GroupingMode.STANDARD

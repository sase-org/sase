"""Dismissing a clan container must hide family members and monitor shells."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.modals import ConfirmDismissAllModal
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin

_CLAN = "sase-ps"
_GENERATION = "20260818102050"
_START = datetime(2026, 8, 18, 10, 20, 50)
_STOP = datetime(2026, 8, 18, 12, 0, 0)


def _done_row(
    name: str,
    suffix: str,
    *,
    parent_timestamp: str | None = None,
    agent_family_role: str | None = None,
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/project.sase",
        status="DONE",
        start_time=_START,
        stop_time=_STOP,
        pid=None,
        raw_suffix=suffix,
        parent_timestamp=parent_timestamp,
        parent_workflow=None,
        agent_family_parallel=False,
        agent_clan=_CLAN,
        agent_clan_generation=_GENERATION,
        agent_name=name,
        agent_family_role=agent_family_role,
        role_suffix=role_suffix,
    )


class _ClanDismissApp(TrackedProcRecorderMixin, AgentsMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._init_tracked_task_recorder()
        self.current_tab = "agents"
        self.current_idx = 0
        self._kill_persistence_inflight: set[Any] = set()
        self._agent_status_overrides: dict[Any, Any] = {}
        self._dismissed_agents: set[Any] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._marked_agents: set[Any] = set()
        self._marked_agent_order: list[Any] = []
        self._current_group_key = None
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._scheduled: list[tuple[object, tuple[object, ...]]] = []
        self.refresh_calls: list[tuple[bool, bool]] = []
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.cleanup_payloads: list[dict[str, Any]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, modal: object, callback: object = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        self.refresh_calls.append((list_changed, defer_detail))

    def _refilter_agents(self, **_kwargs: object) -> None:
        return

    def _schedule_agents_async_refresh(self, **_kwargs: object) -> None:
        return

    def call_later(self, callback: object, *args: object) -> None:
        self._scheduled.append((callback, args))

    def _submit_cleanup_proc(self, **kwargs: Any) -> bool:
        payload = kwargs.get("payload")
        self.cleanup_payloads.append(dict(payload or {}))
        return super()._submit_cleanup_proc(**kwargs)


def test_action_kill_agent_on_clan_container_dismisses_family_and_monitor() -> None:
    plan_root = _done_row("sase-ps.plan", "20260818102050")
    family_root = _done_row(
        "sase-ps.plan--1",
        "20260818114621",
        parent_timestamp="20260818102050",
        agent_family_role="root",
        role_suffix="--1",
    )
    monitor = _done_row(
        "sase-ps.plan--mon",
        "20260818114457",
        parent_timestamp="20260818114621",
        agent_family_role="monitor",
        role_suffix="--mon",
    )
    projected = project_clan_tree([plan_root, family_root, monitor])
    container = next(agent for agent in projected if agent.is_clan_container)
    app = _ClanDismissApp(projected)
    app.current_idx = projected.index(container)

    app.action_kill_agent()
    assert app.pushed_modals
    assert isinstance(app.pushed_modals[0], ConfirmDismissAllModal)
    app.pushed_callbacks[0](True)

    dismissed = app._dismissed_agents
    assert plan_root.identity in dismissed
    assert family_root.identity in dismissed
    assert monitor.identity in dismissed

    remaining = project_clan_tree(app._agents_with_children)
    assert not any(
        agent.is_clan_container and agent.agent_clan == _CLAN for agent in remaining
    )
    assert remaining == []

    assert app.cleanup_payloads
    payload_identities = {
        (item[1], item[2]) for item in app.cleanup_payloads[0]["dismissed_identities"]
    }
    assert payload_identities >= {
        (plan_root.cl_name, plan_root.raw_suffix),
        (family_root.cl_name, family_root.raw_suffix),
        (monitor.cl_name, monitor.raw_suffix),
    }

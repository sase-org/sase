"""Shared harness for the ``test_agents_bead_warmup_*`` test modules.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_bead_warmup import AgentBeadWarmupMixin
from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bead import _BEAD_DISPLAY_CACHE
from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.bead.model import Issue

__all__ = [
    "FakeApp",
    "clear_bead_display_cache",
    "confirmed_lookup",
    "make_agent",
]


@pytest.fixture(autouse=True)
def clear_bead_display_cache() -> Iterator[None]:
    _BEAD_DISPLAY_CACHE.clear()
    _WAIT_BEAD_STATUS_CACHE.clear()
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    _BEAD_DISPLAY_CACHE.clear()
    _WAIT_BEAD_STATUS_CACHE.clear()
    agent_stranded._STRANDED_REPORT_CACHE.clear()


class FakeApp(AgentBeadWarmupMixin):
    def __init__(self) -> None:
        self._agents_first_load_done = True
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scan_running = False
        self._bead_warmup_scan_pending = False
        self._bead_warmup_scan_source = "unknown"
        self._bead_warmup_async_tasks: set[asyncio.Task[None]] = set()
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Any]] = []
        self._patched: list[Agent] = []
        self._patch_kwargs: list[dict[str, object]] = []
        self._refresh_calls: list[dict[str, object]] = []
        self._patch_success = True

    def call_later(self, callback: Any) -> None:
        self._scheduled.append(callback)

    def set_timer(self, delay: float, callback: Any) -> None:
        self._timer_calls.append((delay, callback))

    def _try_patch_agent_row(self, agent: Agent, **kwargs: object) -> bool:
        self._patched.append(agent)
        self._patch_kwargs.append(kwargs)
        return self._patch_success

    def _refresh_agents_display(self, **kwargs: object) -> None:
        self._refresh_calls.append(kwargs)


def make_agent(
    *,
    agent_name: str | None = "sase-x.3",
    cl_name: str = "feat",
    raw_suffix: str = "20260615190000",
    status: str = "RUNNING",
    project_file: str = "/tmp/proj/proj.sase",
    workspace_dir: str | None = "/tmp/ws",
    epic_bead_id: str | None = None,
    phase_bead_id: str | None = None,
    waiting_for_beads: list[str] | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
        epic_bead_id=epic_bead_id,
        phase_bead_id=phase_bead_id,
        waiting_for_beads=waiting_for_beads or [],
    )


def confirmed_lookup(candidate_id: str, **_: object) -> Issue:
    return Issue(id=candidate_id, title="", description="")

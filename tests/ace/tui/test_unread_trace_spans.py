"""Trace-span coverage for unread instrumentation (phase sase-1d7.3).

Fast deterministic checks that each span the phase adds actually emits
with its workload counters. Key-to-paint capture for ``,u`` / ``,j`` /
``,J`` is covered by the slow benches in ``bench_tui_jk_unread.py``,
which assert ``,u`` / ``,j`` samples exist per branch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.actions.agents._notification_unread_projection import (
    AgentNotificationUnreadMixin,
)
from sase.ace.tui.actions.agents._unread_state import (
    AgentUnreadStateMixin,
    _UnreadNotificationDismissal,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_nodes import agent_node_projection_index
from sase.notifications import Notification
from sase.ace.tui.actions.agents._notification_utils import (
    unread_completion_index_rows_from_notifications as _rows,
)

from ._agent_unread_helpers import make_agent
from ._leader_keymap_helpers import _FakeApp


@pytest.fixture
def _trace_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    trace_path = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(trace_path))
    return trace_path


def _spans(trace_path: Path) -> list[dict[str, object]]:
    from sase.ace.tui.util.trace import _flush_trace_writes

    _flush_trace_writes()
    if not trace_path.exists():
        return []
    return [
        json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()
    ]


def _one_span(trace_path: Path, name: str) -> dict[str, object]:
    matches = [s for s in _spans(trace_path) if s.get("span") == name]
    assert matches, (
        f"missing {name} span; saw {[s.get('span') for s in _spans(trace_path)]}"
    )
    return matches[0]


def test_projection_index_span(_trace_file: Path) -> None:
    """agent_node_projection_index emits with roster/node counters."""
    agents = [
        make_agent(name=f"node-{i}", status="DONE", raw_suffix=f"2026050709000{i}")
        for i in range(3)
    ]
    agent_node_projection_index(agents)
    span = _one_span(_trace_file, "agent_nodes.projection_index")
    assert span["loaded_agents"] == 3
    assert span["nodes"] == 3


class _SpanReconcileApp(AgentNotificationUnreadMixin):
    def __init__(self, agents: list[object]) -> None:
        self._agents = agents
        self._agents_with_children = list(agents)
        self.current_tab = "agents"
        self._unread_completed_agent_ids: set[object] = set()
        self._manual_unread_agent_ids: set[object] = set()
        self._agent_info_metrics_cache = None


def _completion_notification() -> Notification:
    return Notification(
        id="span-test",
        timestamp="2026-05-07T09:00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={"cl_name": "demo", "raw_suffix": "20260507090000"},
        dismissed=False,
        silent=False,
    )


def test_reconcile_span(_trace_file: Path) -> None:
    """Unread reconcile emits with roster/unread counters."""
    agent = make_agent(name="demo", status="DONE", raw_suffix="20260507090000")
    app = _SpanReconcileApp([agent])  # type: ignore[arg-type]
    app._reconcile_unread_from_completion_notifications(
        _rows([_completion_notification()])
    )
    span = _one_span(_trace_file, "unread.reconcile")
    assert span["loaded_agents"] == 1
    assert span["unread"] == 1
    assert agent.identity in app._unread_completed_agent_ids


class _SpanAckApp(AgentUnreadStateMixin):
    def __init__(self) -> None:
        self.notify_calls: list[str] = []
        self.refresh_count = 0
        self.scheduled_resync_count = 0

    def _remove_agent_completion_notifications_from_cache(self, agents: object) -> int:
        del agents
        return 0

    def _remove_agent_completion_notifications_from_cache_by_ids(
        self, ids: object
    ) -> int:
        del ids
        return 0

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def _schedule_notification_snapshot_refresh(self) -> None:
        self.scheduled_resync_count += 1

    def notify(self, message: str, **_: object) -> None:
        self.notify_calls.append(message)


def test_ack_complete_span_reports_worker_stat(_trace_file: Path) -> None:
    """Ack completion emits the worker-thread store size without stat-ing."""
    app = _SpanAckApp()
    request = _UnreadNotificationDismissal(
        agents=(),
        keys=(("demo", "20260507090000"),),
        identities=frozenset({(AgentType.RUNNING, "demo", "20260507090000")}),
        restore_manual_ids=frozenset(),
        prior_pending_bulk_read_ids=None,
    )
    app._complete_unread_notification_dismissal(
        request, dismissed_count=0, error=None, store_bytes=1234
    )
    span = _one_span(_trace_file, "unread.ack_complete")
    assert span["targets"] == 1
    assert span["store_bytes"] == 1234


def test_leader_bulk_ack_span(_trace_file: Path) -> None:
    """Leader ,u dispatch emits the bulk-ack span."""
    app = _FakeApp(current_tab="agents")
    keys = app._keymap_registry.leader_mode.keys
    subkey = keys["mark_all_unread_done_agents_read"]
    assert isinstance(subkey, str)
    assert app._handle_leader_key(subkey) is True
    span = _one_span(_trace_file, "leader.unread_bulk_ack")
    assert span["targets"] == 0
    assert app.mark_all_unread_count == 1


def test_leader_jump_span(_trace_file: Path) -> None:
    """Leader ,j dispatch emits the jump span."""
    app = _FakeApp(current_tab="agents")
    keys = app._keymap_registry.leader_mode.keys
    subkey = keys["jump_to_next_unread_done_agent"]
    assert isinstance(subkey, str)
    assert app._handle_leader_key(subkey) is True
    span = _one_span(_trace_file, "leader.unread_jump")
    assert span["action"] == ",j"
    assert app.jump_unread_count == 1

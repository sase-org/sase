"""Painted AgentList row order must stay in sync with j/k nav stops.

Held Agent objects are shared and mutated in place. Gates that re-read
those objects cannot see that the widget still shows the previous grouping
tree. These tests pin the immutable painted-facts snapshot, hydration
preservation for mirrored session roots, and j/k self-heal on cache miss.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agents._navigation_order import AgentNavigationOrderMixin
from sase.ace.tui.models._projected_record import apply_projected_agent_record
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode, status_bucket_for
from sase.ace.tui.widgets._agent_list_styling import BANNER_ROW
from sase.ace.tui.widgets.agent_list import AgentList
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
)

from ._agent_display_diff_helpers import _DisplayDiffApp, _agent
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    make_agent_session,
)


class _NavDiffApp(AgentNavigationOrderMixin, _DisplayDiffApp):
    """Display harness with the real nav-stop walk and a no-op debounce."""

    def _refresh_agents_display_debounced(self) -> None:
        self.debounce_calls = getattr(self, "debounce_calls", 0) + 1


def _by_status_app(agents: list[Agent], monkeypatch: Any) -> _DisplayDiffApp:
    app = _DisplayDiffApp(agents, monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agents_refresh_trace_records.clear()
    return app


def _by_status_nav_app(agents: list[Agent], monkeypatch: Any) -> _NavDiffApp:
    app = _NavDiffApp(agents, monkeypatch)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._refresh_panel_widgets(jump_hints=None)
    app._agents_refresh_trace_records.clear()
    app._nav_stops_cache = None
    return app


def _timed(name: str, status: str, minute: int) -> Agent:
    agent = _agent(
        name,
        tribe=None,
        suffix=f"2026060812{minute:02d}00",
        status=status,
    )
    agent.start_time = datetime(2026, 6, 8, 12, minute, 0)
    return agent


def _video_roster() -> tuple[Agent, Agent, Agent, Agent]:
    """A newest Running, W Waiting, D1/D2 older Done — the screencast shape."""
    alpha = _timed("alpha", "RUNNING", 30)
    waiting = _timed("wait", "WAITING", 20)
    done1 = _timed("done1", "DONE", 10)
    done2 = _timed("done2", "DONE", 5)
    return alpha, waiting, done1, done2


def _panel_widget(app: _DisplayDiffApp) -> AgentList:
    return app.query_one("#agent-list-panel")


def _painted_names(widget: AgentList) -> list[str]:
    names: list[str] = []
    for local_idx, _attempt in widget._row_entries:
        if local_idx == BANNER_ROW:
            continue
        names.append(widget._agents[local_idx].agent_name or "")
    return names


def _nav_agent_names(app: _NavDiffApp) -> list[str]:
    app._nav_stops_cache = None
    stops = app._panel_navigation_stops()
    return [
        app._agents[payload].agent_name or ""
        for kind, payload in stops
        if kind == "agent" and isinstance(payload, int)
    ]


def _hydration_record(artifact_dir: str) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="session-test",
        project_dir="/tmp/projects/session",
        project_file="/tmp/session.sase",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp="20260718120000",
        agent_meta=AgentMetaWire(status_bucket="Done"),
        done=DoneMarkerWire(status_bucket="Done"),
    )


def test_panel_content_is_unchanged_detects_inplace_bucket_mutation(
    monkeypatch: Any,
) -> None:
    running = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([running], monkeypatch)
    widget = _panel_widget(app)
    paint_key = widget._panel_paint_key
    assert app._panel_content_is_unchanged(
        widget,
        [running],
        grouping_mode=GroupingMode.BY_STATUS,
        panel_collapsed=False,
        paint_key=paint_key,
    )

    running.status = "DONE"

    assert not app._panel_content_is_unchanged(
        widget,
        [running],
        grouping_mode=GroupingMode.BY_STATUS,
        panel_collapsed=False,
        paint_key=paint_key,
    )


def test_try_patch_agent_row_declines_mutated_held_running_to_done(
    monkeypatch: Any,
) -> None:
    running = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    app = _by_status_app([running], monkeypatch)
    running.status = "DONE"

    assert app._try_patch_agent_row(running) is False
    assert app._agents_refresh_trace_records[-1].fallback_reason == (
        "status_membership_change"
    )


def test_try_insert_rows_declines_mutated_retained_row(
    monkeypatch: Any,
) -> None:
    running = _agent("alpha", tribe=None, suffix="a1", status="RUNNING")
    other = _agent("beta", tribe=None, suffix="b1", status="RUNNING")
    widget = AgentList()
    monkeypatch.setattr(widget, "post_message", lambda _msg: None)
    widget.update_list([running, other], 0, grouping_mode=GroupingMode.BY_STATUS)

    running.status = "DONE"
    arrival = _agent("gamma", tribe=None, suffix="c1", status="RUNNING")

    assert (
        widget.try_insert_rows(
            [running, other, arrival], 0, grouping_mode=GroupingMode.BY_STATUS
        )
        is False
    )
    assert widget._insert_decline_reason == "panel_membership_change"


def test_mirrored_session_root_hydration_preserves_list_owned_bucket(
    tmp_path: Path,
) -> None:
    root, _child = make_agent_session(tmp_path)
    artifact_dir = "/tmp/projects/session/artifacts/ace-run/20260718120000"
    root.record_shape = "list"
    root.index_record_dir = artifact_dir
    root.status = "RUNNING"
    root.status_bucket = "Running"
    before = status_bucket_for(root)

    assert apply_projected_agent_record(
        root,
        _hydration_record(artifact_dir),
        expected_artifact_dir=artifact_dir,
    )
    assert root.is_agent_session_container_row is True
    assert root.status_bucket == "Running"
    assert status_bucket_for(root) == before


def test_plain_row_hydration_may_overwrite_status_bucket() -> None:
    artifact_dir = "/tmp/projects/plain/artifacts/ace-run/20260718120000"
    agent = _agent("plain", tribe=None, suffix="p1", status="RUNNING")
    agent.record_shape = "list"
    agent.index_record_dir = artifact_dir

    assert apply_projected_agent_record(
        agent,
        _hydration_record(artifact_dir),
        expected_artifact_dir=artifact_dir,
    )
    assert agent.status_bucket == "Done"
    assert status_bucket_for(agent) == "Done"


def test_hydration_bucket_change_fails_painted_content_gate(
    monkeypatch: Any,
) -> None:
    artifact_dir = "/tmp/projects/plain/artifacts/ace-run/20260718120000"
    agent = _agent("plain", tribe=None, suffix="p1", status="RUNNING")
    agent.record_shape = "list"
    agent.index_record_dir = artifact_dir
    app = _by_status_app([agent], monkeypatch)
    widget = _panel_widget(app)
    paint_key = widget._panel_paint_key

    assert apply_projected_agent_record(
        agent,
        _hydration_record(artifact_dir),
        expected_artifact_dir=artifact_dir,
    )
    assert not app._panel_content_is_unchanged(
        widget,
        [agent],
        grouping_mode=GroupingMode.BY_STATUS,
        panel_collapsed=False,
        paint_key=paint_key,
    )


def test_jk_self_heal_rebuilds_when_painted_order_drifted(
    monkeypatch: Any,
) -> None:
    alpha, waiting, done1, done2 = _video_roster()
    agents = [alpha, waiting, done1, done2]
    app = _by_status_nav_app(agents, monkeypatch)
    widget = _panel_widget(app)
    assert _painted_names(widget) == ["alpha", "wait", "done1", "done2"]

    alpha.status = "DONE"
    app._nav_stops_cache = None
    app._panel_navigation_stops()

    assert any(
        record.fallback_reason == "painted_order_drift"
        for record in app._agents_refresh_trace_records
    )
    assert _painted_names(widget) == ["wait", "alpha", "done1", "done2"]
    assert _nav_agent_names(app) == ["wait", "alpha", "done1", "done2"]


def test_video_running_to_done_repaint_puts_waiting_first(
    monkeypatch: Any,
) -> None:
    alpha, waiting, done1, done2 = _video_roster()
    agents = [alpha, waiting, done1, done2]
    app = _by_status_nav_app(agents, monkeypatch)
    widget = _panel_widget(app)

    alpha.status = "DONE"
    app._refresh_panel_widgets(jump_hints=None)

    expected = ["wait", "alpha", "done1", "done2"]
    assert _painted_names(widget) == expected
    assert _nav_agent_names(app) == expected
    first_agent_stop = next(
        payload for kind, payload in app._panel_navigation_stops() if kind == "agent"
    )
    assert app._agents[first_agent_stop].agent_name == "wait"

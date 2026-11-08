"""Navigation through cached stranded agent rows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import (
    CollapsedClanJumpApp,
    LeaderUnreadJumpApp,
    UnreadJumpApp,
)


@pytest.fixture(autouse=True)
def _clear_stranded_cache():
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _owner(bead_id: str, *, stop_time: datetime | None = None):
    return replace(
        make_agent(
            name=bead_id, status="DONE", raw_suffix=bead_id, stop_time=stop_time
        ),
        phase_bead_id=bead_id,
    )


def _seed(*verdicts: StrandedWorkVerdict) -> None:
    report = StrandedWorkReport(
        verdicts=verdicts,
        stranded_ids=tuple(v.bead_id for v in verdicts if v.state == "stranded"),
        blocked_ids=tuple(v.bead_id for v in verdicts if v.state == "blocked"),
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo", StrandedReport(report=report, titles={}, generated_at=1.0), "test"
    )


def _verdict(bead_id: str, *, since: float | None, state: str = "stranded"):
    return StrandedWorkVerdict(
        bead_id=bead_id,
        kind="phase",
        state=state,
        reason="test",
        since=since,
    )


def test_stranded_jump_orders_by_since_and_cycles_newest_to_oldest() -> None:
    older = _owner("sase-demo.older", stop_time=datetime(2026, 11, 7, 12))
    newest = _owner("sase-demo.newest", stop_time=datetime(2020, 1, 1))
    running = make_agent(name="running", raw_suffix="running")
    _seed(
        _verdict("sase-demo.older", since=1_700_000_000),
        _verdict("sase-demo.newest", since=1_800_000_000),
    )
    app = LeaderUnreadJumpApp([older, newest, running], current_idx=2)

    assert app._handle_leader_key("j") is True
    assert app._agents[app.current_idx] is newest
    assert app._handle_leader_key("comma") is True
    assert app._agents[app.current_idx] is older
    assert app._handle_leader_key("comma") is True
    assert app._agents[app.current_idx] is newest
    assert app.notifications == []
    assert all(call.get("defer_detail") is True for call in app.refresh_calls)


def test_stranded_hit_does_not_land_on_main_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stranded = _owner("sase-demo.stranded")
    _seed(_verdict("sase-demo.stranded", since=1_800_000_000))
    app = UnreadJumpApp([stranded])
    calls: list[object] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._unread_navigation.land_stopped_jump_on_main_context",
        calls.append,
    )

    assert app._jump_to_next_stranded_agent()
    assert calls == []


def test_stranded_jump_reveals_member_hidden_by_collapsed_clan() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = _owner("sase-demo.hidden")
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    complete = project_clan_tree([origin, target])
    _seed(_verdict("sase-demo.hidden", since=1_800_000_000))
    app = CollapsedClanJumpApp(complete, current_identity=origin.identity)

    assert app._jump_to_next_stranded_agent()

    clan = next(agent for agent in complete if agent.is_clan_container)
    assert app._fold_manager.get(agent_fold_key(clan)).name == "EXPANDED"
    assert app._agents[app.current_idx].identity == target.identity
    assert app.refresh_calls[-1] == {"list_changed": False, "defer_detail": True}


def test_stranded_jump_uses_stop_time_when_since_is_missing() -> None:
    old = _owner("sase-demo.old", stop_time=datetime(2024, 1, 1))
    fallback_newer = _owner("sase-demo.fallback", stop_time=datetime(2025, 1, 1))
    _seed(
        _verdict("sase-demo.old", since=1_700_000_000),
        _verdict("sase-demo.fallback", since=None),
    )
    app = UnreadJumpApp([old, fallback_newer])

    assert app._jump_to_next_stranded_agent()
    assert app._agents[app.current_idx] is fallback_newer


def test_unread_and_stopped_rows_keep_priority_over_stranded_rows() -> None:
    stranded = _owner("sase-demo.stranded")
    unread = make_agent(name="unread", status="DONE", raw_suffix="unread")
    stopped = make_agent(name="stopped", status="PLAN", raw_suffix="stopped")
    _seed(_verdict("sase-demo.stranded", since=1_800_000_000))
    app = LeaderUnreadJumpApp([stranded, unread, stopped], current_idx=0)
    app._unread_completed_agent_ids.add(unread.identity)

    assert app._handle_leader_key("j") is True
    assert app._agents[app.current_idx] is unread
    app._unread_completed_agent_ids.clear()
    assert app._handle_leader_key("comma") is True
    assert app._agents[app.current_idx] is stopped


def test_blocked_and_missing_verdicts_are_skipped_and_cold_cache_misses() -> None:
    blocked = _owner("sase-demo.blocked")
    missing = _owner("sase-demo.missing")
    running = make_agent(name="running", raw_suffix="running")
    _seed(_verdict("sase-demo.blocked", since=1_800_000_000, state="blocked"))
    app = LeaderUnreadJumpApp([blocked, missing, running], current_idx=2)

    assert app._handle_leader_key("j") is True
    assert app._agents[app.current_idx] is running
    assert app.notifications == ["No unread completed, stopped, or stranded agents"]

    agent_stranded._STRANDED_REPORT_CACHE.clear()
    app.notifications.clear()
    assert app._handle_leader_key("comma") is True
    assert app.notifications == ["No unread completed, stopped, or stranded agents"]

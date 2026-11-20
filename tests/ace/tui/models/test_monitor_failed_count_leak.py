"""Failed-monitor lane leak: clan sase-19o screenshot scenario."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.actions.agents._display_panel_titles import agent_panel_counts
from sase.ace.tui.models._agent_clan import clan_member_counts, sase_agent_status_counts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_status_apply import (
    apply_status_overrides as _apply_status_overrides,
)
from sase.agent.status_buckets import agent_status_bucket
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_roster import (
    clan_roster_entries,
    ordered_clan_members,
)

_STARTED = datetime(2026, 9, 25, 16, 0, 0)
_CLAN = "sase-19o"
_GENERATION = "gen-1"


def _member(
    name: str,
    status: str,
    *,
    start_offset: int,
    status_bucket: str | None = None,
    stop_offset: int | None = None,
    role: str = "root",
    parent_timestamp: str | None = None,
    session: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/sase.sase",
        status=status,
        status_bucket=status_bucket,
        start_time=_STARTED + timedelta(minutes=start_offset),
        run_start_time=_STARTED + timedelta(minutes=start_offset),
        stop_time=(
            _STARTED + timedelta(minutes=stop_offset)
            if stop_offset is not None
            else None
        ),
        raw_suffix=f"suffix-{name}",
        parent_timestamp=parent_timestamp,
        agent_name=name,
        agent_session=session or name,
        agent_session_role=role,
        role_suffix=f"--{role}",
        agent_clan=_CLAN,
        agent_clan_generation=_GENERATION,
    )


def _failed_check_monitor(
    name: str,
    root: Agent,
    *,
    start_offset: int,
    followup_outcome: str | None = "launched",
    followup_error: str | None = None,
    followup_agent: str | None = None,
) -> Agent:
    monitor = _member(
        name,
        "TESTED",
        start_offset=start_offset,
        status_bucket="Failed",
        stop_offset=start_offset + 1,
        role="monitor",
        parent_timestamp=root.raw_suffix,
        session=root.agent_session,
    )
    monitor.monitor_id = f"m-{name}"
    monitor.monitor_state = "failed"
    monitor.monitor_start_status = "TESTING"
    monitor.monitor_stop_status = "TESTED"
    monitor.monitor_label = "just check"
    monitor.monitor_command = "just check"
    monitor.monitor_followup_outcome = followup_outcome
    monitor.monitor_followup_error = followup_error
    monitor.monitor_followup_agent = followup_agent
    return monitor


def _build_19o(*, monitor3_error: str | None = None) -> list[Agent]:
    # .2: DONE starter, failed check with launched follow-up, DONE continuation.
    root2 = _member(
        f"{_CLAN}.2", "DONE", start_offset=0, status_bucket="Done", session=f"{_CLAN}.2"
    )
    starter2 = _member(
        f"{_CLAN}.2--0",
        "DONE",
        start_offset=1,
        status_bucket="Done",
        stop_offset=2,
        role="member",
        parent_timestamp=root2.raw_suffix,
        session=root2.agent_session,
    )
    monitor2 = _failed_check_monitor(
        f"{_CLAN}.2--mon",
        root2,
        start_offset=3,
        followup_agent=f"{_CLAN}.2--1",
    )
    cont2 = _member(
        f"{_CLAN}.2--1",
        "DONE",
        start_offset=5,
        status_bucket="Done",
        stop_offset=6,
        role="member",
        parent_timestamp=root2.raw_suffix,
        session=root2.agent_session,
    )
    root2.runtime_children = [starter2, monitor2, cont2]

    # .3: DONE starter, settled failed check with launched (not yet loaded) follow-up.
    root3 = _member(
        f"{_CLAN}.3", "DONE", start_offset=0, status_bucket="Done", session=f"{_CLAN}.3"
    )
    starter3 = _member(
        f"{_CLAN}.3--0",
        "DONE",
        start_offset=1,
        status_bucket="Done",
        stop_offset=2,
        role="member",
        parent_timestamp=root3.raw_suffix,
        session=root3.agent_session,
    )
    monitor3 = _failed_check_monitor(
        f"{_CLAN}.3--mon",
        root3,
        start_offset=3,
        followup_error=monitor3_error,
    )
    root3.runtime_children = [starter3, monitor3]

    # .land: waiting on its siblings.
    land = _member(
        f"{_CLAN}.land",
        "WAITING",
        start_offset=0,
        session=f"{_CLAN}.land",
    )
    land.waiting_for = [f"{_CLAN}.2", f"{_CLAN}.3"]

    return [root2, starter2, monitor2, cont2, root3, starter3, monitor3, land]


def _project(rows: list[Agent]):
    _apply_status_overrides(rows)
    return project_clan_tree(rows)


def test_failed_check_with_launched_continuation_reports_no_failure() -> None:
    rows = _build_19o()
    projected = _project(rows)
    container = next(row for row in projected if row.is_clan_container)

    assert clan_member_counts(container).failed == 0
    assert agent_status_bucket(container) != "Failed"
    assert sase_agent_status_counts(projected, ()).failed == 0
    assert agent_panel_counts(projected, set()).failed == 0

    members = ordered_clan_members(container)
    entries = clan_roster_entries(container, members, now=_STARTED, digests=())
    by_label = {entry.label: entry for entry in entries}
    for label in (".2", ".3"):
        entry = by_label[label]
        assert entry.effective_bucket != "Failed"
        mon_children = [
            child for child in entry.children or () if child.label == "--mon"
        ]
        assert mon_children and mon_children[0].effective_bucket == "Failed"


def test_failed_check_with_followup_error_reports_failure() -> None:
    rows = _build_19o(monitor3_error="boom")
    projected = _project(rows)
    container = next(row for row in projected if row.is_clan_container)

    assert clan_member_counts(container).failed == 1
    assert sase_agent_status_counts(projected, ()).failed == 1
    assert agent_panel_counts(projected, set()).failed == 1


def _build_settle_window(*, settling: bool) -> tuple[list[Agent], Agent, Agent]:
    """Clan sase-1tz.3.1 screenshot: ``.5`` mid-settle beside a running ``.6``.

    The supervisor has persisted ``monitor_state: failed`` but not yet
    ``stopped_at``, a follow-up outcome, or ``done.json``, so the monitor row
    still reads the raw ``RUNNING`` with its command's ``Failed`` bucket.
    """
    root5 = _member(
        f"{_CLAN}.5", "DONE", start_offset=0, status_bucket="Done", session=f"{_CLAN}.5"
    )
    monitor5 = _member(
        f"{_CLAN}.5--mon",
        "RUNNING",
        start_offset=3,
        status_bucket="Failed",
        role="monitor",
        parent_timestamp=root5.raw_suffix,
        session=root5.agent_session,
    )
    monitor5.monitor_id = f"m-{_CLAN}.5--mon"
    monitor5.monitor_state = "failed"
    monitor5.monitor_start_status = "TESTING"
    monitor5.monitor_stop_status = "TESTED"
    monitor5.monitor_label = "just check"
    monitor5.monitor_command = "just check"
    monitor5.monitor_exit_code = 1
    monitor5.pid = 4242
    monitor5.monitor_settling = settling
    root5.runtime_children = [monitor5]

    sibling = _member(
        f"{_CLAN}.6",
        "RUNNING",
        start_offset=1,
        status_bucket="Running",
        session=f"{_CLAN}.6",
    )
    return [root5, monitor5, sibling], root5, monitor5


def test_settling_failed_monitor_keeps_clan_in_progress() -> None:
    rows, root5, monitor5 = _build_settle_window(settling=True)
    projected = _project(rows)
    container = next(row for row in projected if row.is_clan_container)

    assert agent_status_bucket(root5) == "Running"
    assert container.status != "FAILED"
    assert clan_member_counts(container).failed == 0
    assert sase_agent_status_counts(projected, ()).failed == 0
    assert agent_panel_counts(projected, set()).failed == 0
    # The monitor row stays truthful about its own command.
    assert agent_status_bucket(monitor5) == "Failed"


def test_unverified_settle_window_monitor_still_reports_failure() -> None:
    rows, root5, monitor5 = _build_settle_window(settling=False)
    projected = _project(rows)
    container = next(row for row in projected if row.is_clan_container)

    assert agent_status_bucket(root5) == "Failed"
    assert clan_member_counts(container).failed == 1
    assert sase_agent_status_counts(projected, ()).failed == 1
    assert agent_panel_counts(projected, set()).failed == 1
    assert agent_status_bucket(monitor5) == "Failed"

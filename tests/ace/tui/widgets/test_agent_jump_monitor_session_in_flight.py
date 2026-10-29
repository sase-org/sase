"""Jump-panel lighting for sessions whose current turn is a running monitor."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models._agent_loader_normalization import normalize_loaded_agents
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_roster import (
    clan_roster_entries,
    ordered_clan_members,
)
from sase.ace.tui.widgets.prompt_panel._member_in_flight import (
    IN_FLIGHT_RUNNING_TINT,
    is_in_flight_jump_bucket,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpNumbering,
    append_member_roster,
)

_START = datetime(2026, 10, 1, 9, 0, 0)
_NOW = datetime(2026, 10, 1, 9, 30, 0)


def _agent(name: str, **kwargs: object) -> Agent:
    fields: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/monitor-session.sase",
        "status": "DONE",
        "start_time": _START,
        "raw_suffix": f"suffix-{name}",
        "agent_name": name,
    }
    fields.update(kwargs)
    return Agent(**fields)  # type: ignore[arg-type]


def _clan_shape(
    *,
    monitor_state: str = "running",
    monitor_stop: datetime | None = None,
    monitor_parent: str = "turn",
) -> list[Agent]:
    """Return normalized clan rows with a session member running a monitor."""
    one = _agent(
        "bench.1",
        stop_time=datetime(2026, 10, 1, 9, 1, 0),
        agent_clan="bench",
        agent_clan_generation="20261001090000",
    )
    root = _agent(
        "bench.9",
        status="TALE DONE",
        agent_session="bench.9",
        agent_session_role="root",
        agent_clan="bench",
        agent_clan_generation="20261001090000",
        plan_chain_root=True,
    )
    two = _agent(
        "bench.9--2",
        status="TALE DONE",
        stop_time=datetime(2026, 10, 1, 9, 8, 0),
        parent_timestamp=root.raw_suffix,
        agent_session="bench.9",
        agent_session_role="code",
        role_suffix="--2",
    )
    monitor = _agent(
        "bench.9--mon",
        status="BUILDING" if monitor_state == "running" else "MONITORED",
        status_bucket="Running" if monitor_state == "running" else "Done",
        parent_timestamp=(
            root.raw_suffix if monitor_parent == "root" else two.raw_suffix
        ),
        agent_session="bench.9",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="m9",
        monitor_state=monitor_state,
        stop_time=monitor_stop,
    )
    return normalize_loaded_agents(
        [one, root, two, monitor], [], is_process_running=lambda _pid: False
    )


def _session_shape(*, monitor_state: str = "running") -> list[Agent]:
    """Return normalized standalone session rows with a nested monitor."""
    root = _agent(
        "solo",
        status="TALE DONE",
        agent_session="solo",
        agent_session_role="root",
        plan_chain_root=True,
    )
    two = _agent(
        "solo--2",
        status="TALE DONE",
        stop_time=datetime(2026, 10, 1, 9, 8, 0),
        parent_timestamp=root.raw_suffix,
        agent_session="solo",
        agent_session_role="code",
        role_suffix="--2",
    )
    monitor = _agent(
        "solo--mon",
        status="BUILDING" if monitor_state == "running" else "MONITORED",
        status_bucket="Running" if monitor_state == "running" else "Done",
        parent_timestamp=two.raw_suffix,
        agent_session="solo",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="m9",
        monitor_state=monitor_state,
        stop_time=(
            datetime(2026, 10, 1, 9, 20, 0) if monitor_state != "running" else None
        ),
    )
    return normalize_loaded_agents(
        [root, two, monitor], [], is_process_running=lambda _pid: False
    )


def _covering_styles(line: Text, needle: str) -> list[str]:
    start = line.plain.index(needle)
    end = start + len(needle)
    return [
        str(span.style)
        for span in line.spans
        if span.start <= start and span.end >= end
    ]


def test_clan_roster_lights_session_with_nested_running_monitor() -> None:
    ordered = _clan_shape()
    clan = ordered[0]
    entries = clan_roster_entries(
        clan, ordered_clan_members(clan), now=_NOW, digests=()
    )
    session = next(entry for entry in entries if entry.label == ".9")

    assert session.effective_bucket == "Running"
    assert session.status == "BUILDING"
    assert [child.label for child in session.children] == ["--2"]

    jump_map = append_member_roster(
        Text(),
        container_identity=clan.identity,
        entries=entries,
        title="CLAN MEMBERS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    target = next(item for item in jump_map.targets if item.label == ".9")
    assert target.status_bucket == "Running"
    assert is_in_flight_jump_bucket(target.status_bucket) is True

    lines = JumpLegendRenderable(jump_map, mode="collapsed")._lines_for_width(200)  # noqa: SLF001
    line = next(line for line in lines if ".9" in line.plain)
    assert any(
        IN_FLIGHT_RUNNING_TINT in style for style in _covering_styles(line, ".9")
    )


def test_settled_monitor_keeps_session_dim() -> None:
    ordered = _clan_shape(
        monitor_state="completed",
        monitor_stop=datetime(2026, 10, 1, 9, 20, 0),
    )
    clan = ordered[0]
    entries = clan_roster_entries(
        clan, ordered_clan_members(clan), now=_NOW, digests=()
    )
    session = next(entry for entry in entries if entry.label == ".9")

    assert session.effective_bucket == "Done"
    assert session.status == "DONE"


def test_root_parented_monitor_stays_lit() -> None:
    ordered = _clan_shape(monitor_parent="root")
    clan = ordered[0]
    entries = clan_roster_entries(
        clan, ordered_clan_members(clan), now=_NOW, digests=()
    )
    session = next(entry for entry in entries if entry.label == ".9")

    assert session.effective_bucket == "Running"


def test_tribe_units_light_running_monitor_lanes() -> None:
    clan_snapshot = build_agent_tribe_summary_snapshot(
        None, _clan_shape(), panel_collapsed=False, now=_NOW
    )
    solo_snapshot = build_agent_tribe_summary_snapshot(
        None, _session_shape(), panel_collapsed=False, now=_NOW
    )

    assert clan_snapshot.units[0].status_bucket == "Running"
    assert solo_snapshot.units[0].status_bucket == "Running"

    settled_clan = build_agent_tribe_summary_snapshot(
        None,
        _clan_shape(
            monitor_state="completed",
            monitor_stop=datetime(2026, 10, 1, 9, 20, 0),
        ),
        panel_collapsed=False,
        now=_NOW,
    )
    settled_solo = build_agent_tribe_summary_snapshot(
        None,
        _session_shape(monitor_state="completed"),
        panel_collapsed=False,
        now=_NOW,
    )
    assert settled_clan.units[0].status_bucket == "Done"
    assert settled_solo.units[0].status_bucket == "Done"

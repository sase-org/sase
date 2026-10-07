"""Tests for epic-follow state in the TUI agent model and shared view."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from sase.ace.tui.agent_completion import (
    collect_agent_wait_status_maps,
    wait_dependencies_satisfied,
    wait_dependency_status_counts,
)
from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_wait_beads import (
    WaitBeadStatusSnapshot,
    _WaitBeadStatusSnapshotEntry,
)
from sase.ace.tui.widgets._agent_list_rendering import agent_render_key
from sase.core.agent_scan_wire import AgentMetaWire, WaitingMarkerWire
from sase.core.agent_scan_wire_markers import WaitEpicFollowEntryWire
from sase.core.wait_epic_follow_view import (
    EpicFollowView,
    authored_wait_beads,
    describe_epic_follow,
    epic_follow_views,
)
from tests._enrich_agent_helpers import make_agent as make_loader_agent

from .widgets._agent_display_helpers import make_agent
from .widgets._agent_render_cache_helpers import agent as render_agent


def _follow_entry(
    target: str = "planner",
    state: str = "following",
    **overrides: object,
) -> dict[str, object]:
    entry: dict[str, object] = {"target": target, "state": state}
    entry.update(overrides)
    return entry


def _snapshot(*entries: tuple[str, str | None, bool]) -> WaitBeadStatusSnapshot:
    return WaitBeadStatusSnapshot(
        tuple(
            _WaitBeadStatusSnapshotEntry(bead_id, status, is_cold=is_cold)
            for bead_id, status, is_cold in entries
        )
    )


def _key(agent: Agent) -> tuple[object, ...]:
    return agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )


def test_filesystem_loader_reads_follow_fields(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "wait_for_epics_of": ["planner"],
                "wait_epic_follows": [
                    _follow_entry(epic_ids=["sase-7k"], added_bead_ids=["sase-7k"])
                ],
            }
        )
    )

    agent = make_loader_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_for_epics_of == ["planner"]
    assert agent.wait_epic_follows == [
        EpicFollowView(
            target="planner",
            state="following",
            epic_ids=("sase-7k",),
            added_bead_ids=("sase-7k",),
        )
    ]


def test_filesystem_loader_waiting_json_overrides_meta(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "wait_for_epics_of": ["planner"],
                "wait_epic_follows": [_follow_entry(state="launching", since=10.0)],
            }
        )
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": ["planner"],
                "wait_for_epics_of": ["planner"],
                "wait_epic_follows": [
                    _follow_entry(
                        state="following",
                        epic_ids=["sase-7k"],
                        added_bead_ids=["sase-7k"],
                        since=20.0,
                    )
                ],
            }
        )
    )

    agent = make_loader_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.wait_for_epics_of == ["planner"]
    assert agent.wait_epic_follows == [
        EpicFollowView(
            target="planner",
            state="following",
            epic_ids=("sase-7k",),
            added_bead_ids=("sase-7k",),
            since=20.0,
        )
    ]


def test_wire_loader_mirrors_follow_fields_with_waiting_override() -> None:
    agent = make_loader_agent()
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            wait_for_epics_of=["planner"],
            wait_epic_follows=[
                WaitEpicFollowEntryWire(target="planner", state="launching")
            ],
        ),
        WaitingMarkerWire(
            wait_for_epics_of=["planner"],
            wait_epic_follows=[
                WaitEpicFollowEntryWire(
                    target="planner",
                    state="following",
                    epic_ids=["sase-7k"],
                    added_bead_ids=["sase-7k"],
                )
            ],
        ),
        None,
    )

    assert agent.wait_for_epics_of == ["planner"]
    assert agent.wait_epic_follows == [
        EpicFollowView(
            target="planner",
            state="following",
            epic_ids=("sase-7k",),
            added_bead_ids=("sase-7k",),
        )
    ]


def test_render_key_changes_on_follow_stage_change() -> None:
    launching = render_agent(status="WAITING")
    launching.waiting_for = ["planner"]
    launching.wait_for_epics_of = ["planner"]
    launching.wait_epic_follows = [EpicFollowView(target="planner", state="launching")]

    following = render_agent(status="WAITING")
    following.waiting_for = ["planner"]
    following.wait_for_epics_of = ["planner"]
    following.wait_epic_follows = [
        EpicFollowView(
            target="planner",
            state="following",
            epic_ids=("sase-7k",),
            added_bead_ids=("sase-7k",),
        )
    ]

    assert _key(launching) != _key(following)
    assert _key(launching) == _key(launching)


def test_counts_following_target_leaves_agent_counts_for_follow_segment() -> None:
    planner = make_agent(
        agent_name="planner",
        raw_suffix="planner-suffix",
        status="RUNNING",
        status_bucket="Done",
    )
    waiter = make_agent(
        status="WAITING",
        waiting_for=["planner"],
        waiting_for_beads=["sase-87.2", "sase-7k"],
        wait_for_epics_of=["planner"],
        wait_epic_follows=[
            EpicFollowView(
                target="planner",
                state="following",
                epic_ids=("sase-7k",),
                added_bead_ids=("sase-7k",),
            )
        ],
    )
    maps = collect_agent_wait_status_maps([waiter, planner])
    snapshot = _snapshot(
        ("sase-87.2", "open", False),
        ("sase-7k", "in_progress", False),
    )

    counts = wait_dependency_status_counts(waiter, maps, snapshot)

    assert counts.agents.has_any is False
    assert counts.beads.open == 1
    assert counts.follows.in_progress == 1


def test_counts_blocked_target_keeps_agent_counts() -> None:
    planner = make_agent(
        agent_name="planner",
        raw_suffix="planner-suffix",
        status="RUNNING",
        status_bucket="Done",
    )
    waiter = make_agent(
        status="WAITING",
        waiting_for=["planner"],
        wait_for_epics_of=["planner"],
        wait_epic_follows=[
            EpicFollowView(
                target="planner",
                state="blocked",
                reason="launch_skipped",
            )
        ],
    )
    maps = collect_agent_wait_status_maps([waiter, planner])

    counts = wait_dependency_status_counts(waiter, maps)

    assert counts.agents.done == 1
    assert counts.follows.has_any is False


def test_satisfied_false_while_launching_or_blocked() -> None:
    planner = make_agent(
        agent_name="planner",
        raw_suffix="planner-suffix",
        status="RUNNING",
        status_bucket="Done",
    )
    for state in ("launching", "blocked"):
        waiter = make_agent(
            status="WAITING",
            waiting_for=["planner"],
            wait_for_epics_of=["planner"],
            wait_epic_follows=[EpicFollowView(target="planner", state=state)],
        )
        maps = collect_agent_wait_status_maps([waiter, planner])
        assert wait_dependencies_satisfied(waiter, maps.buckets) is False


def test_satisfied_resolved_armed_target_without_stage_matches_today() -> None:
    planner = make_agent(
        agent_name="planner",
        raw_suffix="planner-suffix",
        status="RUNNING",
        status_bucket="Done",
    )
    waiter = make_agent(
        status="WAITING",
        waiting_for=["planner"],
        wait_for_epics_of=["planner"],
    )
    maps = collect_agent_wait_status_maps([waiter, planner])

    assert wait_dependencies_satisfied(waiter, maps.buckets) is True


def test_no_io_in_follow_status_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counts, satisfied, and the shared view never touch the filesystem."""
    blocked = AssertionError("filesystem access in follow status path")
    monkeypatch.setattr(Path, "exists", lambda self: (_ for _ in ()).throw(blocked))
    monkeypatch.setattr(
        Path, "open", lambda self, *a, **k: (_ for _ in ()).throw(blocked)
    )
    monkeypatch.setattr(
        builtins, "open", lambda *a, **k: (_ for _ in ()).throw(blocked)
    )

    waiter = make_agent(
        status="WAITING",
        waiting_for=["planner"],
        waiting_for_beads=["sase-7k"],
        wait_for_epics_of=["planner"],
        wait_epic_follows=[
            EpicFollowView(
                target="planner",
                state="following",
                epic_ids=("sase-7k",),
                added_bead_ids=("sase-7k",),
            )
        ],
    )
    maps = collect_agent_wait_status_maps([waiter])
    snapshot = _snapshot(("sase-7k", "in_progress", False))

    assert epic_follow_views(waiter)[0].target == "planner"
    assert authored_wait_beads(waiter) == []
    assert "sase-7k" in describe_epic_follow(epic_follow_views(waiter)[0])
    assert wait_dependencies_satisfied(waiter, maps.buckets) is False
    counts = wait_dependency_status_counts(waiter, maps, snapshot)
    assert counts.follows.in_progress == 1

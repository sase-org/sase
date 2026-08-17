"""Presentation ordering of clan members within the agents-tab tree."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree

from ._agent_tree_helpers import _agent


def test_project_clan_tree_sorts_direct_member_units_by_status_priority() -> None:
    done = _agent("research.done", "done", status="DONE")
    waiting = _agent("research.waiting", "waiting", status="WAITING")
    running = _agent("research.running", "running", status="RUNNING")
    stopped = _agent("research.stopped", "stopped", status="QUESTION")
    failed = _agent("research.failed", "failed", status="FAILED")

    container, *members = project_clan_tree([done, waiting, running, stopped, failed])

    assert members == [failed, stopped, running, waiting, done]
    # Container facts and the detail-panel inventory retain the established
    # launch order rather than inheriting the presentation-only member sort.
    assert container.runtime_children == [done, waiting, running, stopped, failed]

    reprojected_container = project_clan_tree([container, *members])[0]
    assert reprojected_container.runtime_children == [
        done,
        waiting,
        running,
        stopped,
        failed,
    ]


def test_project_clan_tree_keeps_same_bucket_launch_order_stable() -> None:
    newer = _agent("research.newer", "newer", status="RUNNING")
    older = _agent("research.older", "older", status="RUNNING")
    newer.start_time = datetime(2026, 7, 17, 10, 1, 0)
    older.start_time = datetime(2026, 7, 17, 10, 0, 0)

    _, *members = project_clan_tree([newer, older])

    assert members == [newer, older]


def test_project_clan_tree_sorts_family_unit_by_displayed_anchor_status() -> None:
    family = _agent("research.family", "family", status="WAITING")
    failed_followup = _agent(
        "research.family--failed",
        "family-failed",
        status="FAILED",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    done_followup = _agent(
        "research.family--done",
        "family-done",
        status="DONE",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    done_peer = _agent("research.done", "done", status="DONE")
    failed_peer = _agent("research.failed", "failed", status="FAILED")

    _, *members = project_clan_tree(
        [family, failed_followup, done_followup, done_peer, failed_peer]
    )

    assert members == [
        failed_peer,
        family,
        failed_followup,
        done_followup,
        done_peer,
    ]


def test_project_clan_tree_ranks_starting_with_running() -> None:
    done = _agent("research.done", "done", status="DONE")
    starting = _agent("research.starting", "starting", status="STARTING")
    running = _agent("research.running", "running", status="RUNNING")

    _, *members = project_clan_tree([done, starting, running])

    assert members == [starting, running, done]

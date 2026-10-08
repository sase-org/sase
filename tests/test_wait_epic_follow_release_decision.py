"""Release-decision regressions: every release path shares one decision.

Split from ``tests.test_wait_epic_follow_release``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.core.wait_dependency_resolution import resolve_wait_release
from tests._agent_names_fixtures import make_agent
from tests._wait_epic_follow_release_helpers import (
    NOW,
    build_release_index,
    decide_release,
    make_release_marker,
    make_release_planner,
    make_release_waiter,
    write_release_argv,
)

__all__ = [
    "test_attributed_epic_heals_missing_record",
    "test_closed_epic_promotes_first_then_releases",
    "test_foreign_epic_id_appends_verbatim",
    "test_implicit_targets_stay_unarmed",
    "test_marker_without_armed_field_releases_as_today",
    "test_monitor_path_launching_then_following",
    "test_non_list_armed_field_means_no_armed_targets",
    "test_phase_worker_child_epic_is_followed",
    "test_phase_worker_inherited_epic_is_not_followed",
    "test_pinned_following_pin_is_not_repromoted",
    "test_plain_tale_end_is_none_and_releasable",
    "test_plan_in_review_stays_agent",
    "test_plan_rejected_stays_parked",
    "test_proc_fallback_launching_does_not_release",
    "test_recorded_epic_promotes_and_parks_first_pass",
    "test_several_recorded_epics_append_in_reducer_order",
    "test_skip_mode_blocks_launch_skipped",
    "test_stale_reservation_blocks_with_resume_command",
    "test_stale_view_withholds_promotion",
    "test_unresolved_unarmed_waiter_stays_parked",
    "test_waiter_own_epic_is_guarded",
]


def _states(decision: Any) -> list[str]:
    return [follow.target + ":" + follow.state for follow in decision.follows]


def test_marker_without_armed_field_releases_as_today(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000")
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(index, make_release_marker(["planner"], None), waiter)
    assert decision.status.resolved
    assert decision.follows == ()
    assert decision.patch is None
    assert decision.releasable is True
    assert decision.confirmation_failed is False


def test_non_list_armed_field_means_no_armed_targets(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000")
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index,
        make_release_marker(["planner"], None, wait_for_epics_of="planner"),
        waiter,
    )
    assert decision.patch is None
    assert decision.releasable is True


def test_unresolved_unarmed_waiter_stays_parked(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000", done=False, outcome=None)
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(index, make_release_marker(["planner"], None), waiter)
    assert not decision.status.resolved
    assert decision.patch is None
    assert decision.releasable is False


def test_plain_tale_end_is_none_and_releasable(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000")
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:none"]
    assert decision.patch is None
    assert decision.releasable is True


def test_recorded_epic_promotes_and_parks_first_pass(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:following"]
    assert decision.patch is not None
    assert list(decision.patch.wait_for_beads) == ["sase-7k"]
    assert list(decision.patch.resolved_deps) == ["planner"]
    assert len(decision.patch.wait_epic_follows) == 1
    entry = decision.patch.wait_epic_follows[0]
    assert entry["target"] == "planner"
    assert entry["state"] == "following"
    assert entry["epic_ids"] == ["sase-7k"]
    assert entry["added_bead_ids"] == ["sase-7k"]
    assert entry["since"] == NOW
    assert decision.releasable is False


def test_plan_in_review_stays_agent(tmp_path: Path) -> None:
    planner = make_agent(
        tmp_path,
        "proj",
        "20261001090000",
        "planner",
        agent_session="planner",
        done=False,
        extra_meta={"plan": True, "plan_submitted_at": ["2026-10-01T09:00:00+00:00"]},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:agent"]
    assert decision.patch is None
    assert decision.releasable is False


def test_plan_rejected_stays_parked(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000", outcome="plan_rejected")
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert decision.releasable is False
    assert all(follow.state != "following" for follow in decision.follows)
    assert decision.patch is None


def test_monitor_path_launching_then_following(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000", outcome="epic_approved")
    write_release_argv(planner)
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    launching = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(launching) in (["planner:launching"], ["planner:blocked"])
    assert launching.patch is not None
    assert launching.releasable is False

    meta_path = planner / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created_epics"] = [{"bead_id": "sase-7k"}]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    following = decide_release(
        build_release_index(planner),
        make_release_marker(["planner"], ["planner"]),
        waiter,
    )
    assert _states(following) == ["planner:following"]
    assert following.patch is not None
    assert list(following.patch.wait_for_beads) == ["sase-7k"]


def test_proc_fallback_launching_does_not_release(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000", outcome="epic_approved")
    write_release_argv(planner)
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:launching"]
    assert decision.releasable is False
    assert decision.patch is not None
    assert decision.patch.wait_epic_follows[0]["state"] == "launching"


def test_stale_reservation_blocks_with_resume_command(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000", outcome="epic_approved")
    write_release_argv(planner, now=NOW - 10_000.0)
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:blocked"]
    assert decision.follows[0].reason == "launch_ended_without_epic"
    assert decision.releasable is False


def test_skip_mode_blocks_launch_skipped(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000", outcome="epic_approved")
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:blocked"]
    assert decision.follows[0].reason == "launch_skipped"
    assert decision.releasable is False
    assert decision.patch is not None


def test_attributed_epic_heals_missing_record(tmp_path: Path) -> None:
    planner = make_release_planner(tmp_path, "20261001090000")
    write_release_argv(planner)
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    with patch(
        "sase.core.created_epics.attributed_epic_ids",
        return_value=["sase-7k"],
    ):
        decision = decide_release(
            index, make_release_marker(["planner"], ["planner"]), waiter
        )
    assert _states(decision) == ["planner:following"]
    assert list(decision.patch.wait_for_beads) == ["sase-7k"]


def test_several_recorded_epics_append_in_reducer_order(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}, {"bead_id": "sase-7m"}]},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:following"]
    assert list(decision.patch.wait_for_beads) == ["sase-7k", "sase-7m"]
    assert decision.patch.wait_epic_follows[0]["added_bead_ids"] == [
        "sase-7k",
        "sase-7m",
    ]


def test_phase_worker_inherited_epic_is_not_followed(tmp_path: Path) -> None:
    worker = make_agent(
        tmp_path,
        "proj",
        "20261001090000",
        "phase-1",
        agent_session="phase-1",
        done=True,
        outcome="completed",
        extra_meta={"epic_bead_id": "sase-7k", "phase_bead_id": "sase-7k.1"},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(worker)
    decision = decide_release(
        index, make_release_marker(["phase-1"], ["phase-1"]), waiter
    )
    assert _states(decision) == ["phase-1:none"]
    assert decision.patch is None
    assert decision.releasable is True


def test_phase_worker_child_epic_is_followed(tmp_path: Path) -> None:
    worker = make_agent(
        tmp_path,
        "proj",
        "20261001090000",
        "phase-1",
        agent_session="phase-1",
        done=True,
        outcome="completed",
        extra_meta={
            "epic_bead_id": "sase-7k",
            "phase_bead_id": "sase-7k.1",
            "created_epics": [{"bead_id": "sase-7m"}],
        },
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(worker)
    decision = decide_release(
        index, make_release_marker(["phase-1"], ["phase-1"]), waiter
    )
    assert _states(decision) == ["phase-1:following"]
    assert list(decision.patch.wait_for_beads) == ["sase-7m"]


def test_waiter_own_epic_is_guarded(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path, extra_meta={"phase_bead_id": "sase-7k.1"})
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:none"]
    assert list(decision.follows[0].skipped_epic_ids) == ["sase-7k"]
    assert decision.patch is None
    assert decision.releasable is True


def test_foreign_epic_id_appends_verbatim(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "gh_owner__repo-1a.3"}]},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = decide_release(
        index, make_release_marker(["planner"], ["planner"]), waiter
    )
    assert _states(decision) == ["planner:following"]
    assert list(decision.patch.wait_for_beads) == ["gh_owner__repo-1a.3"]


def test_pinned_following_pin_is_not_repromoted(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-9z"}]},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    marker = make_release_marker(
        ["planner"],
        ["planner"],
        wait_epic_follows=[
            {
                "target": "planner",
                "state": "following",
                "epic_ids": ["sase-7k"],
                "added_bead_ids": ["sase-7k"],
                "members": ["planner"],
                "since": NOW - 100.0,
                "reason": None,
                "detail": None,
                "resume_command": None,
                "skipped_epic_ids": [],
            }
        ],
        wait_for_beads=["sase-7k"],
        resolved_deps=["planner"],
    )
    decision = decide_release(index, marker, waiter, closed=frozenset({"sase-7k"}))
    assert decision.follows == ()
    assert decision.patch is None
    assert decision.releasable is True


def test_closed_epic_promotes_first_then_releases(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    first = decide_release(index, make_release_marker(["planner"], ["planner"]), waiter)
    assert _states(first) == ["planner:following"]
    assert first.patch is not None
    assert first.releasable is False

    promoted = make_release_marker(["planner"], ["planner"])
    promoted["wait_for_beads"] = list(first.patch.wait_for_beads)
    promoted["resolved_deps"] = list(first.patch.resolved_deps)
    promoted["wait_epic_follows"] = [
        dict(entry) for entry in first.patch.wait_epic_follows
    ]
    second = decide_release(index, promoted, waiter, closed=frozenset({"sase-7k"}))
    assert second.follows == ()
    assert second.patch is None
    assert second.releasable is True


def test_implicit_targets_stay_unarmed(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    other = make_release_planner(tmp_path, "20261001090100", name="other")
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner, other)
    decision = decide_release(
        index, make_release_marker(["planner", "other"], ["other"]), waiter
    )
    assert _states(decision) == ["other:none"]
    assert decision.patch is None
    assert decision.releasable is True


def test_stale_view_withholds_promotion(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path)
    index = build_release_index(planner)
    decision = resolve_wait_release(
        index,
        make_release_marker(["planner"], ["planner"]),
        waiter_dir=waiter,
        closed_bead_ids=None,
        now=NOW,
        fresh_index=None,
    )
    assert decision.confirmation_failed is True
    assert decision.patch is None
    assert decision.releasable is False

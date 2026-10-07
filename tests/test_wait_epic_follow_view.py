"""Tests for the shared epic-follow view model and phrasing."""

from __future__ import annotations

from sase.core.agent_scan_wire_markers import WaitEpicFollowEntryWire
from sase.core.wait_epic_follow_view import (
    EpicFollowView,
    armed_follow_targets,
    authored_wait_beads,
    describe_epic_follow,
    epic_follow_state_token,
    epic_follow_views,
)


def _wire_entry(**overrides: object) -> WaitEpicFollowEntryWire:
    defaults: dict[str, object] = {
        "target": "planner",
        "state": "following",
        "epic_ids": ["sase-7k"],
        "added_bead_ids": ["sase-7k"],
        "members": ["planner"],
        "since": 1234.0,
    }
    defaults.update(overrides)
    return WaitEpicFollowEntryWire(**defaults)  # type: ignore[arg-type]


def test_views_coerce_wire_entries_and_drop_transient_states() -> None:
    views = epic_follow_views(
        [
            _wire_entry(),
            _wire_entry(
                target="other",
                state="launching",
                epic_ids=[],
                added_bead_ids=[],
                members=[],
                since=0.0,
            ),
            _wire_entry(target="gone", state="none"),
            _wire_entry(target="unresolved", state="agent"),
            _wire_entry(target="  ", state="following"),
        ]
    )

    assert views == (
        EpicFollowView(
            target="planner",
            state="following",
            epic_ids=("sase-7k",),
            added_bead_ids=("sase-7k",),
            members=("planner",),
            since=1234.0,
        ),
        EpicFollowView(target="other", state="launching"),
    )


def test_views_accept_plain_mappings_and_dedupe_targets() -> None:
    views = epic_follow_views(
        {
            "wait_epic_follows": [
                {
                    "target": "planner",
                    "state": "blocked",
                    "reason": "launch_skipped",
                    "resume_command": "sase bead work plans/x.md",
                },
                {
                    "target": "planner",
                    "state": "following",
                    "epic_ids": ["sase-7k"],
                },
            ]
        }
    )

    assert views == (
        EpicFollowView(
            target="planner",
            state="blocked",
            reason="launch_skipped",
            resume_command="sase bead work plans/x.md",
        ),
    )


def test_views_pass_through_model_views() -> None:
    stored = [
        EpicFollowView(target="planner", state="launching", since=10.0),
    ]

    assert epic_follow_views({"wait_epic_follows": [], "waiting_for": []}) == ()
    assert epic_follow_views(stored) == tuple(stored)


def test_armed_targets_intersect_in_order() -> None:
    source = {
        "waiting_for": ["planner", "reviewer"],
        "wait_for_epics_of": ["reviewer", "planner", "ghost"],
    }

    assert armed_follow_targets(source) == ["reviewer", "planner"]
    assert armed_follow_targets({"waiting_for": ["planner"]}) == []
    assert armed_follow_targets({}) == []


def test_authored_beads_exclude_derived_but_keep_user_authored() -> None:
    source = {
        "waiting_for": ["planner"],
        "wait_for_beads": ["sase-87.2", "sase-7k"],
        "wait_epic_follows": [
            {
                "target": "planner",
                "state": "following",
                "epic_ids": ["sase-7k"],
                "added_bead_ids": ["sase-7k"],
            }
        ],
    }

    # sase-7k was appended by promotion (derived); sase-87.2 was authored.
    assert authored_wait_beads(source) == ["sase-87.2"]


def test_authored_beads_without_stages_return_everything() -> None:
    assert authored_wait_beads({"wait_for_beads": ["sase-87.2"]}) == ["sase-87.2"]
    assert authored_wait_beads({}) == []


def test_describe_following_single_and_multi_epic() -> None:
    assert (
        describe_epic_follow(
            EpicFollowView(target="planner", state="following", epic_ids=("sase-7k",))
        )
        == "waits on planner's epic sase-7k"
    )
    assert (
        describe_epic_follow(
            EpicFollowView(
                target="planner",
                state="following",
                epic_ids=("sase-7k", "sase-7m"),
            )
        )
        == "waits on planner's epics sase-7k, sase-7m"
    )


def test_describe_launching() -> None:
    assert (
        describe_epic_follow(EpicFollowView(target="planner", state="launching"))
        == "waits on planner's epic launch"
    )


def test_describe_blocked_reasons() -> None:
    assert describe_epic_follow(
        EpicFollowView(
            target="planner",
            state="blocked",
            reason="launch_ended_without_epic",
            resume_command="sase bead work plans/x.md",
        )
    ) == (
        "blocked: planner's epic launch ended without an epic "
        "(resume: sase bead work plans/x.md)"
    )
    assert (
        describe_epic_follow(
            EpicFollowView(target="planner", state="blocked", reason="launch_skipped")
        )
        == "blocked: planner's epic launch was skipped"
    )
    assert (
        describe_epic_follow(
            EpicFollowView(
                target="planner",
                state="blocked",
                reason="target_dismissed_during_launch",
            )
        )
        == "blocked: planner's epic launch ended when the target was dismissed"
    )
    assert (
        describe_epic_follow(
            EpicFollowView(target="planner", state="blocked", reason="cycle")
        )
        == "blocked: planner's epic launch would wait on the waiter"
    )


def test_state_token_changes_on_stage_change_only() -> None:
    base = {
        "waiting_for": ["planner"],
        "wait_for_epics_of": ["planner"],
        "wait_epic_follows": [
            {"target": "planner", "state": "launching", "since": 10.0}
        ],
    }
    same = {
        "waiting_for": ["planner"],
        "wait_for_epics_of": ["planner"],
        "wait_epic_follows": [
            {"target": "planner", "state": "launching", "since": 10.0}
        ],
    }
    promoted = {
        "waiting_for": ["planner"],
        "wait_for_epics_of": ["planner"],
        "wait_epic_follows": [
            {
                "target": "planner",
                "state": "following",
                "epic_ids": ["sase-7k"],
                "added_bead_ids": ["sase-7k"],
                "since": 20.0,
            }
        ],
    }

    assert epic_follow_state_token(base) == epic_follow_state_token(same)
    assert epic_follow_state_token(base) != epic_follow_state_token(promoted)
    hash(epic_follow_state_token(promoted))

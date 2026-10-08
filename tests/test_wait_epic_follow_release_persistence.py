"""Release persistence: patch apply, wait-until edits, and wire round trip.

Split from ``tests.test_wait_epic_follow_release``; shared builders live in
``tests._wait_epic_follow_release_helpers`` and the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.wait_dependency_resolution import (
    apply_wait_epic_follow_patch,
    set_waiting_until,
)
from tests._wait_epic_follow_release_helpers import (
    NOW,
    build_release_index,
    decide_release,
    make_release_marker,
    make_release_planner,
    make_release_waiter,
    write_waiting_marker,
)

__all__ = [
    "test_apply_patch_compare_and_set_abort_leaves_file_unchanged",
    "test_apply_patch_persists_follows_beads_and_deps",
    "test_set_waiting_until_missing_marker_is_noop",
    "test_set_waiting_until_preserves_follows_and_derived_beads",
    "test_wait_epic_follows_wire_round_trip",
]


def test_apply_patch_compare_and_set_abort_leaves_file_unchanged(
    tmp_path: Path,
) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path)
    marker = make_release_marker(["planner"], ["planner"])
    write_waiting_marker(waiter, marker)
    index = build_release_index(planner)
    decision = decide_release(index, marker, waiter)
    assert decision.patch is not None

    concurrent = dict(marker)
    concurrent["wait_for_beads"] = ["sase-9x"]
    write_waiting_marker(waiter, concurrent)
    before = (waiter / "waiting.json").read_bytes()
    assert apply_wait_epic_follow_patch(waiter, decision.patch) is False
    assert (waiter / "waiting.json").read_bytes() == before


def test_apply_patch_persists_follows_beads_and_deps(tmp_path: Path) -> None:
    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path)
    marker = make_release_marker(
        ["planner"], ["planner"], wait_until="2026-10-07T12:00:00+00:00"
    )
    write_waiting_marker(waiter, marker)
    index = build_release_index(planner)
    decision = decide_release(index, marker, waiter)
    assert decision.patch is not None
    assert apply_wait_epic_follow_patch(waiter, decision.patch) is True
    stored = json.loads((waiter / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_for_beads"] == ["sase-7k"]
    assert stored["resolved_deps"] == ["planner"]
    assert stored["wait_epic_follows"][0]["target"] == "planner"
    assert stored["wait_until"] == "2026-10-07T12:00:00+00:00"
    meta = json.loads((waiter / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["wait_for_beads"] == ["sase-7k"]
    assert meta["wait_epic_follows"][0]["state"] == "following"


def test_set_waiting_until_preserves_follows_and_derived_beads(
    tmp_path: Path,
) -> None:
    waiter = make_release_waiter(tmp_path)
    marker = make_release_marker(
        ["planner"],
        ["planner"],
        wait_for_beads=["sase-7k"],
        resolved_deps=["planner"],
        wait_epic_follows=[{"target": "planner", "state": "following"}],
        wait_until="2026-10-07T12:00:00+00:00",
    )
    write_waiting_marker(waiter, marker)
    set_waiting_until(waiter, "2026-10-08T12:00:00+00:00")
    stored = json.loads((waiter / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_until"] == "2026-10-08T12:00:00+00:00"
    assert stored["wait_epic_follows"] == [{"target": "planner", "state": "following"}]
    assert stored["wait_for_beads"] == ["sase-7k"]
    assert stored["resolved_deps"] == ["planner"]


def test_set_waiting_until_missing_marker_is_noop(tmp_path: Path) -> None:
    waiter = make_release_waiter(tmp_path)
    set_waiting_until(waiter, "2026-10-08T12:00:00+00:00")
    assert not (waiter / "waiting.json").exists()


def test_wait_epic_follows_wire_round_trip() -> None:
    from sase.core.agent_scan_wire_conversion import (
        _agent_meta_from_dict,
        _waiting_marker_from_dict,
        agent_scan_wire_to_json_dict,
    )

    entry = {
        "target": "planner",
        "state": "following",
        "epic_ids": ["sase-7k"],
        "added_bead_ids": ["sase-7k"],
        "members": ["planner"],
        "since": NOW,
        "reason": None,
        "detail": "recorded",
        "resume_command": None,
        "skipped_epic_ids": [],
        "future_key": "ignored",
    }
    meta = _agent_meta_from_dict({"wait_epic_follows": [entry]})
    assert len(meta.wait_epic_follows) == 1
    assert meta.wait_epic_follows[0].target == "planner"
    assert meta.wait_epic_follows[0].state == "following"
    assert list(meta.wait_epic_follows[0].epic_ids) == ["sase-7k"]
    payload = agent_scan_wire_to_json_dict(meta)
    assert payload["wait_epic_follows"][0]["target"] == "planner"

    marker = _waiting_marker_from_dict(
        {"waiting_for": ["planner"], "wait_epic_follows": [entry]}
    )
    assert len(marker.wait_epic_follows) == 1
    assert marker.wait_epic_follows[0].since == NOW

    dropped = _waiting_marker_from_dict(
        {
            "waiting_for": [],
            "wait_epic_follows": [
                {"target": "", "state": "following"},
                {"target": "planner", "state": "agent"},
                "not-a-mapping",
                {"target": "planner", "state": "following", "epic_ids": ["sase-7k"]},
            ],
        }
    )
    assert len(dropped.wait_epic_follows) == 1
    assert dropped.wait_epic_follows[0].target == "planner"

    from dataclasses import fields

    from sase.core.agent_scan_wire_markers import WaitingMarkerWire

    assert fields(WaitingMarkerWire)[-1].name == "wait_epic_follows"

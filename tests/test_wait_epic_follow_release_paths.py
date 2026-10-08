"""Patch, wire, and cross-path agreement for wait-epic-follow release.

Split from ``tests.test_wait_epic_follow_release``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

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
    write_release_argv,
)

__all__ = [
    "test_apply_patch_compare_and_set_abort_leaves_file_unchanged",
    "test_apply_patch_persists_follows_beads_and_deps",
    "test_dismiss_launching_target_blocks_without_memoize",
    "test_release_paths_agree_on_promotion_snapshot",
    "test_release_paths_agree_on_unarmed_snapshot",
    "test_run_now_writes_unwait_ready_without_release_decision",
    "test_set_waiting_until_missing_marker_is_noop",
    "test_set_waiting_until_preserves_follows_and_derived_beads",
    "test_wait_epic_follows_wire_round_trip",
]


def _write_waiting_json(waiter: Path, marker: dict[str, Any]) -> None:
    (waiter / "waiting.json").write_text(json.dumps(marker), encoding="utf-8")


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
    _write_waiting_json(waiter, marker)
    index = build_release_index(planner)
    decision = decide_release(index, marker, waiter)
    assert decision.patch is not None

    concurrent = dict(marker)
    concurrent["wait_for_beads"] = ["sase-9x"]
    _write_waiting_json(waiter, concurrent)
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
    _write_waiting_json(waiter, marker)
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
    _write_waiting_json(waiter, marker)
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


def test_run_now_writes_unwait_ready_without_release_decision(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from sase.ace.tui.actions.agents._wait_actions import AgentWaitActionsMixin
    from sase.ace.tui.modals.wait_modal_types import WaitModalResult

    waiter = make_release_waiter(tmp_path)
    agent = SimpleNamespace(
        waiting_for=["planner"],
        waiting_for_beads=[],
        waiting_for_hoods=[],
        wait_duration=None,
        wait_until=None,
        wait_priority=None,
        wait_priority_explicit=False,
        slot_requested_at=None,
        cl_name="waiter-cl",
        display_name="waiter",
        set_queue_capacity=lambda *args, **kwargs: None,
    )
    result = WaitModalResult(agents=[], time_token=None, capacity=None, run_now=True)
    submitted: dict[str, Any] = {}

    def _submit(self: object, **kwargs: Any) -> bool:
        submitted.update(kwargs.get("payload", {}))
        return True

    with (
        patch("sase.ace.tui.actions.agent_durable.submit_agent_directive", _submit),
        patch(
            "sase.core.wait_dependency_resolution._epic_follow_release.resolve_wait_release"
        ) as release,
    ):
        AgentWaitActionsMixin._apply_wait(
            SimpleNamespace(  # type: ignore[arg-type]
                notify=lambda *args, **kwargs: None,
                _refresh_agents_display=lambda **kwargs: None,
            ),
            str(waiter),
            agent,  # type: ignore[arg-type]
            result,
        )
    assert submitted["ready"] == {"resolved_deps": ["planner"], "unwait": True}
    release.assert_not_called()
    assert agent.waiting_for == []


def test_release_paths_agree_on_promotion_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import run_agent_wait_deps as wait_deps

    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path)
    marker = make_release_marker(["planner"], ["planner"])
    _write_waiting_json(waiter, marker)
    index = build_release_index(planner)
    direct = decide_release(index, marker, waiter)
    assert direct.patch is not None
    assert direct.releasable is False

    monkeypatch.setattr(
        wait_deps, "build_wait_dependency_index", lambda *args, **kwargs: index
    )
    initial = wait_deps.resolve_initial_wait_release(
        ["planner"],
        [],
        wait_for_epics_of=["planner"],
        project_name="proj",
        artifacts_dir=str(waiter),
    )
    assert [(f.target, f.state) for f in initial.follows] == [
        (f.target, f.state) for f in direct.follows
    ]
    assert (initial.patch is None) == (direct.patch is None)
    assert initial.releasable == direct.releasable

    assert (
        bool(
            wait_deps.waiting_marker_dependencies_resolved(
                waiter / "waiting.json",
                project_name="proj",
                artifacts_dir=str(waiter),
            )
        )
        is False
    )
    stored = json.loads((waiter / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_for_beads"] == ["sase-7k"]
    assert stored["wait_epic_follows"][0]["state"] == "following"


def test_release_paths_agree_on_unarmed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import run_agent_wait_deps as wait_deps

    planner = make_release_planner(tmp_path, "20261001090000")
    waiter = make_release_waiter(tmp_path)
    marker = make_release_marker(["planner"], None)
    _write_waiting_json(waiter, marker)
    index = build_release_index(planner)
    direct = decide_release(index, marker, waiter)
    assert direct.releasable is True

    monkeypatch.setattr(
        wait_deps, "build_wait_dependency_index", lambda *args, **kwargs: index
    )
    initial = wait_deps.resolve_initial_wait_release(
        ["planner"], [], project_name="proj", artifacts_dir=str(waiter)
    )
    assert initial.releasable == direct.releasable
    assert initial.patch is None
    assert (
        bool(
            wait_deps.waiting_marker_dependencies_resolved(
                waiter / "waiting.json",
                project_name="proj",
                artifacts_dir=str(waiter),
            )
        )
        is True
    )


def test_dismiss_launching_target_blocks_without_memoize(tmp_path: Path) -> None:
    from sase.ace.tui.actions.agents._killing_utils import (
        _resolve_waiters_before_artifact_delete,
    )

    member = make_release_planner(tmp_path, "20261001090000", outcome="epic_approved")
    moment = time.time()
    write_release_argv(member, now=moment)
    waiter = make_release_waiter(tmp_path, suffix="waiter")
    _write_waiting_json(waiter, make_release_marker(["planner"], ["planner"]))

    undismissed = decide_release(
        build_release_index(member),
        make_release_marker(["planner"], ["planner"]),
        waiter,
        now=moment,
    )
    assert [f.state for f in undismissed.follows] == ["launching"]

    _resolve_waiters_before_artifact_delete(str(member))
    stored = json.loads((waiter / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_epic_follows"][0]["state"] == "blocked"
    assert stored["wait_epic_follows"][0]["reason"] == "target_dismissed_during_launch"
    assert stored.get("resolved_deps", []) == []
    assert not (waiter / "ready.json").exists()

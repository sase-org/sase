"""Release-phase regressions: every release path shares one decision.

Covers ``resolve_wait_release``, ``apply_wait_epic_follow_patch``, and
``set_waiting_until`` over fixture trees built the way
``tests/test_wait_epic_follow_collector.py`` does, plus agreement across the
runner initial check, the parked-runner fallback, the chop per-waiter
decision, and the kill/dismiss path.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    apply_wait_epic_follow_patch,
    resolve_wait_release,
    set_waiting_until,
)
from tests._agent_names_fixtures import make_agent

NOW = 1_800_000_000.0


def _index(*artifact_dirs: Path) -> WaitDependencyIndex:
    index = WaitDependencyIndex.empty()
    index.add_many(
        (
            artifact_dir,
            json.loads((artifact_dir / "agent_meta.json").read_text(encoding="utf-8")),
            "proj",
        )
        for artifact_dir in artifact_dirs
    )
    return index


def _planner(
    tmp_path: Path,
    suffix: str,
    name: str = "planner",
    *,
    done: bool = True,
    outcome: str | None = "completed",
    extra_meta: dict[str, object] | None = None,
) -> Path:
    return make_agent(
        tmp_path,
        "proj",
        suffix,
        name,
        agent_session="planner",
        done=done,
        outcome=outcome,
        extra_meta=extra_meta,
    )


def _waiter_dir(
    tmp_path: Path,
    suffix: str = "waiter",
    *,
    extra_meta: dict[str, object] | None = None,
) -> Path:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": "waiter", "model": "test"}
    if extra_meta:
        meta.update(extra_meta)
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return artifact_dir


def _marker(
    waiting_for: list[str],
    armed: list[str] | None,
    **extra: Any,
) -> dict[str, Any]:
    marker: dict[str, Any] = {"waiting_for": list(waiting_for)}
    if armed is not None:
        marker["wait_for_epics_of"] = list(armed)
    marker.update(extra)
    return marker


def _decide(
    index: WaitDependencyIndex,
    marker: dict[str, Any],
    waiter_dir: Path,
    *,
    closed: frozenset[str] | None = None,
    dismissed: Path | None = None,
    now: float = NOW,
) -> Any:
    return resolve_wait_release(
        index,
        marker,
        waiter_dir=waiter_dir,
        closed_bead_ids=closed,
        now=now,
        dismissed_artifact_dir=dismissed,
        fresh_index=lambda: index,
    )


def _states(decision: Any) -> list[str]:
    return [follow.target + ":" + follow.state for follow in decision.follows]


def test_marker_without_armed_field_releases_as_today(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000")
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], None), waiter)
    assert decision.status.resolved
    assert decision.follows == ()
    assert decision.patch is None
    assert decision.releasable is True
    assert decision.confirmation_failed is False


def test_non_list_armed_field_means_no_armed_targets(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000")
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(
        index, _marker(["planner"], None, wait_for_epics_of="planner"), waiter
    )
    assert decision.patch is None
    assert decision.releasable is True


def test_unresolved_unarmed_waiter_stays_parked(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", done=False, outcome=None)
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], None), waiter)
    assert not decision.status.resolved
    assert decision.patch is None
    assert decision.releasable is False


def test_plain_tale_end_is_none_and_releasable(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000")
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:none"]
    assert decision.patch is None
    assert decision.releasable is True


def test_recorded_epic_promotes_and_parks_first_pass(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
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
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:agent"]
    assert decision.patch is None
    assert decision.releasable is False


def test_plan_rejected_stays_parked(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", outcome="plan_rejected")
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert decision.releasable is False
    assert all(follow.state != "following" for follow in decision.follows)
    assert decision.patch is None


def _fresh_argv(planner: Path, now: float = NOW) -> None:
    (planner / "epic_launch_argv.json").write_text(
        json.dumps(
            {"argv": ["sase", "bead", "work", "202610/epic.md", "--yes-to-all"]}
        ),
        encoding="utf-8",
    )
    os.utime(planner / "epic_launch_argv.json", (now, now))


def test_monitor_path_launching_then_following(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", outcome="epic_approved")
    _fresh_argv(planner)
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    launching = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(launching) in (["planner:launching"], ["planner:blocked"])
    assert launching.patch is not None
    assert launching.releasable is False

    meta_path = planner / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created_epics"] = [{"bead_id": "sase-7k"}]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    following = _decide(_index(planner), _marker(["planner"], ["planner"]), waiter)
    assert _states(following) == ["planner:following"]
    assert following.patch is not None
    assert list(following.patch.wait_for_beads) == ["sase-7k"]


def test_proc_fallback_launching_does_not_release(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", outcome="epic_approved")
    _fresh_argv(planner)
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:launching"]
    assert decision.releasable is False
    assert decision.patch is not None
    assert decision.patch.wait_epic_follows[0]["state"] == "launching"


def test_stale_reservation_blocks_with_resume_command(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", outcome="epic_approved")
    _fresh_argv(planner, now=NOW - 10_000.0)
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:blocked"]
    assert decision.follows[0].reason == "launch_ended_without_epic"
    assert decision.releasable is False


def test_skip_mode_blocks_launch_skipped(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", outcome="epic_approved")
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:blocked"]
    assert decision.follows[0].reason == "launch_skipped"
    assert decision.releasable is False
    assert decision.patch is not None


def test_attributed_epic_heals_missing_record(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000")
    _fresh_argv(planner)
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    with patch(
        "sase.core.created_epics.attributed_epic_ids",
        return_value=["sase-7k"],
    ):
        decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:following"]
    assert list(decision.patch.wait_for_beads) == ["sase-7k"]


def test_several_recorded_epics_append_in_reducer_order(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}, {"bead_id": "sase-7m"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
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
    waiter = _waiter_dir(tmp_path)
    index = _index(worker)
    decision = _decide(index, _marker(["phase-1"], ["phase-1"]), waiter)
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
    waiter = _waiter_dir(tmp_path)
    index = _index(worker)
    decision = _decide(index, _marker(["phase-1"], ["phase-1"]), waiter)
    assert _states(decision) == ["phase-1:following"]
    assert list(decision.patch.wait_for_beads) == ["sase-7m"]


def test_waiter_own_epic_is_guarded(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path, extra_meta={"phase_bead_id": "sase-7k.1"})
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:none"]
    assert list(decision.follows[0].skipped_epic_ids) == ["sase-7k"]
    assert decision.patch is None
    assert decision.releasable is True


def test_foreign_epic_id_appends_verbatim(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "gh_owner__repo-1a.3"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(decision) == ["planner:following"]
    assert list(decision.patch.wait_for_beads) == ["gh_owner__repo-1a.3"]


def test_pinned_following_pin_is_not_repromoted(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-9z"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    marker = _marker(
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
    decision = _decide(index, marker, waiter, closed=frozenset({"sase-7k"}))
    assert decision.follows == ()
    assert decision.patch is None
    assert decision.releasable is True


def test_closed_epic_promotes_first_then_releases(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    first = _decide(index, _marker(["planner"], ["planner"]), waiter)
    assert _states(first) == ["planner:following"]
    assert first.patch is not None
    assert first.releasable is False

    promoted = _marker(["planner"], ["planner"])
    promoted["wait_for_beads"] = list(first.patch.wait_for_beads)
    promoted["resolved_deps"] = list(first.patch.resolved_deps)
    promoted["wait_epic_follows"] = [
        dict(entry) for entry in first.patch.wait_epic_follows
    ]
    second = _decide(index, promoted, waiter, closed=frozenset({"sase-7k"}))
    assert second.follows == ()
    assert second.patch is None
    assert second.releasable is True


def test_implicit_targets_stay_unarmed(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    other = _planner(tmp_path, "20261001090100", name="other")
    waiter = _waiter_dir(tmp_path)
    index = _index(planner, other)
    decision = _decide(index, _marker(["planner", "other"], ["other"]), waiter)
    assert _states(decision) == ["other:none"]
    assert decision.patch is None
    assert decision.releasable is True


def test_stale_view_withholds_promotion(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = resolve_wait_release(
        index,
        _marker(["planner"], ["planner"]),
        waiter_dir=waiter,
        closed_bead_ids=None,
        now=NOW,
        fresh_index=None,
    )
    assert decision.confirmation_failed is True
    assert decision.patch is None
    assert decision.releasable is False


def _write_waiting_json(waiter: Path, marker: dict[str, Any]) -> None:
    (waiter / "waiting.json").write_text(json.dumps(marker), encoding="utf-8")


def test_apply_patch_compare_and_set_abort_leaves_file_unchanged(
    tmp_path: Path,
) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    marker = _marker(["planner"], ["planner"])
    _write_waiting_json(waiter, marker)
    index = _index(planner)
    decision = _decide(index, marker, waiter)
    assert decision.patch is not None

    concurrent = dict(marker)
    concurrent["wait_for_beads"] = ["sase-9x"]
    _write_waiting_json(waiter, concurrent)
    before = (waiter / "waiting.json").read_bytes()
    assert apply_wait_epic_follow_patch(waiter, decision.patch) is False
    assert (waiter / "waiting.json").read_bytes() == before


def test_apply_patch_persists_follows_beads_and_deps(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    marker = _marker(["planner"], ["planner"], wait_until="2026-10-07T12:00:00+00:00")
    _write_waiting_json(waiter, marker)
    index = _index(planner)
    decision = _decide(index, marker, waiter)
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
    waiter = _waiter_dir(tmp_path)
    marker = _marker(
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
    waiter = _waiter_dir(tmp_path)
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

    waiter = _waiter_dir(tmp_path)
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
            SimpleNamespace(
                notify=lambda *args, **kwargs: None,
                _refresh_agents_display=lambda **kwargs: None,
            ),
            str(waiter),
            agent,
            result,
        )
    assert submitted["ready"] == {"resolved_deps": ["planner"], "unwait": True}
    release.assert_not_called()
    assert agent.waiting_for == []


def test_release_paths_agree_on_promotion_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import run_agent_wait_deps as wait_deps

    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    marker = _marker(["planner"], ["planner"])
    _write_waiting_json(waiter, marker)
    index = _index(planner)
    direct = _decide(index, marker, waiter)
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
        wait_deps.waiting_marker_dependencies_resolved(
            waiter / "waiting.json",
            project_name="proj",
            artifacts_dir=str(waiter),
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

    planner = _planner(tmp_path, "20261001090000")
    waiter = _waiter_dir(tmp_path)
    marker = _marker(["planner"], None)
    _write_waiting_json(waiter, marker)
    index = _index(planner)
    direct = _decide(index, marker, waiter)
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
        wait_deps.waiting_marker_dependencies_resolved(
            waiter / "waiting.json",
            project_name="proj",
            artifacts_dir=str(waiter),
        )
        is True
    )


def test_dismiss_launching_target_blocks_without_memoize(tmp_path: Path) -> None:
    from sase.ace.tui.actions.agents._killing_utils import (
        _resolve_waiters_before_artifact_delete,
    )

    member = _planner(tmp_path, "20261001090000", outcome="epic_approved")
    moment = time.time()
    _fresh_argv(member, now=moment)
    waiter = _waiter_dir(tmp_path, suffix="waiter")
    _write_waiting_json(waiter, _marker(["planner"], ["planner"]))

    undismissed = _decide(
        _index(member), _marker(["planner"], ["planner"]), waiter, now=moment
    )
    assert [f.state for f in undismissed.follows] == ["launching"]

    _resolve_waiters_before_artifact_delete(str(member))
    stored = json.loads((waiter / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_epic_follows"][0]["state"] == "blocked"
    assert stored["wait_epic_follows"][0]["reason"] == "target_dismissed_during_launch"
    assert stored.get("resolved_deps", []) == []
    assert not (waiter / "ready.json").exists()

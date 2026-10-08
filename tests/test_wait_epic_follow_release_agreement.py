"""Release agreement: runner, parked-runner, chop, and kill/dismiss paths.

Split from ``tests.test_wait_epic_follow_release``; shared builders live in
``tests._wait_epic_follow_release_helpers`` and the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests._wait_epic_follow_release_helpers import (
    build_release_index,
    decide_release,
    make_release_marker,
    make_release_planner,
    make_release_waiter,
    touch_release_launch_argv,
    write_waiting_marker,
)

__all__ = [
    "test_dismiss_launching_target_blocks_without_memoize",
    "test_release_paths_agree_on_promotion_snapshot",
    "test_release_paths_agree_on_unarmed_snapshot",
    "test_run_now_writes_unwait_ready_without_release_decision",
]


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

    planner = make_release_planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = make_release_waiter(tmp_path)
    marker = make_release_marker(["planner"], ["planner"])
    write_waiting_marker(waiter, marker)
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
    write_waiting_marker(waiter, marker)
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
    touch_release_launch_argv(member, now=moment)
    waiter = make_release_waiter(tmp_path, suffix="waiter")
    write_waiting_marker(waiter, make_release_marker(["planner"], ["planner"]))

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

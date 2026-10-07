"""Reducer-phase regressions: epic-follow fact collector over fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.core.wait_dependency_resolution import WaitDependencyIndex
from sase.core.wait_dependency_resolution._epic_follow import (
    collect_epic_follow_facts,
)
from tests._agent_names_fixtures import make_agent


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


def _update_meta(artifact_dir: Path, **updates: object) -> None:
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(updates)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _planner(
    tmp_path: Path,
    suffix: str,
    name: str = "planner",
    *,
    done: bool = True,
    outcome: str = "completed",
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


def test_unresolved_target_stays_agent(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", done=False, outcome=None)
    index = _index(planner)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={},
        now=1_800_000_000.0,
    )
    assert [decision.state for decision in decisions] == ["agent"]


def test_recorded_epic_follows_on_monitor_path(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={
            "created_epics": [
                {
                    "bead_id": "sase-7k",
                    "project": "proj",
                    "plan_ref": "202610/epic.md",
                    "created_at": "2026-10-01T09:05:00+00:00",
                    "via": "host_launch",
                }
            ]
        },
    )
    index = _index(planner)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={},
        now=1_800_000_000.0,
    )
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.state == "following"
    assert list(decision.epic_ids) == ["sase-7k"]
    assert list(decision.members) == ["planner"]


def test_proc_fallback_argv_is_launching_then_blocked(tmp_path: Path) -> None:
    import os
    import time

    # The proc-fallback planner is done (plan accepted) while its epic launch
    # runs outside the session: a fresh reservation reads LAUNCHING.
    planner = _planner(tmp_path, "20261001090000", done=True, outcome="epic_approved")
    (planner / "epic_launch_argv.json").write_text(
        json.dumps(
            {"argv": ["sase", "bead", "work", "202610/epic.md", "--yes-to-all"]}
        ),
        encoding="utf-8",
    )
    index = _index(planner)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={},
    )
    assert decisions[0].state == "launching"

    # An old reservation with no epic ends blocked with a resume command.
    old = time.time() - 10_000.0
    os.utime(planner / "epic_launch_argv.json", (old, old))
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={},
    )
    assert decisions[0].state == "blocked"
    assert decisions[0].reason == "launch_ended_without_epic"
    assert decisions[0].resume_command is not None
    assert "sase" in decisions[0].resume_command


def test_skip_mode_blocks_without_argv(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000", done=True, outcome="epic_approved")
    index = _index(planner)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={},
        now=1_800_000_000.0,
    )
    assert decisions[0].state == "blocked"
    assert decisions[0].reason == "launch_skipped"


def test_lost_record_healed_by_attribution(tmp_path: Path) -> None:
    planner = _planner(tmp_path, "20261001090000")
    (planner / "epic_launch_argv.json").write_text(
        json.dumps(
            {"argv": ["sase", "bead", "work", "202610/epic.md", "--yes-to-all"]}
        ),
        encoding="utf-8",
    )
    index = _index(planner)
    with patch(
        "sase.core.created_epics.attributed_epic_ids",
        return_value=["sase-7k"],
    ):
        decisions = collect_epic_follow_facts(
            index,
            armed_targets=["planner"],
            waiter_meta={},
            now=1_800_000_000.0,
        )
    assert decisions[0].state == "following"
    assert list(decisions[0].epic_ids) == ["sase-7k"]


def test_legacy_planner_follows(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"epic_bead_id": "sase-7k"},
    )
    index = _index(planner)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={},
        now=1_800_000_000.0,
    )
    assert decisions[0].state == "following"
    assert list(decisions[0].epic_ids) == ["sase-7k"]


def test_phase_worker_inherited_epic_is_none(tmp_path: Path) -> None:
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
    index = _index(worker)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["phase-1"],
        waiter_meta={},
        now=1_800_000_000.0,
    )
    assert decisions[0].state == "none"


def test_phase_worker_child_epic_follows(tmp_path: Path) -> None:
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
    index = _index(worker)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["phase-1"],
        waiter_meta={},
        now=1_800_000_000.0,
    )
    assert decisions[0].state == "following"
    assert list(decisions[0].epic_ids) == ["sase-7m"]


def test_deadlock_guard_skips_waiter_subtree(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    index = _index(planner)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={"phase_bead_id": "sase-7k.1"},
        now=1_800_000_000.0,
    )
    assert decisions[0].state == "none"
    assert list(decisions[0].skipped_epic_ids) == ["sase-7k"]


def test_pinned_following_target_is_skipped(tmp_path: Path) -> None:
    planner = _planner(
        tmp_path,
        "20261001090000",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    index = _index(planner)
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        previous_follows=[
            {"target": "planner", "state": "following", "since": 1_799_999_000.0}
        ],
        waiter_meta={},
        now=1_800_000_000.0,
    )
    assert decisions == []

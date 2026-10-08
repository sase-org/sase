"""Blocker-notification and cycle-guard tests for epic follows (safety phase)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts._chop_wait_checks_run as wait_checks_module
from sase.core.agent_artifact_index_lifecycle_mutations import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.wait_dependency_resolution import WaitDependencyIndex
from sase.core.wait_dependency_resolution._epic_follow import (
    collect_epic_follow_facts,
)
from sase.notifications.store import load_notifications
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def _use_tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def _index(*artifact_dirs: Path) -> None:
    for artifact_dir in artifact_dirs:
        update_agent_artifact_index_for_marker_mutation(artifact_dir)


def _point_bead_waits_at(monkeypatch: pytest.MonkeyPatch, closed_ids: set[str]) -> None:
    monkeypatch.setattr(
        wait_checks_module,
        "closed_bead_ids_for_waits",
        lambda *args, **kwargs: SimpleNamespace(closed_ids=frozenset(closed_ids)),
    )


def _notifications() -> list:
    return [n for n in load_notifications() if n.sender == "wait_checks"]


def _by_dedup(suffix: str):
    for row in load_notifications(include_dismissed=True):
        if (row.dedup_key or "").endswith(suffix):
            return row
    return None


def _make_planner(
    base: Path,
    *,
    outcome: str = "completed",
    created_epics: list[dict] | None = None,
    with_argv: bool = False,
) -> Path:
    planner = make_agent(
        base,
        "proj",
        "20261001090000",
        "planner",
        agent_session="planner",
        done=True,
        outcome=outcome,
        extra_meta=(
            {"created_epics": created_epics} if created_epics is not None else None
        ),
    )
    if with_argv:
        (planner / "epic_launch_argv.json").write_text(
            json.dumps(
                {"argv": ["sase", "bead", "work", "202610/epic.md", "--yes-to-all"]}
            ),
            encoding="utf-8",
        )
    return planner


def _seed_launching_follow(waiter_dir: Path, since: float) -> None:
    stored = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    stored["wait_epic_follows"] = [
        {
            "target": "planner",
            "state": "launching",
            "epic_ids": [],
            "added_bead_ids": [],
            "members": ["planner"],
            "since": since,
            "reason": None,
            "detail": None,
            "resume_command": None,
            "skipped_epic_ids": [],
        }
    ]
    (waiter_dir / "waiting.json").write_text(json.dumps(stored), encoding="utf-8")


def test_fresh_launching_stays_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_home(tmp_path, monkeypatch)
    planner = _make_planner(tmp_path, outcome="epic_approved", with_argv=True)
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    _index(planner, waiter_dir)
    _point_bead_waits_at(monkeypatch, set())
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    assert _notifications() == []


def test_overdue_launching_notifies_once_and_never_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_home(tmp_path, monkeypatch)
    planner = _make_planner(tmp_path, outcome="epic_approved", with_argv=True)
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    _seed_launching_follow(waiter_dir, since=time.time() - 3_600.0)
    _index(planner, waiter_dir)
    _point_bead_waits_at(monkeypatch, set())

    run_wait_checks(tmp_path, monkeypatch)
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    rows = _notifications()
    assert len(rows) == 1
    row = rows[0]
    assert row.dedup_key == f"wait_checks:epic-follow-launching:{waiter_dir}:planner"
    assert row.plus_one_count == 1
    assert any("waiting on planner's epic launch" in note for note in row.notes)
    assert any("no epic after 10m" in note for note in row.notes)
    assert str(waiter_dir) in row.files


def test_blocked_notifies_with_resume_and_jump_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_home(tmp_path, monkeypatch)
    planner = _make_planner(tmp_path, outcome="epic_approved", with_argv=True)
    old = time.time() - 10_000.0
    os.utime(planner / "epic_launch_argv.json", (old, old))
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    _index(planner, waiter_dir)
    _point_bead_waits_at(monkeypatch, set())

    run_wait_checks(tmp_path, monkeypatch)
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    rows = _notifications()
    assert len(rows) == 1
    row = rows[0]
    assert row.dedup_key == f"wait_checks:epic-follow-blocked:{waiter_dir}:planner"
    assert row.plus_one_count == 1
    assert row.action == "JumpToAgent"
    assert row.action_data.get("cl_name") == "waiter-cl"
    assert any("ended without an epic" in note for note in row.notes)
    resume_notes = [note for note in row.notes if "Resume with:" in note]
    assert len(resume_notes) == 1
    assert "sase" in resume_notes[0]


def test_blocked_entry_clears_when_epic_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_home(tmp_path, monkeypatch)
    planner = _make_planner(tmp_path, outcome="epic_approved", with_argv=True)
    old = time.time() - 10_000.0
    os.utime(planner / "epic_launch_argv.json", (old, old))
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    _index(planner, waiter_dir)
    _point_bead_waits_at(monkeypatch, set())
    run_wait_checks(tmp_path, monkeypatch)
    assert len(_notifications()) == 1

    meta_path = planner / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created_epics"] = [{"bead_id": "sase-7k"}]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    _index(planner)
    run_wait_checks(tmp_path, monkeypatch)

    stored = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_epic_follows"][0]["state"] == "following"
    cleared = _by_dedup(f":{waiter_dir}:planner")
    assert cleared is not None
    assert cleared.dismissed is True
    assert _notifications() == []


def test_followed_epic_land_failure_notifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_home(tmp_path, monkeypatch)
    planner = _make_planner(tmp_path, created_epics=[{"bead_id": "sase-7k"}])
    land_dir = make_agent(
        tmp_path,
        "proj",
        "20261001100000",
        "sase-7k.land",
        agent_session="sase-7k",
        done=True,
        outcome="failed",
        extra_meta={
            "agent_clan": "sase-7k",
            "agent_clan_generation": "20261001100000",
        },
    )
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    _index(planner, land_dir, waiter_dir)
    _point_bead_waits_at(monkeypatch, set())

    run_wait_checks(tmp_path, monkeypatch)
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    rows = _notifications()
    assert len(rows) == 1
    row = rows[0]
    assert row.dedup_key == f"wait_checks:epic-follow-land-failed:{waiter_dir}:sase-7k"
    assert row.plus_one_count == 1
    assert any("Waiter: waiter-cl" in note for note in row.notes)
    assert any("sase-7k" in note and "failed" in note for note in row.notes)
    assert any("sase-7k.land" in note for note in row.notes)
    assert str(waiter_dir) in row.files
    assert str(land_dir) in row.files


def test_land_failure_entry_clears_when_waiter_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_home(tmp_path, monkeypatch)
    planner = _make_planner(tmp_path, created_epics=[{"bead_id": "sase-7k"}])
    make_agent(
        tmp_path,
        "proj",
        "20261001100000",
        "sase-7k.land",
        agent_session="sase-7k",
        done=True,
        outcome="failed",
    )
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    _index(
        planner,
        tmp_path / ".sase/projects/proj/artifacts/ace-run/20261001100000",
        waiter_dir,
    )
    _point_bead_waits_at(monkeypatch, set())
    run_wait_checks(tmp_path, monkeypatch)
    assert len(_notifications()) == 1

    _point_bead_waits_at(monkeypatch, {"sase-7k"})
    run_wait_checks(tmp_path, monkeypatch)

    # The pinned epic bead makes this a bead wait, so the release-telemetry
    # payload carries released_by but no dependencies_satisfied_at.
    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["planner"],
        "released_by": "wait_checks",
    }
    cleared = _by_dedup(f":{waiter_dir}:sase-7k")
    assert cleared is not None
    assert cleared.dismissed is True
    assert _notifications() == []


def _collector_index(*artifact_dirs: Path) -> WaitDependencyIndex:
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


def _clan_member(
    tmp_path: Path,
    waiting_for: list[str],
    *,
    done: bool = False,
) -> Path:
    member = make_agent(
        tmp_path,
        "proj",
        "20261001110000",
        "worker",
        agent_session="sase-7k",
        done=done,
        outcome="completed" if done else None,
        extra_meta={
            "agent_clan": "sase-7k",
            "agent_clan_generation": "20261001110000",
        },
    )
    (member / "waiting.json").write_text(
        json.dumps({"waiting_for": waiting_for, "cl_name": "worker"}),
        encoding="utf-8",
    )
    return member


def test_cycle_blocks_when_clan_member_waits_on_waiter(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path, created_epics=[{"bead_id": "sase-7k"}])
    _clan_member(tmp_path, ["reviewer"])
    index = _collector_index(
        planner,
        tmp_path / ".sase/projects/proj/artifacts/ace-run/20261001110000",
    )
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={"name": "reviewer", "agent_session": "reviewer"},
        now=1_800_000_000.0,
    )
    assert [decision.state for decision in decisions] == ["blocked"]
    assert decisions[0].reason == "cycle"
    assert list(decisions[0].epic_ids) == ["sase-7k"]


def test_no_cycle_without_waiter_reference(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path, created_epics=[{"bead_id": "sase-7k"}])
    _clan_member(tmp_path, ["someone-else"])
    index = _collector_index(
        planner,
        tmp_path / ".sase/projects/proj/artifacts/ace-run/20261001110000",
    )
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={"name": "reviewer", "agent_session": "reviewer"},
        now=1_800_000_000.0,
    )
    assert [decision.state for decision in decisions] == ["following"]


def test_done_clan_member_is_not_a_cycle(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path, created_epics=[{"bead_id": "sase-7k"}])
    _clan_member(tmp_path, ["reviewer"], done=True)
    index = _collector_index(
        planner,
        tmp_path / ".sase/projects/proj/artifacts/ace-run/20261001110000",
    )
    decisions = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta={"name": "reviewer", "agent_session": "reviewer"},
        now=1_800_000_000.0,
    )
    assert [decision.state for decision in decisions] == ["following"]


def test_cycle_never_releases_on_timeout(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path, created_epics=[{"bead_id": "sase-7k"}])
    _clan_member(tmp_path, ["reviewer"])
    index = _collector_index(
        planner,
        tmp_path / ".sase/projects/proj/artifacts/ace-run/20261001110000",
    )
    waiter_meta: dict[str, object] = {
        "name": "reviewer",
        "agent_session": "reviewer",
    }
    first = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        waiter_meta=waiter_meta,
        now=1_800_000_000.0,
    )
    assert first[0].state == "blocked"
    second = collect_epic_follow_facts(
        index,
        armed_targets=["planner"],
        previous_follows=[
            {"target": "planner", "state": "blocked", "since": 1_700_000_000.0}
        ],
        waiter_meta=waiter_meta,
        now=1_900_000_000.0,
    )
    assert [decision.state for decision in second] == ["blocked"]
    assert second[0].reason == "cycle"


def test_chop_parks_cycle_blocked_waiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_home(tmp_path, monkeypatch)
    planner = _make_planner(tmp_path, created_epics=[{"bead_id": "sase-7k"}])
    _clan_member(tmp_path, ["reviewer"])
    member_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20261001110000"
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": "reviewer", "agent_session": "reviewer"}),
        encoding="utf-8",
    )
    _index(planner, member_dir, waiter_dir)
    _point_bead_waits_at(monkeypatch, set())
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    stored = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_epic_follows"][0]["state"] == "blocked"
    assert stored["wait_epic_follows"][0]["reason"] == "cycle"

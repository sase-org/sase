"""Epic-follow release tests for the wait_checks chop script."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts._chop_wait_checks_run as wait_checks_module
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def _launching_planner(base: Path) -> Path:
    planner = make_agent(
        base,
        "proj",
        "20261001090000",
        "planner",
        agent_session="planner",
        done=True,
        outcome="epic_approved",
    )
    (planner / "epic_launch_argv.json").write_text(
        json.dumps(
            {"argv": ["sase", "bead", "work", "202610/epic.md", "--yes-to-all"]}
        ),
        encoding="utf-8",
    )
    return planner


def _point_bead_waits_at(monkeypatch: pytest.MonkeyPatch, closed_ids: set[str]) -> None:
    monkeypatch.setattr(
        wait_checks_module,
        "closed_bead_ids_for_waits",
        lambda *args, **kwargs: SimpleNamespace(closed_ids=frozenset(closed_ids)),
    )


def test_armed_launching_planner_does_not_write_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _launching_planner(tmp_path)
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    stored = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_epic_follows"][0]["state"] == "launching"


def test_promotion_pass_parks_then_closed_epic_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20261001090000",
        "planner",
        agent_session="planner",
        done=True,
        outcome="completed",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    _point_bead_waits_at(monkeypatch, set())
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    stored = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert stored["wait_for_beads"] == ["sase-7k"]
    assert stored["wait_epic_follows"][0]["state"] == "following"

    _point_bead_waits_at(monkeypatch, {"sase-7k"})
    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner"], "released_by": "wait_checks"}


def test_ready_already_present_skips_waiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20261001090000",
        "planner",
        agent_session="planner",
        done=True,
        outcome="completed",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter_dir = make_waiting_agent(tmp_path, "planner", wait_for_epics_of=["planner"])
    (waiter_dir / "ready.json").write_text(
        json.dumps({"resolved_deps": ["planner"]}), encoding="utf-8"
    )
    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner"]}
    stored = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert "wait_epic_follows" not in stored

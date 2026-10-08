"""Wait release telemetry: sources, satisfied-at, and latency stamps.

Covers the ``release-telemetry`` phase: ``latest_member_finished_at``,
``wait_checks`` ``ready.json`` payloads (``released_by`` /
``dependencies_satisfied_at``), the runner's ``_DependencyResolution`` /
``_ReadyResult`` telemetry, ``wait_release_source`` stamping in
``agent_meta.json``, and ``admission_latency_s`` / ``runner_slot_wait_s``.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.run_agent_markers import record_run_started_at
from sase.axe.run_agent_wait import wait_for_dependencies
from sase.axe.run_agent_wait_deps import (
    _DependencyResolution,
    _ReadyResult,
    initial_dependencies_resolved,
    read_ready_result,
)
from sase.axe.run_agent_wait_markers import record_wait_completed_at
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    latest_member_finished_at,
    parse_finished_at,
)

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def _write_member_done(path: Path, payload: object) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "done.json").write_text(json.dumps(payload), encoding="utf-8")


def _disk_meta(artifacts_dir: Path) -> dict:
    return json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))


# --- latest_member_finished_at / parse_finished_at ---


def test_parse_finished_at_accepts_epochs_and_iso_strings() -> None:
    assert parse_finished_at(1_777_000_000.0) == 1_777_000_000.0
    assert parse_finished_at(42) == 42.0
    assert parse_finished_at("1_777_000_000".replace("_", "")) == 1_777_000_000.0
    iso_epoch = datetime(2026, 5, 6, 1, 1, 1, tzinfo=UTC).timestamp()
    assert parse_finished_at("2026-05-06T01:01:01+00:00") == pytest.approx(iso_epoch)
    assert parse_finished_at(None) is None
    assert parse_finished_at(True) is None
    assert parse_finished_at("") is None
    assert parse_finished_at("not-a-time") is None
    assert parse_finished_at(float("nan")) is None
    assert parse_finished_at({"finished_at": 1}) is None


def test_latest_member_finished_at_takes_max_and_ignores_unknown(
    tmp_path: Path,
) -> None:
    finished_base = tmp_path / "members"
    _write_member_done(
        finished_base / "a", {"outcome": "completed", "finished_at": 100.0}
    )
    _write_member_done(
        finished_base / "b",
        {"outcome": "completed", "finished_at": "2026-05-06T01:01:01+00:00"},
    )
    _write_member_done(finished_base / "c", {"outcome": "completed"})
    _write_member_done(
        finished_base / "d", {"outcome": "completed", "finished_at": True}
    )
    (finished_base / "e").mkdir(parents=True)
    (finished_base / "f").mkdir(parents=True)
    (finished_base / "f" / "done.json").write_text("{torn", encoding="utf-8")

    iso_epoch = datetime(2026, 5, 6, 1, 1, 1, tzinfo=UTC).timestamp()
    assert (
        latest_member_finished_at(
            [finished_base / "a", finished_base / "e", finished_base / "f"]
        )
        == 100.0
    )
    assert latest_member_finished_at(
        [finished_base / "a", finished_base / "b", finished_base / "c"]
    ) == pytest.approx(max(100.0, iso_epoch))
    assert latest_member_finished_at([finished_base / "c", finished_base / "e"]) is None
    assert latest_member_finished_at([]) is None


# --- truthy result types ---


def test_dependency_resolution_and_ready_result_bool_contract() -> None:
    assert bool(_DependencyResolution(True, 1.0)) is True
    assert bool(_DependencyResolution(False)) is False
    assert bool(_ReadyResult(True, "wait_checks", False, 1.0)) is True
    assert bool(_ReadyResult(False)) is False


def test_read_ready_result_carries_release_telemetry(tmp_path: Path) -> None:
    ready = tmp_path / "ready.json"
    ready.write_text(
        json.dumps(
            {
                "resolved_deps": ["wf"],
                "released_by": "wait_checks",
                "dependencies_satisfied_at": 1_777_000_000.0,
            }
        ),
        encoding="utf-8",
    )
    result = read_ready_result(str(ready))
    assert result
    assert result.released_by == "wait_checks"
    assert result.unwait is False
    assert result.dependencies_satisfied_at == 1_777_000_000.0


def test_read_ready_result_manual_marker_and_legacy_marker(
    tmp_path: Path,
) -> None:
    manual = tmp_path / "manual.json"
    manual.write_text(json.dumps({"resolved_deps": [], "unwait": True}))
    manual_result = read_ready_result(str(manual))
    assert manual_result
    assert manual_result.unwait is True
    assert manual_result.released_by is None
    assert manual_result.dependencies_satisfied_at is None

    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"resolved_deps": ["wf"]}))
    legacy_result = read_ready_result(str(legacy))
    assert legacy_result
    assert legacy_result.released_by is None
    assert legacy_result.unwait is False
    assert legacy_result.dependencies_satisfied_at is None


# --- initial_dependencies_resolved satisfied_at ---


def test_initial_resolution_reports_satisfied_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    dep_dir = make_agent(tmp_path, "proj", "20260506010101", "foo", done=True)
    finished_at = 1_777_000_000.0
    (dep_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "finished_at": finished_at}),
        encoding="utf-8",
    )

    result = initial_dependencies_resolved(
        ["foo"], [], project_name="proj", artifacts_dir=str(waiter_dir)
    )
    assert result
    assert result.satisfied_at == finished_at


def test_initial_resolution_omits_satisfied_at_for_bead_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.build_wait_dependency_index",
        lambda _project: WaitDependencyIndex.empty(),
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.closed_bead_ids_for_waits",
        lambda *args, **kwargs: SimpleNamespace(closed_ids=frozenset({"b-1"})),
    )

    result = initial_dependencies_resolved(
        [],
        [],
        wait_beads=["b-1"],
        project_name="proj",
        artifacts_dir=str(tmp_path),
    )
    assert result
    assert result.satisfied_at is None


# --- record_wait_completed_at ---


def test_record_wait_completed_at_stamps_source_and_latency(
    tmp_path: Path,
) -> None:
    released_at = 1_777_000_100.0
    record_wait_completed_at(
        str(tmp_path),
        {},
        wait_release_source="ready_json",
        wait_dependencies_satisfied_at=1_777_000_000.0,
        wait_released_at=released_at,
    )
    meta = _disk_meta(tmp_path)
    assert meta["wait_release_source"] == "ready_json"
    assert meta["wait_dependencies_satisfied_at"] == 1_777_000_000.0
    assert meta["wait_release_latency_s"] == pytest.approx(100.0)


def test_record_wait_completed_at_clamps_negative_latency(tmp_path: Path) -> None:
    record_wait_completed_at(
        str(tmp_path),
        {},
        wait_release_source="runner_fallback",
        wait_dependencies_satisfied_at=1_777_000_100.0,
        wait_released_at=1_777_000_000.0,
    )
    assert _disk_meta(tmp_path)["wait_release_latency_s"] == 0.0


def test_record_wait_completed_at_omits_telemetry_without_satisfied(
    tmp_path: Path,
) -> None:
    record_wait_completed_at(
        str(tmp_path), {}, wait_release_source="ready_json", wait_released_at=1.0
    )
    meta = _disk_meta(tmp_path)
    assert meta["wait_release_source"] == "ready_json"
    assert "wait_dependencies_satisfied_at" not in meta
    assert "wait_release_latency_s" not in meta


@pytest.mark.parametrize("source", ["startup", "manual", "timer"])
def test_record_wait_completed_at_omits_latency_keys_for_non_measured_sources(
    tmp_path: Path, source: str
) -> None:
    record_wait_completed_at(
        str(tmp_path),
        {},
        wait_release_source=source,
        wait_dependencies_satisfied_at=1_777_000_000.0,
        wait_released_at=1_777_000_100.0,
    )
    meta = _disk_meta(tmp_path)
    assert meta["wait_release_source"] == source
    assert "wait_dependencies_satisfied_at" not in meta
    assert "wait_release_latency_s" not in meta


def test_record_wait_completed_at_is_idempotent(tmp_path: Path) -> None:
    agent_meta: dict = {}
    record_wait_completed_at(
        str(tmp_path),
        agent_meta,
        wait_release_source="ready_json",
        wait_dependencies_satisfied_at=1_777_000_000.0,
        wait_released_at=1_777_000_100.0,
    )
    # A refreshed runner re-recording with different release info changes nothing.
    record_wait_completed_at(
        str(tmp_path),
        {},
        wait_release_source="runner_fallback",
        wait_dependencies_satisfied_at=2.0,
        wait_released_at=3.0,
    )
    meta = _disk_meta(tmp_path)
    assert meta["wait_release_source"] == "ready_json"
    assert meta["wait_dependencies_satisfied_at"] == 1_777_000_000.0


# --- record_run_started_at ---


def test_record_run_started_at_stamps_admission_and_slot_wait(
    tmp_path: Path,
) -> None:
    wait_completed = datetime.now(UTC) - timedelta(seconds=30)
    agent_meta: dict = {"wait_completed_at": wait_completed.isoformat()}
    slot_started = time.time() - 7
    record_run_started_at(str(tmp_path), agent_meta, slot_wait_started_at=slot_started)
    meta = _disk_meta(tmp_path)
    assert meta["admission_latency_s"] == pytest.approx(30.0, abs=5.0)
    assert meta["runner_slot_wait_s"] == pytest.approx(7.0, abs=5.0)


def test_record_run_started_at_omits_admission_without_wait(
    tmp_path: Path,
) -> None:
    record_run_started_at(str(tmp_path), {}, slot_wait_started_at=time.time())
    meta = _disk_meta(tmp_path)
    assert "admission_latency_s" not in meta
    assert meta["runner_slot_wait_s"] == pytest.approx(0.0, abs=5.0)


def test_record_run_started_at_is_idempotent(tmp_path: Path) -> None:
    agent_meta: dict = {"wait_completed_at": datetime.now(UTC).isoformat()}
    first = record_run_started_at(
        str(tmp_path), agent_meta, slot_wait_started_at=time.time() - 7
    )
    second = record_run_started_at(
        str(tmp_path), {}, slot_wait_started_at=time.time() - 700
    )
    assert first == second
    assert _disk_meta(tmp_path)["runner_slot_wait_s"] == pytest.approx(7.0, abs=5.0)


# --- wait_for_dependencies sources ---


def _make_waiter(base: Path) -> Path:
    artifact_dir = base / ".sase/projects/proj/artifacts/ace-run/waiter"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"pid": 123}),
        encoding="utf-8",
    )
    return artifact_dir


def test_wait_for_dependencies_startup_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    make_agent(
        tmp_path, "proj", "20260506010101", "dep", done=True, outcome="completed"
    )
    agent_meta: dict = {}
    with patch("sase.axe.run_agent_wait.was_killed", return_value=False):
        blocked = wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
        )
    assert blocked is False
    assert _disk_meta(waiter_dir)["wait_release_source"] == "startup"


def test_wait_for_dependencies_fallback_source_and_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dep_dir = make_agent(tmp_path, "proj", "20260506010101", "dep")
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def complete_dependency_after_poll(seconds: float) -> None:
        (dep_dir / "done.json").write_text(
            json.dumps({"outcome": "completed", "finished_at": time.time() - 5}),
            encoding="utf-8",
        )

    agent_meta: dict = {"pid": 123}
    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=complete_dependency_after_poll,
        ),
    ):
        blocked = wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
        )
    assert blocked is True
    meta = _disk_meta(waiter_dir)
    assert meta["wait_release_source"] == "runner_fallback"
    assert meta["wait_dependencies_satisfied_at"] == pytest.approx(
        time.time() - 5, abs=60.0
    )
    assert meta["wait_release_latency_s"] == pytest.approx(5.0, abs=60.0)


def test_wait_for_dependencies_manual_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    (waiter_dir / "ready.json").write_text(
        json.dumps({"resolved_deps": ["dep"], "unwait": True}), encoding="utf-8"
    )
    agent_meta: dict = {"pid": 123}
    with patch("sase.axe.run_agent_wait.was_killed", return_value=False):
        wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
        )
    meta = _disk_meta(waiter_dir)
    assert meta["wait_release_source"] == "manual"
    assert "wait_dependencies_satisfied_at" not in meta
    assert "wait_release_latency_s" not in meta


def test_wait_for_dependencies_timer_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    agent_meta: dict = {"pid": 123}
    with patch("sase.axe.run_agent_wait.was_killed", return_value=False):
        wait_for_dependencies(
            [],
            str(waiter_dir),
            "cl",
            "20260513120000",
            agent_meta,
            project_name="proj",
            duration=0,
        )
    assert _disk_meta(waiter_dir)["wait_release_source"] == "timer"


def test_wait_for_dependencies_bead_fallback_omits_satisfied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiter_dir = _make_waiter(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    closed_beads: set[str] = set()

    def close_bead_after_poll(seconds: float) -> None:
        closed_beads.add("sase-87.3")

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait._WAIT_DEPENDENCY_FALLBACK_INTERVAL", 0),
        patch(
            "sase.bead.store_locator.closed_bead_ids_for_project",
            side_effect=lambda _project: frozenset(closed_beads),
        ),
        patch(
            "sase.axe.run_agent_wait.time.sleep",
            side_effect=close_bead_after_poll,
        ),
    ):
        wait_for_dependencies(
            [],
            str(waiter_dir),
            "cl",
            "20260720120000",
            {"pid": 123},
            project_name="proj",
            wait_beads=["sase-87.3"],
        )
    meta = _disk_meta(waiter_dir)
    assert meta["wait_release_source"] == "runner_fallback"
    assert "wait_dependencies_satisfied_at" not in meta
    assert "wait_release_latency_s" not in meta


# --- wait_checks payload ---


def test_wait_checks_payload_carries_satisfied_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    dep_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    finished_at = 1_777_000_000.0
    (dep_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "finished_at": finished_at}),
        encoding="utf-8",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf.2",
        workflow_name="wf",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready["resolved_deps"] == ["wf"]
    assert ready["released_by"] == "wait_checks"
    assert ready["dependencies_satisfied_at"] == finished_at


def test_wait_checks_payload_omits_satisfied_at_for_bead_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead import store_locator as bead_store_locator

    root = tmp_path / "bead-store"
    with BeadProject.init(root) as project:
        closed_bead = project.create("Closed", IssueType.PLAN)
        project.close([closed_bead.id])
    monkeypatch.setattr(
        bead_store_locator,
        "canonical_beads_dir_for_project",
        lambda _project: root / "sdd/beads",
    )
    waiter_dir = make_waiting_agent(tmp_path, wait_for_beads=[closed_bead.id])

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready["released_by"] == "wait_checks"
    assert "dependencies_satisfied_at" not in ready

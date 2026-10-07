"""Record-phase regressions: `created_epics` write, readers, and wire."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.bead.epic_launch import _update_epic_launch_metadata
from sase.core.agent_scan_wire_conversion import _agent_meta_from_dict
from sase.core.agent_scan_wire_markers import CreatedEpicWire
from sase.core.agent_scan_wire import agent_scan_wire_to_json_dict
from sase.core.created_epics import (
    AGENT_COMMAND_VIA,
    HOST_LAUNCH_VIA,
    CreatedEpic,
    _attributed_from_issues,
    attributed_epic_ids,
    coerce_created_epics,
    created_epic_ids_from_meta,
    launched_epic_bead_id,
    record_created_epic,
    resolve_creator_artifacts_dir,
)


def _meta_dir(tmp_path: Path, payload: dict | None = None) -> Path:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(payload or {"name": "planner"}), encoding="utf-8"
    )
    return artifacts_dir


def _read_meta(artifacts_dir: Path) -> dict:
    return json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))


def test_record_writes_entry_and_dedupes_by_bead_id(tmp_path: Path) -> None:
    artifacts_dir = _meta_dir(tmp_path)
    with patch(
        "sase.core.agent_meta_update.update_agent_artifact_index_for_marker_mutation"
    ):
        first = record_created_epic(
            artifacts_dir,
            bead_id="sase-7k",
            project="demo",
            plan_ref="202610/epic.md",
            via=HOST_LAUNCH_VIA,
        )
        second = record_created_epic(
            artifacts_dir,
            bead_id="sase-7k",
            project="demo",
            plan_ref="202610/epic.md",
            via=HOST_LAUNCH_VIA,
        )

    assert first is not None and second is not None
    entries = _read_meta(artifacts_dir)["created_epics"]
    assert [entry["bead_id"] for entry in entries] == ["sase-7k"]
    assert entries[0]["project"] == "demo"
    assert entries[0]["plan_ref"] == "202610/epic.md"
    assert entries[0]["via"] == HOST_LAUNCH_VIA
    assert entries[0]["created_at"]


def test_record_never_fails_the_launch(tmp_path: Path) -> None:
    assert record_created_epic(None, bead_id="sase-7k") is None
    assert record_created_epic(tmp_path / "missing", bead_id="sase-7k") is None
    artifacts_dir = _meta_dir(tmp_path)
    assert record_created_epic(artifacts_dir, bead_id="  ") is None
    assert "created_epics" not in _read_meta(artifacts_dir)


def test_resolve_creator_prefers_explicit_dir_then_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    explicit = _meta_dir(tmp_path / "explicit")
    env_dir = _meta_dir(tmp_path / "env")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(env_dir))

    assert resolve_creator_artifacts_dir(explicit) == (explicit, HOST_LAUNCH_VIA)
    assert resolve_creator_artifacts_dir(None) == (env_dir, AGENT_COMMAND_VIA)

    (env_dir / "agent_meta.json").unlink()
    assert resolve_creator_artifacts_dir(None) == (None, None)

    monkeypatch.delenv("SASE_ARTIFACTS_DIR")
    assert resolve_creator_artifacts_dir(None) == (None, None)
    assert resolve_creator_artifacts_dir(tmp_path / "missing") == (None, None)


def test_concurrent_writers_keep_every_epic(tmp_path: Path) -> None:
    artifacts_dir = _meta_dir(tmp_path)
    with patch(
        "sase.core.agent_meta_update.update_agent_artifact_index_for_marker_mutation"
    ):
        threads = [
            threading.Thread(
                target=record_created_epic,
                args=(artifacts_dir,),
                kwargs={"bead_id": f"sase-7{k}"},
            )
            for k in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

    assert sorted(
        entry["bead_id"] for entry in _read_meta(artifacts_dir)["created_epics"]
    ) == [f"sase-7{k}" for k in range(8)]


def test_worker_epic_bead_id_is_preserved(tmp_path: Path) -> None:
    worker = _meta_dir(
        tmp_path / "worker",
        {
            "name": "sase-1h7.1",
            "epic_bead_id": "sase-1h7",
            "phase_bead_id": "sase-1h7.1",
        },
    )
    planner = _meta_dir(tmp_path / "planner", {"name": "planner"})

    with patch(
        "sase.core.agent_meta_update.update_agent_artifact_index_for_marker_mutation"
    ):
        _update_epic_launch_metadata(
            worker, epic_id="sase-9z", sdd_plan_path="plans/child.md"
        )
        _update_epic_launch_metadata(
            planner, epic_id="sase-9z", sdd_plan_path="plans/child.md"
        )
        recorded = record_created_epic(worker, bead_id="sase-9z")

    worker_meta = _read_meta(worker)
    assert worker_meta["epic_bead_id"] == "sase-1h7"
    assert recorded is not None
    assert created_epic_ids_from_meta(worker_meta) == ["sase-9z"]

    planner_meta = _read_meta(planner)
    assert planner_meta["epic_bead_id"] == "sase-9z"
    assert planner_meta["plan_committed"] is True


def test_reader_priority_and_legacy_rules() -> None:
    recorded = {"created_epics": [{"bead_id": "sase-7k"}], "epic_bead_id": "sase-1"}
    assert created_epic_ids_from_meta(recorded) == ["sase-7k"]
    assert launched_epic_bead_id(recorded) == "sase-7k"

    legacy = {"epic_bead_id": "sase-1"}
    assert created_epic_ids_from_meta(legacy) == ["sase-1"]

    worker_legacy = {"epic_bead_id": "sase-1", "phase_bead_id": "sase-1.1"}
    assert created_epic_ids_from_meta(worker_legacy) == []
    assert launched_epic_bead_id(worker_legacy) is None

    plan_ref_worker = {"epic_bead_id": "sase-1", "epic_plan_ref": "202610/e.md"}
    assert created_epic_ids_from_meta(plan_ref_worker) == []

    assert created_epic_ids_from_meta({}) == []
    assert coerce_created_epics([{"nope": 1}, "sase-2", 42]) == [
        CreatedEpic(bead_id="sase-2")
    ]


def _issue(bead_id: str, *, created_by: str = "", design: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=bead_id, created_by=created_by, design=design)


def test_attribution_matches_creator_and_plan() -> None:
    issues = [
        _issue("sase-7k", created_by="agent:planner", design="202610/epic.md"),
        _issue("sase-7m", created_by="agent:planner", design="/x/202610/epic.md"),
        _issue("sase-7n", created_by="agent:other", design="202610/epic.md"),
        _issue("sase-7o", created_by="agent:planner", design="202610/other.md"),
        _issue("sase-7p", created_by="agent:planner", design=""),
    ]
    assert _attributed_from_issues(
        issues, creator="agent:planner", plan_ref="202610/epic.md"
    ) == ["sase-7k", "sase-7m"]
    assert _attributed_from_issues(
        issues,
        creator="agent:planner",
        plan_ref=None,
        plan_basename="epic.md",
    ) == ["sase-7k", "sase-7m"]
    assert _attributed_from_issues(issues, creator="agent:planner", plan_ref=None) == []
    assert attributed_epic_ids("", creator_global_name="agent:planner") == []


def test_scan_wire_round_trips_created_epics() -> None:
    wire = _agent_meta_from_dict(
        {
            "name": "planner",
            "created_epics": [
                {
                    "bead_id": "sase-7k",
                    "project": "demo",
                    "plan_ref": "202610/epic.md",
                    "created_at": "2026-10-06T00:00:00+00:00",
                    "via": "host_launch",
                    "unknown": "ignored",
                },
                {"bead_id": ""},
            ],
        }
    )
    assert wire.created_epics == [
        CreatedEpicWire(
            bead_id="sase-7k",
            project="demo",
            plan_ref="202610/epic.md",
            created_at="2026-10-06T00:00:00+00:00",
            via="host_launch",
        )
    ]
    assert agent_scan_wire_to_json_dict(wire)["created_epics"] == [
        {
            "bead_id": "sase-7k",
            "project": "demo",
            "plan_ref": "202610/epic.md",
            "created_at": "2026-10-06T00:00:00+00:00",
            "via": "host_launch",
        }
    ]
    assert _agent_meta_from_dict({"name": "planner"}).created_epics == []

"""Helpers for operational epic_resume soak tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_epic_resume as epic_resume
from sase.artifacts import create_artifacts_directory
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.core.paths import sase_projects_dir
from sase.notification_gates.paths import interaction_requests_dir
from sase.scripts._bead_gate_projects import ProjectInventory

from tests._axe_chop_epic_resume_helpers import make_runtime

PROJECT = "epic-soak"
GENERATION = "20260821100000"
FAILED_TS = "260821_100000"
WAITING_TS = "260821_100100"
LIVE_TS = "260821_110000"
LIVE_GENERATION = "20260821110000"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def iso_seconds_ago(seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def seed_project_spec() -> Path:
    project_dir = sase_projects_dir() / PROJECT
    project_dir.mkdir(parents=True, exist_ok=True)
    spec = project_dir / f"{PROJECT}.sase"
    spec.write_text(
        f"PROJECT_NAME: {PROJECT}\nPROJECT_STATE: enabled\nNAME: Epic Soak\n",
        encoding="utf-8",
    )
    return spec


def plant_member(
    *,
    timestamp: str,
    name: str,
    bead_id: str,
    epic_id: str,
    generation: str = GENERATION,
    outcome: str | None = None,
    finished_at: float | None = None,
    stopped_at: str | None = None,
    pid: int | None = None,
) -> Path:
    artifact_dir = Path(
        create_artifacts_directory("ace-run", PROJECT, timestamp=timestamp)
    )
    meta: dict[str, Any] = {
        "name": name,
        "bead_id": bead_id,
        "agent_clan": epic_id,
        "agent_clan_generation": generation,
        "clan_tribe": "epic",
        "epic_bead_id": epic_id,
        "phase_bead_id": bead_id,
    }
    if pid is not None:
        meta["pid"] = pid
    if stopped_at is not None:
        meta["stopped_at"] = stopped_at
    write_json(artifact_dir / "agent_meta.json", meta)
    if outcome is not None:
        done: dict[str, Any] = {"outcome": outcome, "name": name}
        if finished_at is not None:
            done["finished_at"] = finished_at
        write_json(artifact_dir / "done.json", done)
    return artifact_dir


def init_stalled_epic(tmp_path: Path) -> tuple[Path, str, str, str]:
    with BeadProject.init(tmp_path) as project:
        epic = project.create(
            "Soak stalled epic resume",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        failed = project.create(
            "Failing phase",
            IssueType.PHASE,
            epic.id,
            size="small",
        )
        waiting = project.create(
            "Waiting phase",
            IssueType.PHASE,
            epic.id,
            size="small",
        )
        project.update(failed.id, status="in_progress")
        return project.beads_dir, epic.id, failed.id, waiting.id


def plant_settled_stall(
    *,
    epic_id: str,
    failed_bead_id: str,
    waiting_bead_id: str,
    age_seconds: int = 180,
    include_done_finished_at: bool = False,
) -> None:
    seed_project_spec()
    stopped_at = iso_seconds_ago(age_seconds)
    finished_at = (
        datetime.now(UTC).timestamp() - age_seconds
        if include_done_finished_at
        else None
    )
    plant_member(
        timestamp=FAILED_TS,
        name=f"{epic_id}.1",
        bead_id=failed_bead_id,
        epic_id=epic_id,
        outcome="failed",
        finished_at=finished_at,
        stopped_at=stopped_at,
    )
    plant_member(
        timestamp=WAITING_TS,
        name=f"{epic_id}.2",
        bead_id=waiting_bead_id,
        epic_id=epic_id,
    )


def run_chop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    beads_dir: Path,
    *,
    settle_seconds: int = 120,
) -> Any:
    monkeypatch.setattr(
        epic_resume,
        "_enabled_project_stores",
        lambda _log: ProjectInventory(
            stores=((PROJECT, beads_dir),),
            sweep_allowed=True,
        ),
    )
    monkeypatch.setattr(
        epic_resume, "get_epic_resume_settle_seconds", lambda: settle_seconds
    )
    return epic_resume._run(make_runtime(tmp_path))


def load_epic_resume_requests() -> list[dict[str, Any]]:
    kind_dir = interaction_requests_dir() / "epic_resume"
    if not kind_dir.is_dir():
        return []
    requests: list[dict[str, Any]] = []
    for bundle in sorted(kind_dir.iterdir()):
        request_path = bundle / "request.json"
        if not request_path.is_file():
            continue
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            requests.append(payload)
    return requests

"""Shared support for the split doctor bead checks tests."""

from __future__ import annotations

import json
from pathlib import Path

from sase.bead.model import Issue
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
)
from sase.doctor.runner import DoctorContext

__all__ = ["context", "stub_agent_scan", "stub_issues"]


def context(tmp_path: Path, project: str | None = None) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=project,
        sase_home=tmp_path / ".sase",
    )


def stub_agent_scan(
    monkeypatch,
    tmp_path: Path,
    *,
    agent_name: str,
    bead_id: str,
    agent_meta: dict[str, object],
    pid: int | None,
) -> None:
    """Publish one ace-run artifact record backed by a real metadata file."""
    artifact_dir = tmp_path / "artifacts" / agent_name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"name": agent_name, "bead_id": bead_id, **agent_meta}),
        encoding="utf-8",
    )

    def scan(
        root: Path,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        return AgentArtifactScanWire(
            schema_version=4,
            projects_root=str(root),
            options=options,
            stats=AgentArtifactScanStatsWire(),
            records=[
                AgentArtifactRecordWire(
                    project_name="proj",
                    project_dir=str(root / "proj"),
                    project_file=str(root / "proj" / "proj.sase"),
                    workflow_dir_name="ace-run",
                    artifact_dir=str(artifact_dir),
                    timestamp="20260725120000",
                    agent_meta=AgentMetaWire(
                        name=agent_name,
                        bead_id=bead_id,
                        pid=pid,
                    ),
                )
            ],
        )

    monkeypatch.setattr("sase.doctor.checks_beads.scan_agent_artifacts", scan)


def stub_issues(monkeypatch, issues: list[Issue]) -> None:
    """Route the bead reads of ``_check_project_beads`` at ``issues``."""
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: no issues found"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.list_issues",
        lambda _path, statuses=None: list(issues),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {"open": 0, "claimed": 0, "in_progress": 0, "closed": 0},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )

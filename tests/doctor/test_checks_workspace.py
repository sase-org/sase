"""Tests for Phase 3 doctor workspace registry checks."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_workspace import _check_workspace_registry
from sase.doctor.runner import DoctorContext
from sase.workspace_provider.registry import (
    SCHEMA_VERSION,
    WorkspaceEntry,
    WorkspaceRegistry,
)


def _record(
    tmp_path: Path,
    primary: Path,
    *,
    active_claim_count: int = 0,
) -> ProjectRecordWire:
    project_dir = tmp_path / "projects" / "alpha"
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="alpha",
        project_dir=str(project_dir),
        project_file=str(project_dir / "alpha.sase"),
        archive_file=None,
        workspace_dir=str(primary),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=active_claim_count,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
    )


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project="alpha",
        sase_home=tmp_path / ".sase",
    )


def _patch_resolution(monkeypatch, record: ProjectRecordWire) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_workspace.resolve_current_project_record",
        lambda _context: SimpleNamespace(
            requested_project="alpha",
            inferred_project=None,
            project_name="alpha",
            record=record,
            records=(record,),
            matched_by="project_name",
            error=None,
        ),
    )


def test_workspace_registry_skips_missing_registry_without_claims(
    monkeypatch, tmp_path
) -> None:
    primary = tmp_path / "alpha"
    primary.mkdir()
    record = _record(tmp_path, primary)
    _patch_resolution(monkeypatch, record)
    monkeypatch.setattr(
        "sase.doctor.checks_workspace.load_merged_config",
        lambda: {
            "workspace": {
                "root": str(tmp_path / "workspace-root"),
                "project_key": "alpha-key",
            }
        },
    )

    check = _check_workspace_registry(_context(tmp_path))

    assert check.status == "SKIP"
    assert "registry is not present" in check.summary
    assert check.data["registry_exists"] is False


def test_workspace_registry_warns_for_missing_checkout_entry(
    monkeypatch, tmp_path
) -> None:
    primary = tmp_path / "alpha"
    primary.mkdir()
    root = tmp_path / "workspace-root" / "alpha-key"
    root.mkdir(parents=True)
    record = _record(tmp_path, primary)
    _patch_resolution(monkeypatch, record)
    monkeypatch.setattr(
        "sase.doctor.checks_workspace.load_merged_config",
        lambda: {
            "workspace": {
                "root": str(tmp_path / "workspace-root"),
                "project_key": "alpha-key",
            }
        },
    )
    registry = WorkspaceRegistry(
        project_key="alpha-key",
        primary_workspace_dir=str(primary),
        schema_version=SCHEMA_VERSION,
        workspaces={
            "0": WorkspaceEntry(
                checkout_dir=str(primary),
                materialization="primary",
                role="primary",
                created_at=1.0,
                last_used_at=1.0,
                pinned=True,
            ),
            "10": WorkspaceEntry(
                checkout_dir=str(tmp_path / "missing"),
                materialization="git-clone",
                role="claim",
                created_at=1.0,
                last_used_at=1.0,
            ),
        },
    )
    (root / "registry.json").write_text(
        json.dumps(asdict(registry)),
        encoding="utf-8",
    )

    check = _check_workspace_registry(_context(tmp_path))

    assert check.status == "WARN"
    assert "workspace #10 path is missing" in check.details[0]
    assert check.data["missing_checkout_count"] == 1

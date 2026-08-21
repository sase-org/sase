"""Tests for artifact-link doctor health."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.artifact_cli.doctor import handle_doctor
from sase.artifact_cli.link_health import ArtifactLinkHealthReport
from sase.artifact_cli.link_health import inspect_artifact_link_health
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.core.artifact_file_facade import ArtifactFileIndexInspection
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home


def test_inspect_reports_store_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: (_ for _ in ()).throw(RuntimeError("bad project key")),
    )
    report = inspect_artifact_link_health()
    assert report.skipped is False
    assert report.errors == ("bad project key",)
    assert report.healthy is False


def test_inspect_treats_existing_bead_refs_as_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path / "beads") as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={},
            beads_dir=project.beads_dir,
        )
        store.upsert_row(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "source_ref": f"bead:{left.id}",
                "relation": "related",
                "target_ref": f"bead:{right.id}",
                "description": "same root cause",
                "origin": "manual",
                "created_by": "agent",
                "created_at": "2026-08-21T00:00:00Z",
                "uses": 1,
            }
        )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_cli_reference",
        lambda _ref: (_ for _ in ()).throw(RuntimeError("no generated page")),
    )

    report = inspect_artifact_link_health()

    assert report.dangling == ()
    assert report.healthy is True


def test_doctor_reports_skipped_link_checks_for_missing_store(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_file_index",
        lambda: ArtifactFileIndexInspection(
            total_rows=0,
            supported_rows=0,
            vcs_reference_rows=0,
            missing_enrichment_ids=(),
            missing_stored_path_ids=(),
            missing_source_path_ids=(),
            vcs_provenance_incomplete_ids=(),
            duplicate_ids=(),
            unrecognized_schema_versions=(),
            malformed_rows=0,
        ),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_link_health",
        lambda *, fix=False: ArtifactLinkHealthReport(skipped=True),
    )
    assert handle_doctor(argparse.Namespace(fix=False, verify=False)) == 0
    output = capsys.readouterr().out
    assert "healthy" in output
    assert "skipped (no store)" in output

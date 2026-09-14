"""Tests for the artifact-link doctor CLI output."""

from __future__ import annotations

import argparse

import pytest

from sase.artifact_cli._link_health_coverage import ArtifactLinkCoverageReport
from sase.artifact_cli._link_health_coverage import _ArtifactLinkCoveragePopulation
from sase.artifact_cli.doctor import handle_doctor
from sase.artifact_cli.link_health import ArtifactLinkHealthReport
from sase.core.artifact_file_facade import ArtifactFileIndexInspection


def test_doctor_reports_link_divergence_counters(
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
        lambda *, fix=False: ArtifactLinkHealthReport(
            skipped=False,
            read_events=3,
            recorded_read_events=2,
            durable_read_rows=1,
            durable_sidecar_rows=4,
            aggregate_rows=5,
            outbox_entries=3,
            outbox_event_entries=2,
            outbox_oldest_age_seconds=90,
            outbox_p95_age_seconds=80,
            event_objects=7,
            event_pending=2,
            publication_pending=("gh_sase-org__sase/plans: /tmp/plans (90s)",),
            coverage=ArtifactLinkCoverageReport(
                populations=(
                    _ArtifactLinkCoveragePopulation(
                        name="research-swarm filename lineage",
                        linked=1,
                        total=2,
                    ),
                ),
                rows_by_origin=(("derived", 2), ("manual", 3)),
                rows_by_relation=(("derives-from", 2), ("related", 3)),
            ),
        ),
    )

    assert handle_doctor(argparse.Namespace(fix=False, verify=False)) == 0
    output = capsys.readouterr().out
    assert "Sidecar vs aggregate links" in output
    assert "4 durable / 5 aggregate" in output
    assert "Read events vs durable rows" in output
    assert "2 recorded / 1 durable" in output
    assert "Derived coverage" in output
    assert "1 linked / 2 candidates" in output
    assert "Rows by origin" in output
    assert "derived: 2, manual: 3" in output
    assert "Rows by relation" in output
    assert "derives-from: 2, related: 3" in output
    assert "Link event objects" in output
    assert "7 durable / 2 pending" in output
    assert "Read-link outbox" in output
    assert "3 queued / 2 events" in output
    assert "oldest" in output
    assert "90s" in output
    assert "p95" in output
    assert "80s" in output
    assert "Artifact-link publications pending" in output


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

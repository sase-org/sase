"""Tests for artifact-link doctor health."""

from __future__ import annotations

import argparse

import pytest

from sase.artifact_cli.doctor import handle_doctor
from sase.artifact_cli.link_health import inspect_artifact_link_health
from sase.core.artifact_file_facade import ArtifactFileIndexInspection
from sase.feature_flags import override_flags


def test_inspect_skips_when_flag_is_off() -> None:
    with override_flags(artifact_links=False):
        report = inspect_artifact_link_health()
    assert report.skipped is True
    assert report.enabled is False
    assert report.healthy is True


def test_doctor_reports_skipped_link_checks(
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
    with override_flags(artifact_links=False):
        assert handle_doctor(argparse.Namespace(fix=False, verify=False)) == 0
    output = capsys.readouterr().out
    assert "healthy" in output
    assert "artifact_links disabled" in output

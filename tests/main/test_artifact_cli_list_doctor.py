"""Focused list and doctor tests for ``sase artifact``."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from sase.artifact_cli.doctor import handle_doctor
from sase.artifact_cli.link_health import ArtifactLinkHealthReport
from sase.artifact_cli.listing import handle_list
from sase.core.artifact_file_facade import (
    ArtifactFile,
    ArtifactFileBackfillReport,
    ArtifactFileDigestMismatch,
    ArtifactFileIndexInspection,
    ArtifactFileVerifyReport,
)
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)


def _list_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "agent": None,
        "explicit": False,
        "json": False,
        "kind": None,
        "limit": 50,
        "project": None,
        "query": None,
        "since": None,
        "unused": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _artifact(**overrides: Any) -> ArtifactFile:
    defaults: dict[str, Any] = {
        "id": "explicit:0123456789abcdef01234567",
        "label": "Release report",
        "kind": "markdown",
        "path": "/stored/report.md",
        "source_path": "/source/report.md",
        "workspace_dir": "/workspace",
        "created_at": "2026-07-29T12:34:56Z",
        "agent_artifacts_dir": "/agents/run",
        "project": "gh_sase-org__sase",
        "workflow": "ace-run",
        "raw_timestamp": "20260729123456",
        "agent_name": "agent.one",
        "explicit": True,
        "sha256": "abc",
        "size_bytes": 1536,
        "mime_type": "text/markdown",
    }
    defaults.update(overrides)
    return ArtifactFile(**defaults)


def _projects() -> ProjectRefDisplaySnapshot:
    return ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"}),
        aliases={"ss": "gh_sase-org__sase"},
    )


def test_list_resolves_project_passes_filters_and_renders_display_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.listing.load_project_ref_display_snapshot",
        _projects,
    )

    def fake_query(**kwargs: object) -> list[ArtifactFile]:
        calls.append(dict(kwargs))
        return [_artifact()]

    monkeypatch.setattr(
        "sase.artifact_cli.listing.query_artifact_files",
        fake_query,
    )

    assert (
        handle_list(
            _list_args(
                agent="agent.one",
                explicit=True,
                kind=["markdown"],
                limit=3,
                project="ss",
                query="report",
                since="14d",
                unused=True,
            )
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Release" in output
    assert "sase" in output
    assert "gh_sase-org__sase" not in output
    assert "1.5 KiB" in output
    assert "2026-07-29 08:34" in output
    assert calls == [
        {
            "kinds": ["markdown"],
            "project": "gh_sase-org__sase",
            "agent": "agent.one",
            "since": "14d",
            "explicit_only": True,
            "query": "report",
            "limit": 3,
            "unused_only": True,
        }
    ]


def test_list_json_contains_every_record_field_and_ref(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.listing.load_project_ref_display_snapshot",
        _projects,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.listing.query_artifact_files",
        lambda **_kwargs: [_artifact()],
    )

    assert handle_list(_list_args(json=True)) == 0

    [payload] = json.loads(capsys.readouterr().out)
    assert list(payload) == [
        "id",
        "label",
        "kind",
        "path",
        "source_path",
        "workspace_dir",
        "created_at",
        "agent_artifacts_dir",
        "project",
        "workflow",
        "raw_timestamp",
        "agent_name",
        "explicit",
        "sha256",
        "size_bytes",
        "mime_type",
        "vcs_repo",
        "vcs_sha",
        "vcs_relpath",
        "ref",
    ]
    assert payload["project"] == "gh_sase-org__sase"
    assert payload["ref"] == "file:explicit:0123456789abcdef01234567"


def test_list_empty_output_and_unknown_project_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.listing.load_project_ref_display_snapshot",
        _projects,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.listing.query_artifact_files",
        lambda **_kwargs: [],
    )

    assert handle_list(_list_args()) == 0
    assert "No artifacts found." in capsys.readouterr().out
    assert handle_list(_list_args(project="unknown")) == 2
    assert "unknown project reference" in capsys.readouterr().err


def test_list_unused_filter_is_named_in_empty_panel(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.listing.load_project_ref_display_snapshot",
        _projects,
    )

    def fake_query(**kwargs: object) -> list[ArtifactFile]:
        calls.append(dict(kwargs))
        return []

    monkeypatch.setattr(
        "sase.artifact_cli.listing.query_artifact_files",
        fake_query,
    )

    assert handle_list(_list_args(unused=True)) == 0

    output = capsys.readouterr().out
    assert "Artifacts (0, unused)" in output
    assert calls[0]["unused_only"] is True


def _inspection(**overrides: object) -> ArtifactFileIndexInspection:
    defaults: dict[str, object] = {
        "total_rows": 1,
        "supported_rows": 1,
        "missing_enrichment_ids": (),
        "missing_stored_path_ids": (),
        "missing_source_path_ids": (),
        "duplicate_ids": (),
        "unrecognized_schema_versions": (),
        "malformed_rows": 0,
    }
    defaults.update(overrides)
    return ArtifactFileIndexInspection(**defaults)  # type: ignore[arg-type]


def test_doctor_health_ignores_missing_source_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_file_index",
        lambda: _inspection(missing_source_path_ids=("artifact-id",)),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_link_health",
        lambda *, fix=False: ArtifactLinkHealthReport(skipped=True),
    )

    assert handle_doctor(argparse.Namespace(fix=False, verify=False)) == 0
    output = capsys.readouterr().out
    assert "healthy" in output
    assert "artifact-id" in output
    assert "informational" in output


def test_doctor_fix_then_verify_reports_changed_ids_and_health(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    order: list[str] = []

    def backfill() -> ArtifactFileBackfillReport:
        order.append("fix")
        return ArtifactFileBackfillReport(1, ("fixed-id",), (), ())

    def inspect() -> ArtifactFileIndexInspection:
        order.append("inspect")
        return _inspection()

    def verify() -> ArtifactFileVerifyReport:
        order.append("verify")
        return ArtifactFileVerifyReport(1, ("fixed-id",), (), (), (), ())

    monkeypatch.setattr(
        "sase.artifact_cli.doctor.backfill_artifact_file_index",
        backfill,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_file_index",
        inspect,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.verify_artifact_file_index",
        verify,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_link_health",
        lambda *, fix=False: ArtifactLinkHealthReport(skipped=True),
    )

    assert handle_doctor(argparse.Namespace(fix=True, verify=True)) == 0
    assert order == ["fix", "inspect", "verify"]
    output = capsys.readouterr().out
    assert "fixed-id" in output
    assert "Backfilled ids" in output
    assert "Verified ids" in output


def test_doctor_unhealthy_for_structural_and_digest_problems(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_file_index",
        lambda: _inspection(
            missing_enrichment_ids=("no-digest",),
            duplicate_ids=("duplicate",),
            malformed_rows=1,
        ),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.verify_artifact_file_index",
        lambda: ArtifactFileVerifyReport(
            1,
            (),
            ("no-digest",),
            (),
            (
                ArtifactFileDigestMismatch(
                    "mismatch",
                    "/stored/file",
                    "expected",
                    "actual",
                ),
            ),
            (),
        ),
    )

    assert handle_doctor(argparse.Namespace(fix=False, verify=True)) == 1
    output = capsys.readouterr().out
    assert "unhealthy" in output
    assert "duplicate" in output
    assert "mismatch" in output

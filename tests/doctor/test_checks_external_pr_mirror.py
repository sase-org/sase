"""Doctor coverage for the external PR mirror check."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_external_pr_mirror import _check_external_pr_mirror
from sase.doctor.runner import DoctorContext
from sase.external_mirror.pr_sync import KIND
from sase.external_mirror.state import (
    BackoffEntry,
    MirrorCursor,
    write_backoff_state,
    write_mirror_cursor,
)


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def _record(
    tmp_path: Path,
    *,
    project_name: str = "proj",
    display_name: str = "Proj",
    workspace_dir: str | None = "/repo",
    vcs_kind: str | None = "git",
) -> ProjectRecordWire:
    project_dir = tmp_path / project_name
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{project_name}.sase"),
        archive_file=str(project_dir / f"{project_name}-archive.sase"),
        workspace_dir=workspace_dir,
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name=display_name,
        is_project=True,
        vcs_kind=vcs_kind,
    )


def test_external_pr_mirror_doctor_ok_for_unsupported_provider(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.lumberjack_state_dir",
        lambda _name: tmp_path,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.list_project_records",
        lambda *_args, **_kwargs: [_record(tmp_path)],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.supports_pull_requests",
        lambda _workspace_dir: False,
    )

    check = _check_external_pr_mirror(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["project_count"] == 1
    assert check.data["projects"][0]["reason"] == "pull_requests_unsupported"


def test_external_pr_mirror_doctor_warns_on_stale_cursor(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.lumberjack_state_dir",
        lambda _name: tmp_path,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.list_project_records",
        lambda *_args, **_kwargs: [_record(tmp_path)],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.supports_pull_requests",
        lambda _workspace_dir: True,
    )

    check = _check_external_pr_mirror(_context(tmp_path))

    assert check.status == "WARN"
    assert check.data["warnings"] == 1
    assert check.data["projects"][0]["reason"] == "stale_cursor"
    assert check.next_steps


def test_external_pr_mirror_doctor_errors_on_repeated_backoff_failures(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.lumberjack_state_dir",
        lambda _name: tmp_path,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.list_project_records",
        lambda *_args, **_kwargs: [_record(tmp_path)],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_external_pr_mirror.supports_pull_requests",
        lambda _workspace_dir: True,
    )
    write_mirror_cursor(
        tmp_path,
        KIND,
        "proj",
        MirrorCursor(last_updated_at=datetime.now(UTC)),
    )
    write_backoff_state(
        tmp_path,
        KIND,
        {
            "proj": BackoffEntry(
                failures=3,
                next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
                last_error="auth failed",
            )
        },
    )

    check = _check_external_pr_mirror(_context(tmp_path))

    assert check.status == "ERROR"
    assert check.data["errors"] == 1
    assert check.data["projects"][0]["reason"] == "repeated_failures"

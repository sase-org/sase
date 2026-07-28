"""Tests for doctor checks over the agent publication outbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_agent_publication import _check_agent_publication_outbox
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def _record(tmp_path: Path, *, name: str = "alpha") -> ProjectRecordWire:
    project_dir = tmp_path / ".sase" / "projects" / name
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / name),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )


def _item(
    *,
    project_key: str = "alpha",
    local_agent: str = "foo--code",
    revision: str = "a" * 40,
    attempts: int = 0,
    last_error: str | None = None,
    quarantined: bool = False,
    created_at: float = 100.0,
    updated_at: float = 100.0,
) -> dict[str, object]:
    hood = local_agent.split("--", 1)[0]
    return AgentPublicationOutboxItem(
        project_key=project_key,
        project="Alpha",
        local_agent=local_agent,
        global_agent=f"alice.athena.{local_agent}",
        primary_revision=revision,
        local_hood=hood,
        attempts=attempts,
        last_error=last_error,
        quarantined=quarantined,
        quarantined_at=updated_at if quarantined else None,
        created_at=created_at,
        updated_at=updated_at,
    ).to_json_dict()


def _write_outbox(
    root: Path,
    project_key: str,
    rows: list[dict[str, object]],
) -> Path:
    path = root / "projects" / project_key / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": 2, "items": rows}),
        encoding="utf-8",
    )
    return path


def test_agent_publication_outbox_doctor_reports_clean_outbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    _write_outbox(tmp_path / ".sase", "alpha", [])

    check = _check_agent_publication_outbox(_context(tmp_path), now=200.0)

    assert check.status == "OK"
    assert "no quarantined or stalled requests" in check.summary
    assert check.data["request_count"] == 0
    assert check.data["quarantined_request_count"] == 0
    assert check.data["stalled_request_count"] == 0


def test_agent_publication_outbox_doctor_reports_quarantined_and_stalled_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    _write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            _item(
                local_agent="bad--code",
                revision="b" * 40,
                attempts=3,
                last_error="committing agent absent from project inventory",
                quarantined=True,
                created_at=now - 120,
                updated_at=now - 60,
            ),
            _item(
                local_agent="slow--code",
                revision="c" * 40,
                attempts=3,
                last_error="git pull --rebase failed",
                created_at=now - 2 * 24 * 60 * 60,
                updated_at=now - 60,
            ),
        ],
    )

    check = _check_agent_publication_outbox(
        _context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "1 quarantined, 1 stalled" in check.summary
    assert "sase agent sync --retry-quarantined" in check.summary
    assert "bad--code" in check.details[0]
    assert "quarantined" in check.details[0]
    assert "slow--code" in check.details[1]
    assert "stalled: attempts >= 3" in check.details[1]
    assert check.next_steps == (
        "Run `sase agent sync --retry-quarantined` to release quarantined requests and retry publication.",
    )
    assert check.data["request_count"] == 2
    assert check.data["quarantined_request_count"] == 1
    assert check.data["stalled_request_count"] == 1

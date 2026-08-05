"""Tests for doctor checks over the agent publication outbox."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentOwnerIdentity
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
    terminal: bool = False,
    terminal_reason: str | None = None,
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
        terminal=terminal,
        terminal_reason=terminal_reason,
        created_at=created_at,
        updated_at=updated_at,
    ).to_json_dict()


def _write_outbox(
    root: Path,
    project_key: str,
    rows: list[dict[str, object]],
    *,
    schema_version: int = 2,
) -> Path:
    path = root / "projects" / project_key / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": schema_version, "items": rows}),
        encoding="utf-8",
    )
    return path


def _axe_snapshot(*, state: str = "running") -> SimpleNamespace:
    return SimpleNamespace(
        lumberjacks=(
            SimpleNamespace(
                name="publications",
                configured=True,
                configured_chops=("sidecar_publication",),
                state=state,
            ),
        )
    )


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
    monkeypatch.setattr(
        "sase.axe.status_collector.collect_axe_status_snapshot",
        lambda: _axe_snapshot(),
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


def test_agent_publication_outbox_doctor_reports_typed_queue_not_draining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.axe.status_collector.collect_axe_status_snapshot",
        lambda: _axe_snapshot(state="not_reporting"),
    )
    _write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            AgentPublicationOutboxItem(
                project_key="alpha",
                project="Alpha",
                kind="bead_pages",
                bead_id="alpha-1.2",
                lineage_root="alpha-1",
                primary_revision="e" * 40,
                created_at=100.0,
                updated_at=100.0,
            ).to_json_dict(),
            AgentPublicationOutboxItem(
                project_key="alpha",
                project="Alpha",
                kind="plan_header",
                plan_ref="plans:202608/example.md",
                primary_revision="f" * 40,
                commit_message="feat: example",
                created_at=101.0,
                updated_at=101.0,
            ).to_json_dict(),
        ],
        schema_version=4,
    )

    check = _check_agent_publication_outbox(
        _context(tmp_path),
        now=200.0,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "2 not draining" in check.summary
    assert "sase axe ensure" in check.summary
    assert "bead lineage alpha-1@eeeeeeeeeeee" in check.details[0]
    assert "not draining: publications lumberjack is not_reporting" in check.details[0]
    assert check.next_steps == (
        "Run `sase axe ensure` to start or heal the publications lumberjack.",
    )
    assert check.data["request_kind_counts"] == {
        "bead_pages": 1,
        "plan_header": 1,
    }
    assert check.data["active_kind_counts"] == {
        "bead_pages": 1,
        "plan_header": 1,
    }
    assert check.data["not_draining_request_count"] == 2
    assert check.data["problems"][0]["kind"] == "bead_pages"
    assert check.data["problems"][1]["kind"] == "plan_header"


def test_agent_publication_outbox_doctor_points_retired_requests_at_the_drop_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    reason = "hood 'lt' has no publishable runs"
    _write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            _item(
                local_agent="lt--code",
                revision="d" * 40,
                attempts=2,
                last_error=reason,
                terminal=True,
                terminal_reason=reason,
                created_at=now - 120,
                updated_at=now - 60,
            )
        ],
    )

    check = _check_agent_publication_outbox(
        _context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "1 retired" in check.summary
    assert "sase agent sync --drop-retired" in check.summary
    assert "sase agent sync --retry-quarantined" not in check.summary
    assert "retired as unpublishable" in check.details[0]
    assert check.next_steps == (
        "Run `sase agent sync --drop-retired` to drop retired requests that can never be published.",
    )
    assert check.data["retired_request_count"] == 1
    assert check.data["quarantined_request_count"] == 0
    assert check.data["stalled_request_count"] == 0
    assert check.data["problems"][0]["remediation_command"] == (
        "sase agent sync --drop-retired"
    )


def test_agent_publication_doctor_warns_on_unreadable_local_owner_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    sidecar = tmp_path / "agents"
    sidecar.mkdir()
    manifest = sidecar / "users" / "alice" / "machines" / "athena" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")
    target = ProjectTarget(
        "alpha",
        "Alpha",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        "git@example.test:alpha--agents.git",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    _write_outbox(tmp_path / ".sase", "alpha", [])

    check = _check_agent_publication_outbox(_context(tmp_path), now=200.0)

    assert check.status == "WARN"
    assert "unreadable owner manifest" in check.summary
    assert "sase agent sync --retry-quarantined" in check.summary
    assert str(manifest) in check.details[0]
    assert "missing required keys" in check.details[0]
    assert check.data["owner_manifest_problem_count"] == 1
    assert check.data["owner_manifest_problems"][0]["manifest_path"] == str(manifest)


def test_agent_publication_doctor_accepts_healthy_local_owner_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    sidecar = tmp_path / "agents"
    sidecar.mkdir()
    target = ProjectTarget(
        "alpha",
        "Alpha",
        tmp_path / "primary",
        (tmp_path / "primary",),
        sidecar,
        "git@example.test:alpha--agents.git",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.resolve_sync_targets",
        lambda *_args, **_kwargs: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    _write_outbox(tmp_path / ".sase", "alpha", [])

    check = _check_agent_publication_outbox(_context(tmp_path), now=200.0)

    assert check.status == "OK"
    assert check.data["owner_manifest_problem_count"] == 0
    assert check.data["owner_manifest_problems"] == ()

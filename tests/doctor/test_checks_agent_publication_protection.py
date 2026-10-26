"""Tests for value-free doctor reporting of publication-protection state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_agent_publication import agent_publication_check_specs
from sase.doctor.checks_agent_publication_protection import (
    _check_agent_publication_protection,
)
from sase.doctor.runner import DoctorContext


def _project(tmp_path: Path) -> ProjectRecordWire:
    project_dir = tmp_path / ".sase" / "projects" / "alpha"
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="alpha",
        project_dir=str(project_dir),
        project_file=str(project_dir / "alpha.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / "alpha"),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def test_doctor_reports_counts_and_safe_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SYNTHETIC_SECRET_DO_NOT_SHOW"
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_protection.list_project_records",
        lambda *_args, **_kwargs: [_project(tmp_path)],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_protection.read_publication_protection_ledger_from_path",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "records": [
                {
                    "repository_identity": "sase-org/sase--agents",
                    "relative_destination": "agents/alice/run/chat.md",
                    "sha256": "a" * 64,
                    "status": "blocked",
                    "reason": "scanner_hit",
                    "affected_requests": ["request-a"],
                    "evidence": [
                        {
                            "kind": "known_value",
                            "rule_id": "known-value",
                            "line": 5,
                            "rules_version": 1,
                        }
                    ],
                    "rules_versions": [1],
                    "created_at": 1.0,
                    "updated_at": 1.0,
                    "private_candidate_bytes": secret,
                },
                {
                    "repository_identity": "sase-org/sase--agents",
                    "relative_destination": "agents/alice/run/prompt.md",
                    "sha256": "b" * 64,
                    "status": "unverified",
                    "reason": "scan_skipped",
                    "affected_requests": [],
                    "evidence": [],
                    "rules_versions": [1],
                    "created_at": 2.0,
                    "updated_at": 2.0,
                },
            ],
        },
    )

    check = _check_agent_publication_protection(_context(tmp_path))

    assert check.status == "WARN"
    assert check.data["blocked_count"] == 1
    assert check.data["unverified_count"] == 1
    serialized = json.dumps(check.to_dict())
    assert secret not in serialized
    assert "a" * 64 not in serialized
    assert "sase-org/sase--agents" not in serialized
    assert "agents/alice/run/chat.md" in serialized
    assert "known-value" in serialized
    assert check.next_steps[0].startswith("Sanitize blocked source content")


def test_doctor_skips_projects_without_a_ledger_and_is_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_protection.list_project_records",
        lambda *_args, **_kwargs: [_project(tmp_path)],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_protection.read_publication_protection_ledger_from_path",
        lambda *_args, **_kwargs: None,
    )

    check = _check_agent_publication_protection(_context(tmp_path))
    specs = agent_publication_check_specs(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["blocked_count"] == 0
    assert check.data["unverified_count"] == 0
    assert any(spec.id == "state.agent_publication_protection" for spec in specs)

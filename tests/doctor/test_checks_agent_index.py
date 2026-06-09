"""Tests for Phase 3 doctor agent-index checks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_agent_index import _check_agent_index
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def test_agent_index_warns_when_repair_recommended(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_agent_index.build_agent_index_status_payload",
        lambda: {
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "index_exists": True,
            "schema_version": 3,
            "visible_rows": 0,
            "dismissed_projection_rows": 0,
            "complete_visible_inbox": False,
            "repair_recommended": True,
            "repair_reason": "artifact_index_query_soft_errors",
            "verify_command": "sase agents index verify",
            "repair_command": "sase agents index gc",
            "normal_refresh": "visible-inbox artifact-index query",
        },
    )

    check = _check_agent_index(_context(tmp_path))

    assert check.status == "WARN"
    assert "repair recommended" in check.summary
    assert check.next_steps == (
        "Run `sase agents index verify`.",
        "Repair with `sase agents index gc`.",
    )
    assert check.data["repair_reason"] == "artifact_index_query_soft_errors"


def test_agent_index_ok_when_status_payload_is_clean(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_agent_index.build_agent_index_status_payload",
        lambda: {
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "index_exists": True,
            "schema_version": 3,
            "visible_rows": 12,
            "dismissed_projection_rows": 2,
            "complete_visible_inbox": True,
            "repair_recommended": False,
            "repair_reason": None,
            "normal_refresh": "visible-inbox artifact-index query",
        },
    )

    check = _check_agent_index(_context(tmp_path))

    assert check.status == "OK"
    assert "schema 3" in check.summary
    assert check.data["visible_rows"] == 12

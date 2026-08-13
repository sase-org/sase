"""Tests for ``project.patch_refs`` diagnostics."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_changespec_refs import _check_patch_refs
from sase.doctor.runner import DoctorContext
from tests.artifact_refs.helpers import context as make_context


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project="sase",
        sase_home=tmp_path / ".sase",
    )


def _record(tmp_path: Path, *refs: str) -> ProjectRecordWire:
    project_dir = tmp_path / "projects" / "sase"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "sase.sase"
    refs_section = (
        "REFS:\n" + "".join(f"  {reference}\n" for reference in refs) if refs else ""
    )
    project_file.write_text(
        f"NAME: sase_feature\nDESCRIPTION:\n  Example\nSTATUS: Draft\n{refs_section}",
        encoding="utf-8",
    )
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="sase",
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(tmp_path),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )


def _select_record(monkeypatch, record: ProjectRecordWire) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_changespec_refs.resolve_current_project_record",  # legacy module path
        lambda _context: SimpleNamespace(record=record),
    )


def test_patch_refs_reports_healthy_batch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "plan:resolved.md")
    context = make_context(tmp_path)
    plan = context.document_roots[1].root / "resolved.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Resolved\n", encoding="utf-8")
    _select_record(monkeypatch, record)
    monkeypatch.setattr(
        "sase.doctor.checks_changespec_refs._reference_context",  # legacy module path
        lambda _record: context,
    )

    check = _check_patch_refs(_context(tmp_path))

    assert check.status == "OK"
    assert "all 1" in check.summary
    assert check.data["findings"] == ()


def test_patch_refs_groups_unresolvable_entries(
    monkeypatch,
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "plan:missing.md")
    context = make_context(tmp_path)
    _select_record(monkeypatch, record)
    monkeypatch.setattr(
        "sase.doctor.checks_changespec_refs._reference_context",  # legacy module path
        lambda _record: context,
    )

    check = _check_patch_refs(_context(tmp_path))

    assert check.status == "WARN"
    assert check.details == (
        "WARNING: unresolvable artifact references (1): sase_feature [plan:missing.md]",
    )
    assert check.data["findings"][0]["status"] == "missing"


def test_patch_refs_skips_when_reference_context_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "plan:missing.md")
    _select_record(monkeypatch, record)
    monkeypatch.setattr(
        "sase.doctor.checks_changespec_refs._reference_context",  # legacy module path
        lambda _record: None,
    )

    check = _check_patch_refs(_context(tmp_path))

    assert check.status == "SKIP"
    assert "context is unavailable" in check.summary

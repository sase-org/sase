"""Tests for Phase 3 doctor project checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_project import (
    _check_junk_project_directories,
    _check_project_current,
    project_check_specs,
)
from sase.doctor.runner import DoctorContext


def _record(
    tmp_path: Path,
    *,
    name: str = "alpha",
    state: str = "enabled",
    workspace_dir: str | None = "/tmp/alpha",
    launchable: bool = True,
    parse_warnings: list[str] | None = None,
) -> ProjectRecordWire:
    project_dir = tmp_path / name
    project_file = project_dir / f"{name}.sase"
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=name,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=workspace_dir,
        state=state,
        state_explicit=state != "enabled",
        system_managed=False,
        active_claim_count=0,
        launchable=launchable,
        aliases=[],
        warnings=[],
        parse_warnings=parse_warnings or [],
    )


def _context(tmp_path: Path, project: str | None = "alpha") -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=project,
        sase_home=tmp_path / ".sase",
    )


def test_project_current_warns_for_disabled_project(monkeypatch, tmp_path) -> None:
    record = _record(tmp_path, state="disabled", launchable=False)
    monkeypatch.setattr(
        "sase.doctor.checks_project.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    check = _check_project_current(_context(tmp_path))

    assert check.status == "WARN"
    assert "state=disabled" in check.summary
    assert "project state is disabled" in check.details
    assert check.next_steps == ("Run `sase project enable alpha`.",)


def test_project_current_skips_when_no_project_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_project.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _cwd: None,
    )

    check = _check_project_current(_context(tmp_path, project=None))

    assert check.status == "SKIP"
    assert "no SASE project" in check.summary


def test_project_current_resolves_alias(monkeypatch, tmp_path) -> None:
    record = _record(tmp_path, name="alpha")
    record = replace(record, aliases=["docs"])
    monkeypatch.setattr(
        "sase.doctor.checks_project.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    context = _context(tmp_path, project="docs")

    check = _check_project_current(context)

    assert check.status == "OK"
    assert context.project == "alpha"
    assert check.data["matched_by"] == "alias"


def test_project_junk_directories_lists_missing_projectspecs(tmp_path: Path) -> None:
    projects_root = tmp_path / ".sase" / "projects"
    (projects_root / "alpha").mkdir(parents=True)
    (projects_root / "alpha" / "alpha.sase").write_text("NAME: alpha\n")
    (projects_root / "basher").mkdir()
    (projects_root / "symvision").mkdir()
    (projects_root / "home").mkdir()

    check = _check_junk_project_directories(_context(tmp_path))

    assert check.status == "WARN"
    assert check.summary == "found 2 project directories without a ProjectSpec"
    assert check.details == (
        f"{projects_root / 'basher'}: missing basher.sase",
        f"{projects_root / 'symvision'}: missing symvision.sase",
    )
    assert check.data["junk_directory_count"] == 2
    assert "manually remove any obsolete state" in check.next_steps[0]


def test_project_junk_directories_is_clean_when_every_directory_has_spec(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / ".sase" / "projects"
    project_dir = projects_root / "alpha"
    project_dir.mkdir(parents=True)
    (project_dir / "alpha.sase").write_text("NAME: alpha\n")

    check = _check_junk_project_directories(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["junk_directory_count"] == 0


def test_project_check_specs_registers_junk_directory_check(tmp_path: Path) -> None:
    ids = [spec.id for spec in project_check_specs(_context(tmp_path))]

    assert ids == ["project.current", "project.junk_directories"]

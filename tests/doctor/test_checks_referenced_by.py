"""Tests for Referenced By index doctor checks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_referenced_by import (
    _check_referenced_by_index,
    referenced_by_check_specs,
)
from sase.doctor.runner import DoctorContext
from sase.sdd.store import SddStore


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def test_referenced_by_check_specs_register_the_index_check(tmp_path: Path) -> None:
    specs = referenced_by_check_specs(_context(tmp_path))

    assert [spec.id for spec in specs] == ["project.referenced_by_index"]


def test_referenced_by_index_check_skips_without_store(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_referenced_by._resolve_store",
        lambda _context: None,
    )

    check = _check_referenced_by_index(_context(tmp_path))

    assert check.status == "SKIP"
    assert "no SDD store" in check.summary


def test_referenced_by_index_check_errors_on_missing_index(
    monkeypatch, tmp_path: Path
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_referenced_by._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_referenced_by.document_sidecar_roles",
        lambda _roles, include_plans=False: ("plans",),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_referenced_by.missing_referenced_by_indexes",
        lambda _root: ("202608/example.md",),
    )

    check = _check_referenced_by_index(_context(tmp_path))

    assert check.status == "ERROR"
    assert check.details == ("plans:202608/example.md",)
    assert "missing links/ JSON" in check.summary


def test_referenced_by_index_check_ok_when_indexes_present(
    monkeypatch, tmp_path: Path
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_referenced_by._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_referenced_by.document_sidecar_roles",
        lambda _roles, include_plans=False: ("plans",),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_referenced_by.missing_referenced_by_indexes",
        lambda _root: (),
    )

    check = _check_referenced_by_index(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["missing"] == ()

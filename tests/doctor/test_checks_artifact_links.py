from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.doctor.checks_artifact_links import (
    _check_artifact_links_aggregate,
    artifact_links_check_specs,
)
from sase.doctor.runner import DoctorContext
from sase.sdd.store import SddStore
from tests._conftest_environment import redirect_sase_home


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project="gh_sase-org__sase",
        sase_home=tmp_path / ".sase",
    )


def test_artifact_links_check_specs_register_the_aggregate_check(
    tmp_path: Path,
) -> None:
    specs = artifact_links_check_specs(_context(tmp_path))
    assert [spec.id for spec in specs] == ["project.artifact_links_aggregate"]


def test_artifact_links_check_skips_without_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: None,
    )
    check = _check_artifact_links_aggregate(_context(tmp_path))
    assert check.status == "SKIP"
    assert "no SDD store" in check.summary


def test_artifact_links_check_errors_without_project_key(
    monkeypatch, tmp_path: Path
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: None,
    )
    check = _check_artifact_links_aggregate(_context(tmp_path))
    assert check.status == "ERROR"
    assert "canonical project key" in check.summary


def test_artifact_links_check_ok_when_empty(monkeypatch, tmp_path: Path) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: "gh_sase-org__sase",
    )
    check = _check_artifact_links_aggregate(_context(tmp_path))
    assert check.status == "OK"
    assert check.data["rows"] == 0


def test_artifact_links_check_reports_row_level_and_projected_drift(
    monkeypatch, tmp_path: Path
) -> None:
    store = SddStore("sidecar_repos", tmp_path, tmp_path)
    expected_rows = [
        {
            "schema_version": 2,
            "source_ref": "agent:pending.athena.worker",
            "relation": "cites",
            "target_ref": "plan:202608/a.md",
            "description": "prompt citation",
            "origin": "prompt_ref",
            "created_by": "agent",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        },
        {
            "schema_version": 2,
            "source_ref": "chop:hooks/build",
            "relation": "launched",
            "target_ref": "agent:alice.athena.9w",
            "description": "chop launch metadata",
            "origin": "projected",
            "created_by": "projection:chop-agent",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        },
    ]
    adapter = SimpleNamespace(
        load_aggregate=lambda: {"schema_version": 2, "generation": 1, "rows": []},
        preview_aggregate=lambda: {
            "schema_version": 2,
            "generation": 1,
            "rows": expected_rows,
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._resolve_store",
        lambda _context: store,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links._project_key",
        lambda _context: "gh_sase-org__sase",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_artifact_links.ArtifactLinkStore.from_sdd_store",
        lambda _store, _project_key: adapter,
    )

    check = _check_artifact_links_aggregate(_context(tmp_path))

    assert check.status == "ERROR"
    assert check.data["missing_rows"] == 2
    assert check.data["projected_rows"] == 1
    assert check.data["missing_by_relation"] == {"cites": 1, "launched": 1}
    assert "missing 2 row(s)" in str(check.next_steps)
    assert "cites: 1" in str(check.next_steps)

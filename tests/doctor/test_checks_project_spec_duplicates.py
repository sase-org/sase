"""Doctor coverage for duplicate ProjectSpec Patch blocks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_project_spec_duplicates import _check_project_spec_duplicates
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def test_project_spec_duplicate_check_skips_without_projects_root(
    tmp_path: Path,
) -> None:
    check = _check_project_spec_duplicates(_context(tmp_path))

    assert check.status == "SKIP"
    assert check.data["project_count"] == 0


def test_project_spec_duplicate_check_ok_on_clean_projects_root(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / ".sase" / "projects"
    project_dir = projects_root / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "proj.sase").write_text(
        "NAME: one\nSTATUS: WIP\n\n\nNAME: two\nSTATUS: Ready\n",
        encoding="utf-8",
    )

    check = _check_project_spec_duplicates(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["project_count"] == 0
    assert check.data["reclaimable_bytes"] == 0


def test_project_spec_duplicate_check_warns_with_data_and_display_label(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / ".sase" / "projects"
    project_dir = projects_root / "gh_acme__widgets"
    project_dir.mkdir(parents=True)
    (project_dir / "gh_acme__widgets.sase").write_text(
        "PROJECT_NAME: widgets\n"
        "\n"
        "\n"
        "NAME: one\n"
        "STATUS: WIP\n"
        "\n"
        "\n"
        "NAME: one\n"
        "STATUS: Ready\n",
        encoding="utf-8",
    )

    check = _check_project_spec_duplicates(_context(tmp_path))

    assert check.status == "WARN"
    assert check.data["project_count"] == 1
    assert check.data["duplicate_name_count"] == 1
    assert check.data["dropped_block_count"] == 1
    assert check.data["reclaimable_bytes"] > 0
    assert check.details == (
        f"WARN: widgets: 1 duplicate name(s), {check.data['reclaimable_bytes']} "
        "bytes reclaimable",
    )
    row = check.data["projects"][0]
    assert row["project"] == "gh_acme__widgets"
    assert row["label"] == "widgets"
    assert row["active_duplicate_name_count"] == 1
    assert row["archive_duplicate_name_count"] == 0


def test_project_spec_duplicate_check_errors_when_root_scan_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / ".sase" / "projects"
    projects_root.mkdir(parents=True)

    def fail_scan(*, projects_root: Path) -> object:
        raise OSError("permission denied")

    monkeypatch.setattr(
        "sase.doctor.checks_project_spec_duplicates.plan_duplicate_block_repairs",
        fail_scan,
    )

    check = _check_project_spec_duplicates(_context(tmp_path))

    assert check.status == "ERROR"
    assert "permission denied" in check.details[0]

"""Tests for Phase 3 doctor plugin adapter."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_plugins import _check_plugins_doctor
from sase.doctor.runner import DoctorContext
from sase.plugins.chops import ChopInventory
from sase.plugins.doctor import DoctorCheck, DoctorReport
from sase.plugins.inventory import PluginInventory


def _context(tmp_path: Path, *, verbose: bool = False) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        verbose=verbose,
    )


def test_plugins_doctor_adapts_existing_report(monkeypatch, tmp_path) -> None:
    report = DoctorReport(
        status="WARN",
        plugin_inventory=PluginInventory(
            entry_points=(),
            distributions=(),
            disabled_env=(),
        ),
        chop_inventory=ChopInventory(
            configured_chops=(),
            available_scripts=(),
            chop_script_dirs=(),
            python_bin_dir="/bin",
            path_dirs=(),
        ),
        checks=(
            DoctorCheck(
                id="resource_entry_points",
                status="OK",
                summary="resources ok",
            ),
            DoctorCheck(
                id="available_unconfigured_chops",
                status="WARN",
                summary="Executable chop scripts are installed but not configured.",
                next_steps=("Update axe.lumberjacks.",),
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_plugins.build_plugin_doctor_report",
        lambda: report,
    )

    check = _check_plugins_doctor(_context(tmp_path))

    assert check.id == "plugins.doctor"
    assert check.status == "WARN"
    assert "1 warning" in check.summary
    assert check.details == (
        "WARN: available_unconfigured_chops: Executable chop scripts are installed but not configured.",
    )
    assert check.next_steps == ("Update axe.lumberjacks.",)
    assert check.data["problem_check_count"] == 1

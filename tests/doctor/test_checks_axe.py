"""Tests for the ``axe.chops`` doctor check."""

from __future__ import annotations

from pathlib import Path

from sase.axe.chop_doctor import build_chop_doctor_report
from sase.axe.chop_inventory import collect_chop_inventory
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.doctor.checks_axe import _check_axe_chops
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path, *, verbose: bool = False) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        verbose=verbose,
    )


def test_axe_chops_check_errors_on_missing_configured_chop(
    monkeypatch, tmp_path
) -> None:
    config = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                interval=10,
                chops=[ChopConfig(name="missing", description="")],
            )
        }
    )
    inventory = collect_chop_inventory(config)
    monkeypatch.setattr(
        "sase.doctor.checks_axe.build_chop_doctor_report",
        lambda: build_chop_doctor_report(inventory=inventory),
    )

    check = _check_axe_chops(_context(tmp_path))

    assert check.id == "axe.chops"
    assert check.group == "axe"
    assert check.status == "ERROR"
    assert check.data["counts"]["ERROR"] >= 1
    assert any("cannot be resolved" in detail for detail in check.details)


def test_axe_chops_check_ok_when_clean(monkeypatch, tmp_path) -> None:
    inventory = collect_chop_inventory(AxeConfig())
    monkeypatch.setattr(
        "sase.doctor.checks_axe.build_chop_doctor_report",
        lambda: build_chop_doctor_report(inventory=inventory),
    )

    check = _check_axe_chops(_context(tmp_path))

    assert check.status in {"OK", "WARN", "SKIP"}
    assert (
        check.data["problem_check_count"]
        == check.data["counts"]["WARN"] + (check.data["counts"]["ERROR"])
    )

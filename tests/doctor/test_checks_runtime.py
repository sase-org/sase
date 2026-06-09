"""Tests for Phase 2 doctor runtime checks."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from sase.doctor.checks_runtime import _check_runtime_environment
from sase.doctor.runner import DoctorContext
from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord


def _record(
    *,
    source_root: str,
    install_type: Literal["editable", "wheel"] = "editable",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name="sase",
        role="host",
        display_version="0.1.3",
        distribution_version="0.1.3",
        source_version="0.1.3",
        import_module="sase",
        import_path=f"{source_root}/src/sase",
        code_directory=f"{source_root}/src/sase",
        source_root=source_root,
        distribution_location="/venv/site-packages",
        install_type=install_type,
        git=None,
    )


def _context(cwd: Path, source_root: str) -> DoctorContext:
    context = DoctorContext(cwd=cwd, project=None, sase_home=cwd / ".sase")
    context._runtime_inventory = RuntimeVersionInventory(
        executable="/bin/sase",
        python_executable="/bin/python",
        python_version="3.12.8",
        packages=(_record(source_root=source_root),),
    )
    return context


def test_runtime_environment_warns_on_editable_source_root_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    installed = tmp_path / "installed"
    installed.mkdir()

    monkeypatch.setattr(
        "sase.doctor.checks_runtime._current_checkout_root",
        lambda _cwd: checkout,
    )

    check = _check_runtime_environment(_context(checkout, str(installed)))

    assert check.status == "WARN"
    assert "differs from the current checkout" in check.summary
    assert "just install" in check.next_steps[0]


def test_runtime_environment_ok_when_editable_source_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(
        "sase.doctor.checks_runtime._current_checkout_root",
        lambda _cwd: checkout,
    )

    check = _check_runtime_environment(_context(checkout, str(checkout)))

    assert check.status == "OK"

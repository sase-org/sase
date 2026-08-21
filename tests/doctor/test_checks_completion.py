"""Tests for the completion doctor checks."""

from __future__ import annotations

from pathlib import Path

from sase.completion.install import ShellInstallStatus
from sase.completion.install_stamp import InstallStamp
from sase.doctor.checks_completion import (
    _check_completion_install,
    _check_completion_registration,
    completion_check_specs,
)
from sase.doctor.runner import default_doctor_context


def _row(
    shell: str,
    *,
    status: str,
    path: str | None = "/tmp/_sase",
    zwc: str = "fresh",
    stamp: str | None = "0.16.0",
    owner: str | None = "local",
) -> ShellInstallStatus:
    return ShellInstallStatus(shell, True, status, path, zwc, stamp, owner)


def test_completion_check_specs_register_default_and_deep() -> None:
    specs = completion_check_specs(default_doctor_context())
    by_id = {spec.id: spec for spec in specs}
    assert by_id["completion.install"].deep is False
    assert by_id["completion.registration"].deep is True


def test_install_check_skips_when_nothing_is_stamped() -> None:
    check = _check_completion_install(
        statuses=(
            _row("zsh", status="not installed", path=None, zwc="n/a", stamp=None),
            _row("bash", status="not installed", path=None, zwc="n/a", stamp=None),
        )
    )
    assert check.status == "SKIP"
    assert "no sase completion install is stamped" in check.summary


def test_install_check_ok_when_stamp_version_and_zwc_match() -> None:
    check = _check_completion_install(statuses=(_row("zsh", status="installed"),))
    assert check.status == "OK"
    assert "1 stamped" in check.summary


def test_install_check_warns_for_missing_script() -> None:
    check = _check_completion_install(statuses=(_row("zsh", status="missing"),))
    assert check.status == "WARN"
    assert "missing" in check.summary
    assert any("install --force" in step for step in check.next_steps)


def test_install_check_warns_for_stale_version() -> None:
    check = _check_completion_install(
        statuses=(_row("zsh", status="stale", stamp="0.15.0"),)
    )
    assert check.status == "WARN"
    assert "stale" in check.summary


def test_install_check_warns_for_stale_zwc() -> None:
    check = _check_completion_install(
        statuses=(_row("zsh", status="zwc stale", zwc="missing"),)
    )
    assert check.status == "WARN"
    assert "zwc" in check.summary


def test_registration_skips_without_zsh_stamp() -> None:
    check = _check_completion_registration(stamps=())
    assert check.status == "SKIP"


def test_registration_warns_when_comps_unset() -> None:
    stamp = InstallStamp(
        shell="zsh",
        version="0.16.0",
        digest="x",
        target="/home/u/.zfunc/_sase",
        timestamp="2026-08-17T12:00:00Z",
    )
    check = _check_completion_registration(stamps=(stamp,), probe=lambda: "UNSET")
    assert check.status == "WARN"
    assert "UNSET" in check.summary
    assert any("BEFORE compinit" in detail for detail in check.details)


def test_registration_ok_when_comps_resolve() -> None:
    stamp = InstallStamp(
        shell="zsh",
        version="0.16.0",
        digest="x",
        target="/home/u/.zfunc/_sase",
        timestamp="2026-08-17T12:00:00Z",
    )
    check = _check_completion_registration(stamps=(stamp,), probe=lambda: "_sase")
    assert check.status == "OK"
    assert check.data["comps"] == "_sase"


def test_registration_skips_when_probe_unavailable() -> None:
    stamp = InstallStamp(
        shell="zsh",
        version="0.16.0",
        digest="x",
        target=str(Path("/tmp/_sase")),
        timestamp="2026-08-17T12:00:00Z",
    )
    check = _check_completion_registration(stamps=(stamp,), probe=lambda: None)
    assert check.status == "SKIP"

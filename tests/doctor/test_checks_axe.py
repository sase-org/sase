"""Tests for the ``axe.chops`` doctor check."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.axe.chop_doctor import build_chop_doctor_report
from sase.axe.chop_inventory import collect_chop_inventory
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.desired_state import AxeDesiredState
from sase.axe.systemd_scope import unsafe_axe_systemd_scope
from sase.doctor.checks_axe import (
    _check_axe_chops,
    _check_axe_health,
    _check_axe_systemd_scope,
)
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
                description="Run AXE doctor hook checks",
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


def test_axe_health_warns_when_desired_running_but_down(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_axe.read_desired_state",
        lambda: AxeDesiredState(
            state="running",
            source="restart",
            timestamp="2026-07-19T12:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_axe.probe_orchestrator",
        lambda **_kwargs: SimpleNamespace(running_pid=None),
    )

    check = _check_axe_health()

    assert check.status == "WARN"
    assert "orchestrator is down" in check.summary
    assert check.next_steps == ("Run `sase axe ensure`.",)


def test_axe_health_accepts_explicit_stop(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_axe.read_desired_state",
        lambda: AxeDesiredState(
            state="stopped",
            source="axe stop",
            timestamp="2026-07-19T12:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_axe.probe_orchestrator",
        lambda **_kwargs: SimpleNamespace(running_pid=None),
    )

    check = _check_axe_health()

    assert check.status == "OK"
    assert check.summary == "axe is explicitly stopped"


@pytest.mark.parametrize(
    ("cgroup", "has_systemd_run", "expected_scope"),
    [
        (
            "0::/user.slice/user-1000.slice/user@1000.service/"
            "app.slice/tmux-spawn-example.scope\n",
            True,
            "tmux-spawn-example.scope",
        ),
        (
            "0::/user.slice/user-1000.slice/user@1000.service/"
            "app.slice/sase-axe-123.scope\n",
            True,
            None,
        ),
        ("0::/user.slice/app.slice/sase-axe.scope\n", True, None),
        (
            "0::/user.slice/user-1000.slice/user@1000.service/"
            "app.slice/tmux-spawn-example.scope\n",
            False,
            None,
        ),
        ("5:cpu:/legacy/session.scope\n", True, None),
    ],
)
def test_unsafe_axe_systemd_scope_matrix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cgroup: str,
    has_systemd_run: bool,
    expected_scope: str | None,
) -> None:
    proc_root = tmp_path / "proc"
    process_dir = proc_root / "123"
    process_dir.mkdir(parents=True)
    (process_dir / "cgroup").write_text(cgroup)
    monkeypatch.setattr("sase.axe.systemd_scope.sys.platform", "linux")
    monkeypatch.setattr(
        "sase.axe.systemd_scope.shutil.which",
        lambda _name: "/usr/bin/systemd-run" if has_systemd_run else None,
    )

    assert unsafe_axe_systemd_scope(123, proc_root=proc_root) == expected_scope


def test_axe_systemd_scope_warns_for_session_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_axe.probe_orchestrator",
        lambda **_kwargs: SimpleNamespace(running_pid=123),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_axe.unsafe_axe_systemd_scope",
        lambda _pid: "tmux-spawn-example.scope",
    )

    check = _check_axe_systemd_scope()

    assert check.status == "WARN"
    assert "will be killed" in check.details[0]
    assert check.next_steps == ("Run `sase axe restart`.",)


def test_axe_systemd_scope_passes_without_doomed_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_axe.probe_orchestrator",
        lambda **_kwargs: SimpleNamespace(running_pid=123),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_axe.unsafe_axe_systemd_scope",
        lambda _pid: None,
    )

    check = _check_axe_systemd_scope()

    assert check.status == "OK"

"""Linux systemd service-platform tests: render, linger, legacy, idempotency."""

from __future__ import annotations

import getpass
from pathlib import Path

import pytest

from sase.service.platform import (
    apply_service_init,
    service_init_plan,
)
from tests.service.service_platform_helpers import (
    _LinuxManager,
    _exe,
    _linux_home,
)


def test_linux_unit_render_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _linux_home(tmp_path, monkeypatch)
    exe = _exe(tmp_path)
    plan = service_init_plan(
        runner=_LinuxManager(),
        environ={"PATH": "/bin", "OPENAI_API_KEY": "super-secret-token"},
        executable_resolver=lambda: str(exe),
    )
    content = plan.definition.content
    assert "Type=exec" in content
    assert "Restart=on-failure" in content
    assert "RestartSec=5" in content
    assert "KillMode=mixed" in content
    assert "WantedBy=default.target" in content
    assert "ExecStart=" in content
    assert "service run" in content
    assert f"ExecStart={exe} service run" in content or "service run" in content
    assert "network-online.target" not in content
    assert "super-secret-token" not in content
    assert "OPENAI_API_KEY" not in content
    user = getpass.getuser()
    assert f"loginctl enable-linger {user}" in "\n".join(plan.warnings)


def test_linux_linger_warning_never_elevates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _linux_home(tmp_path, monkeypatch)
    runner = _LinuxManager(linger="no")
    apply_service_init(
        runner=runner,
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    assert any(
        f"loginctl enable-linger {getpass.getuser()}" in warning
        for warning in service_init_plan(
            runner=_LinuxManager(linger="no"),
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(_exe(tmp_path)),
        ).warnings
    )
    assert all(call[0] != "loginctl" or call[1] == "show-user" for call in runner.calls)


def test_linux_legacy_units_detected_and_retired_before_enable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _linux_home(tmp_path, monkeypatch)
    runner = _LinuxManager(
        enabled=(
            "sase-gateway.service",
            "sase-axe-ensure.service",
            "sase-axe-ensure.timer",
        ),
        active=("sase-gateway.service",),
    )
    plan = service_init_plan(
        runner=runner,
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    assert plan.inspection is not None
    assert plan.inspection.legacy_owners == (
        "sase-gateway.service",
        "sase-axe-ensure.service",
        "sase-axe-ensure.timer",
    )
    result = apply_service_init(
        runner=runner,
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    assert result.ok is True
    disable_now = [
        call
        for call in runner.calls
        if call[:3] == ("systemctl", "--user", "disable") and "--now" in call
    ]
    retired = {call[-1] for call in disable_now}
    assert retired >= {
        "sase-gateway.service",
        "sase-axe-ensure.service",
        "sase-axe-ensure.timer",
    }
    enable_idx = runner.calls.index(("systemctl", "--user", "enable", "sase.service"))
    start_idx = runner.calls.index(("systemctl", "--user", "start", "sase.service"))
    last_retire = max(runner.calls.index(call) for call in disable_now)
    assert last_retire < enable_idx < start_idx


def test_linux_second_apply_skips_enable_and_start_when_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _linux_home(tmp_path, monkeypatch)
    runner = _LinuxManager()

    def resolve() -> str:
        return str(_exe(tmp_path))

    first = apply_service_init(
        runner=runner,
        environ={"PATH": "/bin"},
        executable_resolver=resolve,
    )
    assert first.ok is True
    enable_calls = runner.calls.count(("systemctl", "--user", "enable", "sase.service"))
    start_calls = runner.calls.count(("systemctl", "--user", "start", "sase.service"))
    second = apply_service_init(
        runner=runner,
        environ={"PATH": "/bin"},
        executable_resolver=resolve,
    )
    assert second.ok is True
    assert (
        runner.calls.count(("systemctl", "--user", "enable", "sase.service"))
        == enable_calls
    )
    assert (
        runner.calls.count(("systemctl", "--user", "start", "sase.service"))
        == start_calls
    )

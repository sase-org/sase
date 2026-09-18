"""Tests for native service-host platform planning and apply."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.feature_flags import override_flags
from sase.service.platform import (
    CommandResult,
    apply_service_init,
    build_native_definition,
    control_installed_service,
    service_init_plan,
)


def _exe(tmp_path: Path) -> Path:
    path = tmp_path / "bin" / "sase"
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if command[:3] == ("systemctl", "--user", "is-enabled"):
            return CommandResult(1, "disabled\n")
        if command[:3] == ("systemctl", "--user", "is-active"):
            return CommandResult(3, "inactive\n")
        if command[0] == "loginctl":
            return CommandResult(0, "no\n")
        return CommandResult(0, "")


def test_linux_plan_detects_content_env_linger_and_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr("sase.service.platform.readiness_warnings", lambda _env: ())
    runner = _Runner()

    with override_flags(service_host=True):
        plan = service_init_plan(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(_exe(tmp_path)),
        )

    assert plan.status == "needs_attention"
    assert any("write" in action and ".service" in action for action in plan.actions)
    assert any("write" in action and action.endswith("/env") for action in plan.actions)
    assert any("enable sase.service" == action for action in plan.actions)
    assert any("start sase.service" == action for action in plan.actions)
    assert any("loginctl enable-linger" in warning for warning in plan.warnings)
    assert "ExecStart=" in plan.definition.content
    assert "service run" in plan.definition.content
    assert "Environment=SASE_SERVICE_UNIT=sase.service" in plan.definition.content


def test_non_default_home_requires_force_and_gets_deterministic_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "alt-home"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")

    definition, blockers, _stable = build_native_definition(
        force=False,
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    forced, forced_blockers, _stable = build_native_definition(
        force=True,
        executable_resolver=lambda: str(_exe(tmp_path)),
    )

    assert blockers
    assert definition.unit_name.startswith("sase-home-")
    assert definition.unit_name == forced.unit_name
    assert forced_blockers == ()


def test_apply_service_init_writes_files_and_orders_manager_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr("sase.service.platform.readiness_warnings", lambda _env: ())
    runner = _Runner()

    with override_flags(service_host=True):
        result = apply_service_init(
            runner=runner,
            environ={"PATH": "/bin", "SASE_FEATURE_FLAGS": '{"service_host": true}'},
            executable_resolver=lambda: str(_exe(tmp_path)),
        )

    assert result.ok is True
    assert (tmp_path / ".sase" / "service" / "env").exists()
    assert (tmp_path / ".config" / "systemd" / "user" / "sase.service").exists()
    assert ("systemctl", "--user", "daemon-reload") in runner.calls
    assert ("systemctl", "--user", "enable", "sase.service") in runner.calls
    assert ("systemctl", "--user", "start", "sase.service") in runner.calls
    assert runner.calls.index(
        ("systemctl", "--user", "daemon-reload")
    ) < runner.calls.index(("systemctl", "--user", "enable", "sase.service"))


def test_control_installed_service_uses_native_manager_without_detached_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    unit_dir = tmp_path / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "sase.service").write_text("[Service]\n", encoding="utf-8")

    def failing_runner(argv: Sequence[str]) -> CommandResult:
        assert tuple(argv) == ("systemctl", "--user", "start", "sase.service")
        return CommandResult(1, stderr="boom")

    result = control_installed_service("start", runner=failing_runner)

    assert result is not None
    assert result.ok is False
    assert "boom" in result.message

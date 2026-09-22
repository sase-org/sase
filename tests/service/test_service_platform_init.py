"""Cross-platform service-init plan, apply, identity, and uninstall tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.service.env import (
    _CapturedServiceEnvironment,
    write_service_environment,
)
from sase.service.paths import service_state_path
from sase.service.platform import (
    DECLINED_MARKER,
    CommandResult,
    apply_service_init,
    apply_service_uninstall,
    build_native_definition,
    control_installed_service,
    service_init_plan,
    service_uninstall_plan,
)
from sase.service.state import read_service_state, set_service_marker
from tests.service.service_platform_helpers import (
    _LinuxManager,
    _Runner,
    _exe,
    _linux_home,
)


def test_linux_plan_detects_content_env_linger_and_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr("sase.service.platform._readiness_warnings", lambda _env: ())
    runner = _Runner()

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
    monkeypatch.setattr("sase.service.platform._readiness_warnings", lambda _env: ())
    runner = _Runner()

    result = apply_service_init(
        runner=runner,
        environ={"PATH": "/bin"},
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


def test_init_plan_diff_redacts_env_secrets_on_both_sides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = _linux_home(tmp_path, monkeypatch)
    env_path = sase_home / "service" / "env"
    env_path.parent.mkdir(parents=True)
    write_service_environment(
        {
            "OPENAI_API_KEY": "old-secret-token",
            "REMOVED_TOKEN": "gone-secret-token",
            "PATH": "/old",
        },
        path=env_path,
    )
    monkeypatch.setattr(
        "sase.service.platform.capture_service_environment",
        lambda **_k: _CapturedServiceEnvironment(
            values={
                "FCM_TOKEN": "new-secret-token",
                "OPENAI_API_KEY": "super-secret-token",
                "PATH": "/bin",
            }
        ),
    )
    plan = service_init_plan(
        runner=_LinuxManager(),
        environ={"PATH": "/bin", "OPENAI_API_KEY": "super-secret-token"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    assert "super-secret-token" not in plan.diff
    assert "old-secret-token" not in plan.diff
    assert "gone-secret-token" not in plan.diff
    assert "new-secret-token" not in plan.diff
    assert "[captured]" in plan.diff
    assert "-REMOVED_TOKEN=" in plan.diff
    assert "+FCM_TOKEN=" in plan.diff
    assert "Type=exec" in plan.diff or "sase.service" in plan.diff


def test_uninstall_preserves_state_and_force_removes_suffixed_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    sase_home = tmp_path / "alt-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr("sase.service.platform._readiness_warnings", lambda _env: ())
    runner = _LinuxManager()
    blocked = apply_service_init(
        runner=runner,
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    assert blocked.ok is False
    installed = apply_service_init(
        force=True,
        runner=runner,
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    assert installed.ok is True
    assert installed.plan is not None
    unit_path = installed.plan.definition.definition_path
    assert unit_path.name.startswith("sase-home-")
    assert unit_path.exists()
    set_service_marker(
        "history-probe",
        "pytest",
        detail="keep-me",
        sase_home=sase_home,
    )
    refused = apply_service_uninstall(runner=runner)
    assert refused.ok is False
    removed = apply_service_uninstall(force=True, runner=runner)
    assert removed.ok is True
    assert not unit_path.exists()
    snapshot = read_service_state(sase_home=sase_home)
    assert "history-probe" in snapshot.state.markers
    assert DECLINED_MARKER in snapshot.state.markers
    assert service_state_path(sase_home).exists()
    plan = service_uninstall_plan(force=True, runner=runner)
    assert plan.definition.unit_name == installed.plan.definition.unit_name


def test_env_file_mode_is_0600_after_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = _linux_home(tmp_path, monkeypatch)
    apply_service_init(
        runner=_LinuxManager(),
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    env_path = sase_home / "service" / "env"
    assert (env_path.stat().st_mode & 0o777) == 0o600

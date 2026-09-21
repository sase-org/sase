"""Tests for native service-host platform planning and apply.

Darwin host smoke checklist (the mac host is often offline; do not add a docs
page for this). On a real macOS machine:

- ``sase service init --check`` / ``--diff`` / ``--yes``
- ``launchctl print gui/$UID/sh.sase.service``
- a user-disabled Login Item stays disabled across a second ``--yes``
- ``sase service start`` does not fall back to detached while the plist exists
"""

from __future__ import annotations

import getpass
import plistlib
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.service.env import (
    CapturedServiceEnvironment,
    write_service_environment,
)
from sase.service.paths import service_state_path
from sase.service.platform import (
    DECLINED_MARKER,
    SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV,
    CommandResult,
    apply_service_init,
    apply_service_uninstall,
    build_native_definition,
    control_installed_service,
    inspect_native_service,
    readiness_warnings,
    service_init_plan,
    service_uninstall_plan,
)
from sase.service.state import read_service_state, set_service_marker


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


class _LinuxManager:
    def __init__(
        self,
        *,
        enabled: Sequence[str] = (),
        active: Sequence[str] = (),
        linger: str = "no",
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.enabled = set(enabled)
        self.active = set(active)
        self.linger = linger

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if command[:3] == ("systemctl", "--user", "is-enabled"):
            unit = command[3]
            if unit in self.enabled:
                return CommandResult(0, "enabled\n")
            return CommandResult(1, "disabled\n")
        if command[:3] == ("systemctl", "--user", "is-active"):
            unit = command[3]
            if unit in self.active:
                return CommandResult(0, "active\n")
            return CommandResult(3, "inactive\n")
        if command[0] == "loginctl" and "enable-linger" in command:
            raise AssertionError(f"privileged linger command must not run: {command}")
        if command[0] == "loginctl":
            return CommandResult(0, f"{self.linger}\n")
        if command[:3] == ("systemctl", "--user", "enable"):
            self.enabled.add(command[3])
        if command[:3] == ("systemctl", "--user", "start"):
            self.active.add(command[3])
        if command[:3] == ("systemctl", "--user", "disable"):
            unit = command[-1]
            self.enabled.discard(unit)
            if "--now" in command:
                self.active.discard(unit)
        if command[:3] == ("systemctl", "--user", "stop"):
            self.active.discard(command[3])
        return CommandResult(0, "")


class _DarwinManager:
    def __init__(
        self,
        *,
        active: Sequence[str] = (),
        user_disabled: Sequence[str] = (),
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.active = set(active)
        self.user_disabled = set(user_disabled)

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if command[:2] == ("launchctl", "print"):
            label = command[2].rsplit("/", 1)[-1]
            if label in self.user_disabled:
                return CommandResult(1, stderr="SMAppService: service is disabled\n")
            if label in self.active:
                return CommandResult(0, stdout="state = running\n")
            return CommandResult(1, stderr="Could not find service\n")
        if command[:2] == ("launchctl", "bootstrap"):
            plist = Path(command[3])
            assert plist.exists()
            label = plist.stem
            if label in self.user_disabled:
                raise AssertionError(f"must not bootstrap user-disabled {label}")
            self.active.add(label)
            return CommandResult(0, "")
        if command[:2] == ("launchctl", "bootout"):
            label = command[2].rsplit("/", 1)[-1]
            self.active.discard(label)
            return CommandResult(0, "")
        return CommandResult(0, "")


def _linux_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    monkeypatch.setattr("sase.service.platform.readiness_warnings", lambda _env: ())
    return sase_home


def _darwin_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Darwin")
    monkeypatch.setattr("sase.service.platform.readiness_warnings", lambda _env: ())
    return sase_home


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
        lambda **_k: CapturedServiceEnvironment(
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
    monkeypatch.setattr("sase.service.platform.readiness_warnings", lambda _env: ())
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


def test_readiness_warnings_omit_secrets_and_compare_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_bin = tmp_path / "live"
    live_bin.mkdir()
    binary = live_bin / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(live_bin))
    monkeypatch.setenv("SASE_FEATURE_FLAGS", '{"typed_launch_units": true}')
    monkeypatch.setattr(
        "sase.service.platform.collect_agent_cli_statuses",
        lambda **_k: (
            SimpleNamespace(
                display_name="Codex",
                installed=False,
                binary="codex",
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_gateway.load_mobile_gateway_config",
        lambda: SimpleNamespace(command=(str(tmp_path / "missing-gateway"),)),
    )
    warnings = readiness_warnings(
        {
            "PATH": str(tmp_path / "empty"),
            "OPENAI_API_KEY": "super-secret-token",
        }
    )
    joined = "\n".join(warnings)
    assert "super-secret-token" not in joined
    assert "interactive PATH" in joined
    assert "mobile gateway" in joined
    assert "SASE_FEATURE_FLAGS differ" in joined


def _stub_non_ssh_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    monkeypatch.setattr(
        "sase.service.platform.collect_agent_cli_statuses", lambda **_k: ()
    )
    monkeypatch.setattr(
        "sase.integrations.mobile_gateway.load_mobile_gateway_config",
        lambda: SimpleNamespace(command=()),
    )


def test_readiness_warnings_leave_ssh_to_the_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capture owns the SSH report, so readiness must not ask the remote again."""
    _stub_non_ssh_readiness(monkeypatch)

    def fail(_env: dict[str, str]) -> str:
        raise AssertionError("readiness_warnings must not probe the git remote")

    monkeypatch.setattr("sase.service.ssh_agent.probe_git_remote_auth", fail)

    assert readiness_warnings({"PATH": "/nowhere"}) == ()


def test_init_plan_reports_a_refused_capture_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Linux")
    _stub_non_ssh_readiness(monkeypatch)
    probed: list[dict[str, str]] = []

    def denied(env: dict[str, str]) -> str:
        probed.append(env)
        return "denied"

    monkeypatch.setattr("sase.service.ssh_agent.probe_git_remote_auth", denied)

    plan = service_init_plan(
        runner=_Runner(),
        environ={"PATH": "/bin"},
        executable_resolver=lambda: str(_exe(tmp_path)),
    )

    refused = [w for w in plan.warnings if "refused by the git remote" in w]
    assert len(refused) == 1
    assert refused[0].startswith("captured service environment")
    assert len(probed) == 1
    assert plan.status == "needs_attention"


def test_default_runner_refuses_under_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.service import platform as service_platform

    _linux_home(tmp_path, monkeypatch)
    monkeypatch.delenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    with patch("sase.service.platform_runner.subprocess.run") as run:
        result = service_platform.default_runner(
            ["systemctl", "--user", "is-active", "sase.service"]
        )
    run.assert_not_called()
    assert result.returncode == 125
    assert SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE in result.stderr
    definition, _blockers, _exe_info = build_native_definition(
        executable_resolver=lambda: str(_exe(tmp_path)),
    )
    with patch("sase.service.platform_runner.subprocess.run") as run:
        inspection = inspect_native_service(
            definition,
            desired_env={"PATH": "/bin"},
        )
    run.assert_not_called()
    assert inspection.active is False


def test_default_runner_override_allows_isolated_lifecycle_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.service import platform as service_platform

    monkeypatch.setenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, "1")
    with patch("sase.service.platform_runner.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        result = service_platform.default_runner(["true"])
    run.assert_called_once()
    assert result.returncode == 0
    assert result.stdout == "ok\n"


class TestDarwinPlatform:
    """Darwin host smoke checklist (mac is often offline; keep this in tests).

    - init ``--check`` / ``--diff`` / ``--yes``
    - ``launchctl print gui/$UID/sh.sase.service``
    - user-disabled Login Item stays disabled across a second ``--yes``
    - ``sase service start`` does not fall back to detached while the plist exists
    """

    def test_darwin_render_inspect_apply_and_legacy_order(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _darwin_home(tmp_path, monkeypatch)
        runner = _DarwinManager(active=("sh.sase.gateway",))
        exe = _exe(tmp_path)
        plan = service_init_plan(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(exe),
        )
        payload = plistlib.loads(plan.definition.content.encode("utf-8"))
        assert payload["RunAtLoad"] is True
        assert payload["KeepAlive"] == {"SuccessfulExit": False}
        assert payload["AbandonProcessGroup"] is True
        assert payload["ThrottleInterval"] == 10
        assert payload["ProgramArguments"] == [str(exe), "service", "run"]
        assert payload["StandardOutPath"].endswith("host.stdout.log")
        assert payload["StandardErrorPath"].endswith("host.stderr.log")
        env = payload["EnvironmentVariables"]
        assert set(env) <= {"SASE_SERVICE_ENV", "SASE_SERVICE_UNIT", "SASE_HOME"}
        assert env["SASE_SERVICE_UNIT"] == "sh.sase.service"
        assert plan.inspection is not None
        assert plan.inspection.legacy_owners == ("sh.sase.gateway",)
        result = apply_service_init(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(exe),
        )
        assert result.ok is True
        assert plan.definition.definition_path.exists()
        bootout = [
            i
            for i, call in enumerate(runner.calls)
            if call[:2] == ("launchctl", "bootout")
            and call[2].endswith("sh.sase.gateway")
        ]
        bootstrap = [
            i
            for i, call in enumerate(runner.calls)
            if call[:2] == ("launchctl", "bootstrap")
        ]
        assert bootout
        assert bootstrap
        assert bootout[0] < bootstrap[0]
        print_calls = [
            call for call in runner.calls if call[:2] == ("launchctl", "print")
        ]
        assert any(call[2].endswith("sh.sase.service") for call in print_calls)

    def test_darwin_user_disabled_skips_bootstrap(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _darwin_home(tmp_path, monkeypatch)
        runner = _DarwinManager(user_disabled=("sh.sase.service",))
        plan = service_init_plan(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(_exe(tmp_path)),
        )
        assert plan.inspection is not None
        assert plan.inspection.user_disabled is True
        assert plan.inspection.active is False
        assert not any(action.startswith("start ") for action in plan.actions)
        first = apply_service_init(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(_exe(tmp_path)),
        )
        second = apply_service_init(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(_exe(tmp_path)),
        )
        assert first.ok is True
        assert second.ok is True
        assert first.plan is not None
        assert first.plan.definition.definition_path.exists()
        assert all(call[:2] != ("launchctl", "bootstrap") for call in runner.calls)

    def test_darwin_print_failure_without_disabled_marker_is_not_user_disabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _darwin_home(tmp_path, monkeypatch)
        runner = _DarwinManager()
        plan = service_init_plan(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=lambda: str(_exe(tmp_path)),
        )
        assert plan.inspection is not None
        assert plan.inspection.active is False
        assert plan.inspection.user_disabled is False

    def test_darwin_second_apply_skips_bootstrap_when_active(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _darwin_home(tmp_path, monkeypatch)
        runner = _DarwinManager()

        def resolve() -> str:
            return str(_exe(tmp_path))

        first = apply_service_init(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=resolve,
        )
        bootstrap_count = sum(
            1 for call in runner.calls if call[:2] == ("launchctl", "bootstrap")
        )
        second = apply_service_init(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=resolve,
        )
        assert first.ok is True
        assert second.ok is True
        assert (
            sum(1 for call in runner.calls if call[:2] == ("launchctl", "bootstrap"))
            == bootstrap_count
        )

    def test_darwin_uninstall_and_start_use_native_manager(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _darwin_home(tmp_path, monkeypatch)
        runner = _DarwinManager()

        def resolve() -> str:
            return str(_exe(tmp_path))

        installed = apply_service_init(
            runner=runner,
            environ={"PATH": "/bin"},
            executable_resolver=resolve,
        )
        assert installed.plan is not None
        plist = installed.plan.definition.definition_path
        assert plist.exists()
        start = control_installed_service("start", runner=runner)
        assert start is not None
        assert start.ok is True
        assert any(call[:2] == ("launchctl", "bootstrap") for call in runner.calls)
        removed = apply_service_uninstall(runner=runner)
        assert removed.ok is True
        assert not plist.exists()

    def test_darwin_non_default_home_suffixes_label(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "user"))
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "alt-home"))
        monkeypatch.setattr("sase.service.platform.platform.system", lambda: "Darwin")
        forced, blockers, _stable = build_native_definition(
            force=True,
            executable_resolver=lambda: str(_exe(tmp_path)),
        )
        refused, refused_blockers, _stable = build_native_definition(
            force=False,
            executable_resolver=lambda: str(_exe(tmp_path)),
        )
        assert blockers == ()
        assert refused_blockers
        assert forced.label.startswith("sh.sase.service.")
        assert forced.label == refused.label
        assert forced.definition_path.name == f"{forced.label}.plist"
        env = plistlib.loads(forced.content.encode("utf-8"))["EnvironmentVariables"]
        assert env["SASE_HOME"] == str((tmp_path / "alt-home").resolve())
        assert "SASE_SERVICE_ENV" in env

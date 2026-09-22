"""Darwin launchd service-platform tests.

Darwin host smoke checklist (the mac host is often offline; do not add a docs
page for this). On a real macOS machine:

- ``sase service init --check`` / ``--diff`` / ``--yes``
- ``launchctl print gui/$UID/sh.sase.service``
- a user-disabled Login Item stays disabled across a second ``--yes``
- ``sase service start`` does not fall back to detached while the plist exists
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from sase.service.platform import (
    apply_service_init,
    apply_service_uninstall,
    build_native_definition,
    control_installed_service,
    service_init_plan,
)
from tests.service.service_platform_helpers import (
    _DarwinManager,
    _darwin_home,
    _exe,
)


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

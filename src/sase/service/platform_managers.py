"""Native service-manager verbs (systemd user units and launchd)."""

from __future__ import annotations

import getpass
import os
import shutil
from collections.abc import Mapping

from sase.service.platform_models import (
    LEGACY_LAUNCHD_LABELS,
    LEGACY_SYSTEMD_UNITS,
    CommandRunner,
    NativeServiceDefinition,
)
from sase.service.platform_runner import require_ok

_DARWIN_USER_DISABLED_MARKERS = (
    "disabled = 1",
    "disabled = true",
    "state = disabled",
    "is disabled",
    "disabled by the user",
    "gui-disabled",
)


def linux_unit_enabled(unit: str, runner: CommandRunner) -> bool:
    result = runner(["systemctl", "--user", "is-enabled", unit])
    return result.returncode == 0 and result.stdout.strip() in {"enabled", "linked"}


def linux_unit_active(unit: str, runner: CommandRunner) -> bool:
    result = runner(["systemctl", "--user", "is-active", unit])
    return result.returncode == 0 and result.stdout.strip() == "active"


def linux_linger_enabled(runner: CommandRunner) -> bool | None:
    result = runner(
        ["loginctl", "show-user", getpass.getuser(), "-p", "Linger", "--value"]
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip().casefold()
    if value in {"yes", "true", "1"}:
        return True
    if value in {"no", "false", "0"}:
        return False
    return None


def linux_legacy_owners(runner: CommandRunner) -> tuple[str, ...]:
    found: list[str] = []
    for unit in LEGACY_SYSTEMD_UNITS:
        if linux_unit_enabled(unit, runner) or linux_unit_active(unit, runner):
            found.append(unit)
    return tuple(found)


def linux_reload(runner: CommandRunner) -> None:
    require_ok(
        runner(["systemctl", "--user", "daemon-reload"]), "systemctl daemon-reload"
    )


def linux_enable_start(
    definition: NativeServiceDefinition,
    runner: CommandRunner,
    *,
    enable: bool = True,
    start: bool = True,
) -> None:
    if enable:
        require_ok(
            runner(["systemctl", "--user", "enable", definition.unit_name]),
            f"systemctl enable {definition.unit_name}",
        )
    if start:
        require_ok(
            runner(["systemctl", "--user", "start", definition.unit_name]),
            f"systemctl start {definition.unit_name}",
        )


def linux_disable_stop(
    definition: NativeServiceDefinition, runner: CommandRunner
) -> None:
    runner(["systemctl", "--user", "stop", definition.unit_name])
    runner(["systemctl", "--user", "disable", definition.unit_name])


def retire_linux_legacy(runner: CommandRunner) -> None:
    for unit in LEGACY_SYSTEMD_UNITS:
        runner(["systemctl", "--user", "disable", "--now", unit])


def darwin_unit_active(label: str, runner: CommandRunner) -> tuple[bool, bool]:
    result = runner(["launchctl", "print", _darwin_service_target(label)])
    if result.returncode == 0:
        return True, False
    output = f"{result.stdout}\n{result.stderr}"
    return False, _darwin_output_user_disabled(output)


def _darwin_output_user_disabled(output: str) -> bool:
    lowered = output.casefold()
    return any(marker in lowered for marker in _DARWIN_USER_DISABLED_MARKERS)


def darwin_legacy_owners(runner: CommandRunner) -> tuple[str, ...]:
    return tuple(
        label for label in LEGACY_LAUNCHD_LABELS if darwin_unit_active(label, runner)[0]
    )


def darwin_bootstrap(
    definition: NativeServiceDefinition, runner: CommandRunner
) -> None:
    result = runner(
        [
            "launchctl",
            "bootstrap",
            _darwin_gui_domain(),
            str(definition.definition_path),
        ]
    )
    if (
        result.returncode != 0
        and "already bootstrapped" not in result.stderr.casefold()
    ):
        require_ok(result, f"launchctl bootstrap {definition.label}")


def darwin_bootout(definition: NativeServiceDefinition, runner: CommandRunner) -> None:
    runner(["launchctl", "bootout", _darwin_service_target(definition.label)])


def retire_darwin_legacy(runner: CommandRunner) -> None:
    for label in LEGACY_LAUNCHD_LABELS:
        runner(["launchctl", "bootout", _darwin_service_target(label)])


def _darwin_gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _darwin_service_target(label: str) -> str:
    return f"{_darwin_gui_domain()}/{label}"


def resolve_command(command: str, env: Mapping[str, str]) -> str | None:
    expanded = os.path.expanduser(command)
    resolved = shutil.which(expanded, path=env.get("PATH"))
    if resolved:
        return resolved
    if os.sep in expanded and os.access(expanded, os.X_OK):
        return expanded
    return None

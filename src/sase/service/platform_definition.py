"""Native service definition building, inspection, and lifecycle routing."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from sase.core.paths import sase_home as _sase_home
from sase.service.executable import (
    StableExecutable,
    resolve_stable_sase_executable,
)
from sase.service.paths import (
    service_env_path,
    service_host_stderr_path,
    service_host_stdout_path,
)
from sase.service.platform_files import (
    content_current,
    environment_current,
)
from sase.service.platform_managers import (
    darwin_bootout,
    darwin_bootstrap,
    darwin_legacy_owners,
    darwin_unit_active,
    linux_linger_enabled,
    linux_legacy_owners,
    linux_unit_active,
    linux_unit_enabled,
)
from sase.service.platform_models import (
    CommandRunner,
    NativeInspection,
    NativeServiceDefinition,
    ServicePlatformApplyResult,
)
from sase.service.platform_runner import default_runner, require_ok
from sase.service.platform_units import (
    home_suffix,
    platform_kind,
    render_launchd_plist,
    render_systemd_unit,
)


def build_native_definition(
    *,
    force: bool = False,
    executable_resolver: Callable[[], str | None] | None = None,
) -> tuple[NativeServiceDefinition, tuple[str, ...], StableExecutable]:
    """Build the desired platform-unit definition and any planning blockers."""
    kind = platform_kind()
    home = _sase_home().resolve(strict=False)
    default_home = (Path.home() / ".sase").expanduser().resolve(strict=False)
    alternate_home = home != default_home
    blockers: list[str] = []
    if alternate_home and not force:
        blockers.append(
            f"non-default SASE_HOME {home} requires --force so it cannot overwrite the default service"
        )
    suffix = home_suffix(home) if alternate_home else ""
    unit_name = "sase.service" if not suffix else f"sase-{suffix}.service"
    label = "sh.sase.service" if not suffix else f"sh.sase.service.{suffix}"
    executable = resolve_stable_sase_executable(resolver=executable_resolver)
    env_path = service_env_path(home)
    stdout_path = service_host_stdout_path(home)
    stderr_path = service_host_stderr_path(home)
    if kind == "linux":
        definition_path = Path.home() / ".config" / "systemd" / "user" / unit_name
        content = render_systemd_unit(
            executable.path,
            unit_identity=unit_name,
            env_path=env_path,
            alternate_home=home if alternate_home else None,
        )
    elif kind == "darwin":
        definition_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        content = render_launchd_plist(
            executable.path,
            label=label,
            env_path=env_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            alternate_home=home if alternate_home else None,
        )
    else:
        definition_path = home / "service" / "unsupported.service"
        content = ""
    return (
        NativeServiceDefinition(
            platform=kind,
            sase_home=home,
            default_home=default_home,
            unit_name=unit_name,
            label=label,
            definition_path=definition_path,
            env_path=env_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            executable=executable.path,
            content=content,
            alternate_home=alternate_home,
        ),
        tuple(blockers),
        executable,
    )


def inspect_native_service(
    definition: NativeServiceDefinition,
    *,
    desired_env: Mapping[str, str],
    runner: CommandRunner | None = None,
) -> NativeInspection:
    """Inspect desired file content and native manager state without writes."""
    runner = default_runner if runner is None else runner
    definition_exists, definition_current = content_current(
        definition.definition_path,
        definition.content,
    )
    environment_exists, environment_is_current = environment_current(
        definition.env_path,
        desired_env,
    )
    enabled: bool | None = None
    active: bool | None = None
    user_disabled = False
    linger: bool | None = None
    legacy: tuple[str, ...] = ()
    if definition.platform == "linux":
        enabled = linux_unit_enabled(definition.unit_name, runner)
        active = linux_unit_active(definition.unit_name, runner)
        linger = linux_linger_enabled(runner)
        legacy = linux_legacy_owners(runner)
    elif definition.platform == "darwin":
        active, user_disabled = darwin_unit_active(definition.label, runner)
        enabled = active
        legacy = darwin_legacy_owners(runner)
    return NativeInspection(
        definition_exists=definition_exists,
        definition_current=definition_current,
        environment_exists=environment_exists,
        environment_current=environment_is_current,
        enabled=enabled,
        active=active,
        user_disabled=user_disabled,
        linger=linger,
        legacy_owners=legacy,
    )


def installed_native_definition(
    *,
    force: bool = True,
) -> NativeServiceDefinition | None:
    """Return the expected installed definition if its owned file exists."""
    definition, _blockers, _executable = build_native_definition(
        force=force,
        executable_resolver=lambda: None,
    )
    if definition.definition_path.exists():
        return definition
    return None


def control_installed_service(
    action: Literal["start", "stop", "restart"],
    *,
    runner: CommandRunner | None = None,
) -> ServicePlatformApplyResult | None:
    """Route lifecycle action through the installed native manager when present."""
    definition = installed_native_definition()
    if definition is None:
        return None
    runner = default_runner if runner is None else runner
    try:
        if definition.platform == "linux":
            command = {
                "start": "start",
                "stop": "stop",
                "restart": "restart",
            }[action]
            require_ok(
                runner(["systemctl", "--user", command, definition.unit_name]),
                f"systemctl --user {command} {definition.unit_name}",
            )
        elif definition.platform == "darwin":
            if action in {"stop", "restart"}:
                darwin_bootout(definition, runner)
            if action in {"start", "restart"}:
                darwin_bootstrap(definition, runner)
        else:
            return ServicePlatformApplyResult(
                ok=False,
                changed=False,
                message="unsupported platform",
            )
    except RuntimeError as exc:
        return ServicePlatformApplyResult(ok=False, changed=True, message=str(exc))
    return ServicePlatformApplyResult(
        ok=True,
        changed=True,
        message=f"{action}ed {definition.identity} through the native manager",
    )

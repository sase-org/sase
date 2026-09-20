"""Native platform-unit planning and lifecycle for the service host."""

from __future__ import annotations

import difflib
import getpass
import hashlib
import os
import platform
import plistlib
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sase.agent_clis.operations import collect_agent_cli_statuses
from sase.core.paths import sase_home as _sase_home
from sase.core.state_write_guard import pytest_context_detected
from sase.feature_flags import FeatureFlag, current_flags
from sase.service.effective_env import effective_ssh_agent_warnings
from sase.service.env import (
    ServiceEnvironmentError,
    capture_service_environment,
    environment_files_match,
    parse_service_environment_text,
    render_service_environment,
    write_service_environment,
)
from sase.service.executable import StableExecutable, resolve_stable_sase_executable
from sase.service.paths import (
    service_env_path,
    service_host_stderr_path,
    service_host_stdout_path,
)
from sase.service.state import clear_service_marker, set_service_marker

PlatformKind = Literal["linux", "darwin", "unsupported"]
ServicePlanStatus = Literal["current", "needs_attention", "blocked"]

DECLINED_MARKER = "platform_init.declined"
LEGACY_SYSTEMD_UNITS = (
    "sase-gateway.service",
    "sase-axe-ensure.service",
    "sase-axe-ensure.timer",
)
LEGACY_LAUNCHD_LABELS = ("sh.sase.gateway",)
SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV = "SASE_SERVICE_ALLOW_LIFECYCLE_IN_TESTS"
SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE = (
    "Native service-manager commands are disabled while running under pytest. Set "
    f"{SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV}=1 only for isolated lifecycle tests."
)
_DARWIN_USER_DISABLED_MARKERS = (
    "disabled = 1",
    "disabled = true",
    "state = disabled",
    "is disabled",
    "disabled by the user",
    "gui-disabled",
)


@dataclass(frozen=True)
class CommandResult:
    """Small command result protocol for injected platform managers."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str]], CommandResult]


@dataclass(frozen=True)
class NativeServiceDefinition:
    """Desired native-unit identity, paths, and rendered content."""

    platform: PlatformKind
    sase_home: Path
    default_home: Path
    unit_name: str
    label: str
    definition_path: Path
    env_path: Path
    stdout_path: Path
    stderr_path: Path
    executable: Path | None
    content: str
    alternate_home: bool = False

    @property
    def identity(self) -> str:
        return self.unit_name if self.platform == "linux" else self.label


@dataclass(frozen=True)
class NativeInspection:
    """Read-only native-unit state."""

    definition_exists: bool
    definition_current: bool
    environment_exists: bool
    environment_current: bool
    enabled: bool | None = None
    active: bool | None = None
    user_disabled: bool = False
    linger: bool | None = None
    legacy_owners: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServicePlatformPlan:
    """Complete read-only service-platform assessment."""

    definition: NativeServiceDefinition
    status: ServicePlanStatus
    actions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    diff: str = ""
    captured_env_redacted: Mapping[str, str] = field(default_factory=dict)
    inspection: NativeInspection | None = None

    @property
    def current(self) -> bool:
        return self.status == "current"


@dataclass(frozen=True)
class ServicePlatformApplyResult:
    """Result of installing or uninstalling the platform unit."""

    ok: bool
    changed: bool
    message: str
    plan: ServicePlatformPlan | None = None


def service_platform_supported() -> bool:
    return _platform_kind() in {"linux", "darwin"}


def service_init_plan(
    *,
    force: bool = False,
    runner: CommandRunner | None = None,
    environ: Mapping[str, str] | None = None,
    executable_resolver: Callable[[], str | None] | None = None,
) -> ServicePlatformPlan:
    """Return the read-only installation plan for the current machine."""
    definition, initial_blockers, executable = build_native_definition(
        force=force,
        executable_resolver=executable_resolver,
    )
    capture = capture_service_environment(
        environ=environ,
        force_sase_home=definition.sase_home if definition.alternate_home else None,
    )
    desired_env = capture.values
    blockers = list(initial_blockers)
    warnings: list[str] = list(capture.warnings)
    actions: list[str] = []

    if not current_flags().enabled(FeatureFlag.service_host):
        blockers.append("service_host beta flag is disabled")
    if not executable.available:
        blockers.extend(executable.diagnostics)
    if definition.platform == "unsupported":
        blockers.append(
            f"platform-unit installation is not supported on {platform.system() or 'this platform'}"
        )

    inspection = inspect_native_service(
        definition,
        desired_env=desired_env,
        runner=runner,
    )
    if not inspection.definition_current:
        actions.append(f"write {definition.definition_path}")
    if not inspection.environment_current:
        actions.append(f"write {definition.env_path}")
    if inspection.legacy_owners:
        actions.append("retire legacy owner(s): " + ", ".join(inspection.legacy_owners))
    if inspection.user_disabled:
        warnings.append(
            f"{definition.identity} appears disabled by the user in the native manager"
        )
    else:
        if inspection.enabled is False:
            actions.append(f"enable {definition.identity}")
        if inspection.active is False:
            actions.append(f"start {definition.identity}")
    if inspection.linger is False:
        user = getpass.getuser()
        warnings.append(
            f"user linger is disabled; run `loginctl enable-linger {user}` so the service can survive logout"
        )
    warnings.extend(readiness_warnings(desired_env))
    if inspection.definition_exists:
        # The capture above answers "what will init write"; this answers "what
        # would the installed host see", which a healthy caller shell cannot mask.
        warnings.extend(
            effective_ssh_agent_warnings(
                platform_kind=definition.platform,
                env_path=definition.env_path,
                desired_env=desired_env,
                runner=_default_runner if runner is None else runner,
            )
        )

    diff = _combined_diff(
        definition.definition_path,
        definition.content,
        definition.env_path,
        render_service_environment(desired_env),
    )
    status: ServicePlanStatus
    if blockers:
        status = "blocked"
    elif actions or warnings:
        status = "needs_attention"
    else:
        status = "current"
    return ServicePlatformPlan(
        definition=definition,
        status=status,
        actions=tuple(actions),
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        diff=diff,
        captured_env_redacted=capture.redacted_values,
        inspection=inspection,
    )


def apply_service_init(
    *,
    force: bool = False,
    runner: CommandRunner | None = None,
    environ: Mapping[str, str] | None = None,
    executable_resolver: Callable[[], str | None] | None = None,
) -> ServicePlatformApplyResult:
    """Install or update the native platform unit idempotently."""
    plan = service_init_plan(
        force=force,
        runner=runner,
        environ=environ,
        executable_resolver=executable_resolver,
    )
    if plan.blockers:
        return ServicePlatformApplyResult(
            ok=False,
            changed=False,
            message="service platform init is blocked",
            plan=plan,
        )
    runner = _default_runner if runner is None else runner
    definition = plan.definition
    inspection = plan.inspection
    user_disabled = bool(inspection is not None and inspection.user_disabled)
    already_enabled = bool(inspection is not None and inspection.enabled is True)
    already_active = bool(inspection is not None and inspection.active is True)
    write_service_environment(
        capture_service_environment(
            environ=environ,
            force_sase_home=definition.sase_home if definition.alternate_home else None,
        ).values,
        path=definition.env_path,
    )
    _write_definition(definition)
    try:
        if definition.platform == "linux":
            _linux_reload(runner)
            _retire_linux_legacy(runner)
            _linux_enable_start(
                definition,
                runner,
                enable=not already_enabled,
                start=not already_active,
            )
        elif definition.platform == "darwin":
            _retire_darwin_legacy(runner)
            if not user_disabled and not already_active:
                _darwin_bootstrap(definition, runner)
        else:
            return ServicePlatformApplyResult(
                ok=False,
                changed=True,
                message="unsupported platform",
                plan=plan,
            )
    except RuntimeError as exc:
        return ServicePlatformApplyResult(
            ok=False,
            changed=True,
            message=str(exc),
            plan=plan,
        )
    clear_service_marker(DECLINED_MARKER)
    return ServicePlatformApplyResult(
        ok=True,
        changed=bool(plan.actions),
        message=f"installed {definition.identity}",
        plan=plan,
    )


def service_uninstall_plan(
    *,
    force: bool = False,
    runner: CommandRunner | None = None,
) -> ServicePlatformPlan:
    """Return a read-only uninstall assessment."""
    definition, blockers, executable = build_native_definition(
        force=force,
        executable_resolver=lambda: None,
    )
    inspection = inspect_native_service(definition, desired_env={}, runner=runner)
    actions: list[str] = []
    if inspection.active:
        actions.append(f"stop {definition.identity}")
    if inspection.enabled:
        actions.append(f"disable {definition.identity}")
    if definition.definition_path.exists():
        actions.append(f"remove {definition.definition_path}")
    status: ServicePlanStatus = "blocked" if blockers else "needs_attention"
    if not blockers and not actions:
        status = "current"
    return ServicePlatformPlan(
        definition=definition,
        status=status,
        actions=tuple(actions),
        blockers=tuple(blockers),
        inspection=inspection,
        captured_env_redacted={},
    )


def apply_service_uninstall(
    *,
    force: bool = False,
    runner: CommandRunner | None = None,
) -> ServicePlatformApplyResult:
    """Unload/disable the native unit and remove only SASE-owned unit files."""
    plan = service_uninstall_plan(force=force, runner=runner)
    if plan.blockers:
        return ServicePlatformApplyResult(
            ok=False,
            changed=False,
            message="service platform uninstall is blocked",
            plan=plan,
        )
    runner = _default_runner if runner is None else runner
    definition = plan.definition
    try:
        if definition.platform == "linux":
            _linux_disable_stop(definition, runner)
            _unlink_owned_definition(definition)
            _linux_reload(runner)
        elif definition.platform == "darwin":
            _darwin_bootout(definition, runner)
            _unlink_owned_definition(definition)
        else:
            return ServicePlatformApplyResult(
                ok=False,
                changed=False,
                message="unsupported platform",
                plan=plan,
            )
    except RuntimeError as exc:
        return ServicePlatformApplyResult(
            ok=False,
            changed=True,
            message=str(exc),
            plan=plan,
        )
    set_service_marker(
        DECLINED_MARKER,
        "service-uninstall",
        detail=definition.identity,
    )
    return ServicePlatformApplyResult(
        ok=True,
        changed=bool(plan.actions),
        message=f"uninstalled {definition.identity}",
        plan=plan,
    )


def build_native_definition(
    *,
    force: bool = False,
    executable_resolver: Callable[[], str | None] | None = None,
) -> tuple[NativeServiceDefinition, tuple[str, ...], StableExecutable]:
    """Build the desired platform-unit definition and any planning blockers."""
    kind = _platform_kind()
    home = _sase_home().resolve(strict=False)
    default_home = (Path.home() / ".sase").expanduser().resolve(strict=False)
    alternate_home = home != default_home
    blockers: list[str] = []
    if alternate_home and not force:
        blockers.append(
            f"non-default SASE_HOME {home} requires --force so it cannot overwrite the default service"
        )
    suffix = _home_suffix(home) if alternate_home else ""
    unit_name = "sase.service" if not suffix else f"sase-{suffix}.service"
    label = "sh.sase.service" if not suffix else f"sh.sase.service.{suffix}"
    executable = resolve_stable_sase_executable(resolver=executable_resolver)
    env_path = service_env_path(home)
    stdout_path = service_host_stdout_path(home)
    stderr_path = service_host_stderr_path(home)
    if kind == "linux":
        definition_path = Path.home() / ".config" / "systemd" / "user" / unit_name
        content = _render_systemd_unit(
            executable.path,
            unit_identity=unit_name,
            env_path=env_path,
            alternate_home=home if alternate_home else None,
        )
    elif kind == "darwin":
        definition_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        content = _render_launchd_plist(
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
    runner = _default_runner if runner is None else runner
    definition_exists, definition_current = _content_current(
        definition.definition_path,
        definition.content,
    )
    environment_exists, environment_current = _environment_current(
        definition.env_path,
        desired_env,
    )
    enabled: bool | None = None
    active: bool | None = None
    user_disabled = False
    linger: bool | None = None
    legacy: tuple[str, ...] = ()
    if definition.platform == "linux":
        enabled = _linux_unit_enabled(definition.unit_name, runner)
        active = _linux_unit_active(definition.unit_name, runner)
        linger = _linux_linger_enabled(runner)
        legacy = _linux_legacy_owners(runner)
    elif definition.platform == "darwin":
        active, user_disabled = _darwin_unit_active(definition.label, runner)
        enabled = active
        legacy = _darwin_legacy_owners(runner)
    return NativeInspection(
        definition_exists=definition_exists,
        definition_current=definition_current,
        environment_exists=environment_exists,
        environment_current=environment_current,
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
    runner = _default_runner if runner is None else runner
    try:
        if definition.platform == "linux":
            command = {
                "start": "start",
                "stop": "stop",
                "restart": "restart",
            }[action]
            _require_ok(
                runner(["systemctl", "--user", command, definition.unit_name]),
                f"systemctl --user {command} {definition.unit_name}",
            )
        elif definition.platform == "darwin":
            if action in {"stop", "restart"}:
                _darwin_bootout(definition, runner)
            if action in {"start", "restart"}:
                _darwin_bootstrap(definition, runner)
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


def readiness_warnings(env: Mapping[str, str]) -> tuple[str, ...]:
    """Return non-secret readiness warnings for captured service env."""
    warnings: list[str] = []
    try:
        statuses = collect_agent_cli_statuses(offline=True, env=env)
    except Exception as exc:
        warnings.append(f"provider CLI readiness could not be checked: {exc}")
    else:
        for status in statuses:
            if not status.installed:
                binary = str(getattr(status, "binary", "") or "")
                live_path = _resolve_command(binary, os.environ) if binary else None
                if live_path:
                    warnings.append(
                        f"{status.display_name} CLI is available in the interactive PATH "
                        "but not the captured service PATH"
                    )
                else:
                    warnings.append(
                        f"{status.display_name} CLI is not available to the captured "
                        "service PATH"
                    )
    try:
        from sase.integrations.mobile_gateway import load_mobile_gateway_config

        gateway = load_mobile_gateway_config()
    except Exception:
        gateway = None
    command = getattr(gateway, "command", ()) if gateway is not None else ()
    if command:
        executable = str(command[0])
        if _resolve_command(executable, env) is None:
            warnings.append(
                "configured mobile gateway executable is not available to the captured service PATH"
            )
    interactive_flags = os.environ.get("SASE_FEATURE_FLAGS")
    captured_flags = env.get("SASE_FEATURE_FLAGS")
    if interactive_flags and interactive_flags != captured_flags:
        warnings.append(
            "SASE_FEATURE_FLAGS differ between the shell and captured service environment"
        )
    return tuple(warnings)


def _render_systemd_unit(
    executable: Path | None,
    *,
    unit_identity: str,
    env_path: Path,
    alternate_home: Path | None,
) -> str:
    exe = str(executable or "sase")
    lines = [
        "[Unit]",
        "Description=SASE service host",
        "",
        "[Service]",
        "Type=exec",
        f"ExecStart={_systemd_quote(exe)} service run",
        "Restart=on-failure",
        "RestartSec=5",
        "KillMode=mixed",
        f"Environment=SASE_SERVICE_ENV={_systemd_quote(str(env_path))}",
        f"Environment=SASE_SERVICE_UNIT={_systemd_quote(unit_identity)}",
    ]
    if alternate_home is not None:
        lines.append(f"Environment=SASE_HOME={_systemd_quote(str(alternate_home))}")
    lines.extend(
        [
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    return "\n".join(lines)


def _render_launchd_plist(
    executable: Path | None,
    *,
    label: str,
    env_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    alternate_home: Path | None,
) -> str:
    env = {
        "SASE_SERVICE_ENV": str(env_path),
        "SASE_SERVICE_UNIT": label,
    }
    if alternate_home is not None:
        env["SASE_HOME"] = str(alternate_home)
    payload = {
        "AbandonProcessGroup": True,
        "EnvironmentVariables": env,
        "KeepAlive": {"SuccessfulExit": False},
        "Label": label,
        "ProgramArguments": [str(executable or "sase"), "service", "run"],
        "RunAtLoad": True,
        "StandardErrorPath": str(stderr_path),
        "StandardOutPath": str(stdout_path),
        "ThrottleInterval": 10,
    }
    return plistlib.dumps(payload, sort_keys=True).decode("utf-8")


def _platform_kind() -> PlatformKind:
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "darwin"
    return "unsupported"


def _home_suffix(home: Path) -> str:
    digest = hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:12]
    return f"home-{digest}"


def _content_current(path: Path, desired: str) -> tuple[bool, bool]:
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, False
    except OSError:
        return True, False
    return True, current == desired


def _environment_current(path: Path, desired: Mapping[str, str]) -> tuple[bool, bool]:
    try:
        current_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, False
    except OSError:
        return True, False
    try:
        current = parse_service_environment_text(current_text)
    except ValueError:
        return True, False
    return True, environment_files_match(current, desired)


def _combined_diff(
    definition_path: Path,
    definition_content: str,
    env_path: Path,
    env_content: str,
) -> str:
    chunks: list[str] = []
    definition_current = _read_text_or_empty(definition_path)
    chunks.extend(
        difflib.unified_diff(
            definition_current.splitlines(keepends=True),
            definition_content.splitlines(keepends=True),
            fromfile=str(definition_path),
            tofile=str(definition_path),
        )
    )
    env_current = _redact_env_file_text(_read_text_or_empty(env_path))
    env_desired = _redact_env_file_text(env_content)
    chunks.extend(
        difflib.unified_diff(
            env_current.splitlines(keepends=True),
            env_desired.splitlines(keepends=True),
            fromfile=str(env_path),
            tofile=str(env_path),
        )
    )
    return "".join(chunks)


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _redact_env_file_text(text: str) -> str:
    if not text:
        return ""
    try:
        values = parse_service_environment_text(text)
    except (ServiceEnvironmentError, ValueError):
        return _blind_redact_env_text(text)
    return render_service_environment(dict.fromkeys(values, "[captured]"))


def _blind_redact_env_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        newline = "\n" if raw_line.endswith("\n") else ""
        line = raw_line.rstrip("\n")
        if "=" not in line:
            lines.append(raw_line)
            continue
        name, _value = line.split("=", 1)
        lines.append(f'{name}="[captured]"{newline}')
    return "".join(lines)


def _write_definition(definition: NativeServiceDefinition) -> None:
    definition.definition_path.parent.mkdir(parents=True, exist_ok=True)
    definition.definition_path.write_text(definition.content, encoding="utf-8")
    if definition.platform == "linux":
        definition.definition_path.chmod(0o644)


def _unlink_owned_definition(definition: NativeServiceDefinition) -> None:
    try:
        definition.definition_path.unlink()
    except FileNotFoundError:
        pass


def _linux_unit_enabled(unit: str, runner: CommandRunner) -> bool:
    result = runner(["systemctl", "--user", "is-enabled", unit])
    return result.returncode == 0 and result.stdout.strip() in {"enabled", "linked"}


def _linux_unit_active(unit: str, runner: CommandRunner) -> bool:
    result = runner(["systemctl", "--user", "is-active", unit])
    return result.returncode == 0 and result.stdout.strip() == "active"


def _linux_linger_enabled(runner: CommandRunner) -> bool | None:
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


def _linux_legacy_owners(runner: CommandRunner) -> tuple[str, ...]:
    found: list[str] = []
    for unit in LEGACY_SYSTEMD_UNITS:
        if _linux_unit_enabled(unit, runner) or _linux_unit_active(unit, runner):
            found.append(unit)
    return tuple(found)


def _linux_reload(runner: CommandRunner) -> None:
    _require_ok(
        runner(["systemctl", "--user", "daemon-reload"]), "systemctl daemon-reload"
    )


def _linux_enable_start(
    definition: NativeServiceDefinition,
    runner: CommandRunner,
    *,
    enable: bool = True,
    start: bool = True,
) -> None:
    if enable:
        _require_ok(
            runner(["systemctl", "--user", "enable", definition.unit_name]),
            f"systemctl enable {definition.unit_name}",
        )
    if start:
        _require_ok(
            runner(["systemctl", "--user", "start", definition.unit_name]),
            f"systemctl start {definition.unit_name}",
        )


def _linux_disable_stop(
    definition: NativeServiceDefinition, runner: CommandRunner
) -> None:
    runner(["systemctl", "--user", "stop", definition.unit_name])
    runner(["systemctl", "--user", "disable", definition.unit_name])


def _retire_linux_legacy(runner: CommandRunner) -> None:
    for unit in LEGACY_SYSTEMD_UNITS:
        runner(["systemctl", "--user", "disable", "--now", unit])


def _darwin_unit_active(label: str, runner: CommandRunner) -> tuple[bool, bool]:
    result = runner(["launchctl", "print", _darwin_service_target(label)])
    if result.returncode == 0:
        return True, False
    output = f"{result.stdout}\n{result.stderr}"
    return False, _darwin_output_user_disabled(output)


def _darwin_output_user_disabled(output: str) -> bool:
    lowered = output.casefold()
    return any(marker in lowered for marker in _DARWIN_USER_DISABLED_MARKERS)


def _darwin_legacy_owners(runner: CommandRunner) -> tuple[str, ...]:
    return tuple(
        label
        for label in LEGACY_LAUNCHD_LABELS
        if _darwin_unit_active(label, runner)[0]
    )


def _darwin_bootstrap(
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
        _require_ok(result, f"launchctl bootstrap {definition.label}")


def _darwin_bootout(definition: NativeServiceDefinition, runner: CommandRunner) -> None:
    runner(["launchctl", "bootout", _darwin_service_target(definition.label)])


def _retire_darwin_legacy(runner: CommandRunner) -> None:
    for label in LEGACY_LAUNCHD_LABELS:
        runner(["launchctl", "bootout", _darwin_service_target(label)])


def _darwin_gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _darwin_service_target(label: str) -> str:
    return f"{_darwin_gui_domain()}/{label}"


def _resolve_command(command: str, env: Mapping[str, str]) -> str | None:
    expanded = os.path.expanduser(command)
    resolved = shutil.which(expanded, path=env.get("PATH"))
    if resolved:
        return resolved
    if os.sep in expanded and os.access(expanded, os.X_OK):
        return expanded
    return None


def _service_lifecycle_blocked_in_tests(
    environ: Mapping[str, str] | None = None,
) -> bool:
    effective_environ = os.environ if environ is None else environ
    if effective_environ.get(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV) == "1":
        return False
    return pytest_context_detected(effective_environ)


def _default_runner(argv: Sequence[str]) -> CommandResult:
    if _service_lifecycle_blocked_in_tests():
        return CommandResult(
            returncode=125,
            stderr=SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE,
        )
    try:
        result = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError as exc:
        return CommandResult(returncode=127, stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_process_output_text(exc.stdout),
            stderr=_process_output_text(exc.stderr) or "timed out",
        )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _require_ok(result: CommandResult, action: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        raise RuntimeError(f"{action} failed: {detail}")
    raise RuntimeError(f"{action} failed with exit {result.returncode}")


def _systemd_quote(value: str) -> str:
    return shlex.quote(value)


def _process_output_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


__all__ = [
    "CommandResult",
    "NativeInspection",
    "NativeServiceDefinition",
    "SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE",
    "SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV",
    "ServicePlatformApplyResult",
    "ServicePlatformPlan",
    "apply_service_init",
    "apply_service_uninstall",
    "build_native_definition",
    "control_installed_service",
    "installed_native_definition",
    "inspect_native_service",
    "readiness_warnings",
    "service_init_plan",
    "service_platform_supported",
    "service_uninstall_plan",
]

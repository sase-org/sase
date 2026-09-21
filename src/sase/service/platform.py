"""Native platform-unit planning and lifecycle for the service host."""

from __future__ import annotations

import getpass
import os
import platform
from collections.abc import Callable, Mapping

from sase.agent_clis.operations import collect_agent_cli_statuses
from sase.service.effective_env import effective_ssh_agent_warnings
from sase.service.env import (
    capture_service_environment,
    render_service_environment,
    write_service_environment,
)
from sase.service.executable import service_launcher_warnings
from sase.service.platform_definition import (
    build_native_definition,
    control_installed_service,
    inspect_native_service,
    installed_native_definition,
)
from sase.service.platform_files import (
    combined_diff,
    unlink_owned_definition,
    write_definition,
)
from sase.service.platform_managers import (
    darwin_bootout,
    darwin_bootstrap,
    linux_disable_stop,
    linux_enable_start,
    linux_reload,
    resolve_command,
    retire_darwin_legacy,
    retire_linux_legacy,
)
from sase.service.platform_models import (
    SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV,
    DECLINED_MARKER,
    CommandResult,
    CommandRunner,
    NativeInspection,
    NativeServiceDefinition,
    ServicePlatformApplyResult,
    ServicePlatformPlan,
    ServicePlanStatus,
)
from sase.service.platform_runner import default_runner
from sase.service.state import clear_service_marker, set_service_marker


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
    warnings.extend(_readiness_warnings(desired_env))
    warnings.extend(service_launcher_warnings(desired_env))
    if inspection.definition_exists:
        # The capture above answers "what will init write"; this answers "what
        # would the installed host see", which a healthy caller shell cannot mask.
        warnings.extend(
            effective_ssh_agent_warnings(
                platform_kind=definition.platform,
                env_path=definition.env_path,
                desired_env=desired_env,
                runner=default_runner if runner is None else runner,
            )
        )

    diff = combined_diff(
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
    runner = default_runner if runner is None else runner
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
    write_definition(definition)
    try:
        if definition.platform == "linux":
            linux_reload(runner)
            retire_linux_legacy(runner)
            linux_enable_start(
                definition,
                runner,
                enable=not already_enabled,
                start=not already_active,
            )
        elif definition.platform == "darwin":
            retire_darwin_legacy(runner)
            if not user_disabled and not already_active:
                darwin_bootstrap(definition, runner)
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
    runner = default_runner if runner is None else runner
    definition = plan.definition
    try:
        if definition.platform == "linux":
            linux_disable_stop(definition, runner)
            unlink_owned_definition(definition)
            linux_reload(runner)
        elif definition.platform == "darwin":
            darwin_bootout(definition, runner)
            unlink_owned_definition(definition)
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


def _readiness_warnings(env: Mapping[str, str]) -> tuple[str, ...]:
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
                live_path = resolve_command(binary, os.environ) if binary else None
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
        if resolve_command(executable, env) is None:
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
    "service_init_plan",
    "service_uninstall_plan",
]

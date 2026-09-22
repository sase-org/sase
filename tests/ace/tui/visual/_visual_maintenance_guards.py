"""Environment guards and renderer identity for visual maintenance."""

from __future__ import annotations

from collections.abc import Mapping
import os
import sys
from typing import Any

from tests.ace.tui.visual._visual_maintenance_types import (
    MaintenanceHooks,
    MaintenanceRequest,
    UsageError,
)


def refuse_ci_update(
    request: MaintenanceRequest,
    *,
    hooks: MaintenanceHooks,
    environ: Mapping[str, str],
) -> None:
    if request.check:
        return
    is_ci = hooks.is_ci or default_is_ci
    if is_ci(environ):
        raise UsageError(
            "update refused because CI or GITHUB_ACTIONS is set; re-run with --check"
        )


def preflight(request: MaintenanceRequest, *, hooks: MaintenanceHooks) -> None:
    preflight_hook = hooks.preflight
    if preflight_hook is not None:
        preflight_hook(not request.check)
        return
    default_preflight(update=not request.check, platform_system=hooks.platform_system)


def default_preflight(
    *,
    update: bool,
    platform_system: Any | None = None,
) -> None:
    from tests.ace.tui.visual.renderer_env import (
        RendererEnvironmentError,
        assert_renderer_environment,
    )

    try:
        if platform_system is None:
            assert_renderer_environment(update=update)
        else:
            assert_renderer_environment(
                update=update,
                platform_system=platform_system,
            )
    except RendererEnvironmentError as error:
        raise UsageError(str(error)) from error


def default_is_ci(environ: Mapping[str, str]) -> bool:
    """Return whether *environ* is a real CI that must not write goldens.

    SASE agent workspaces export ``CI=true`` for pytest/tooling, so ``CI``
    alone is not enough when ``SASE_AGENT`` is set. Detached ``sase monitor``
    commands do not inherit ``SASE_AGENT*`` identity, but they do set
    ``SASE_MONITOR_ID``; treat that the same way. GitHub Actions still
    refuses because it sets ``GITHUB_ACTIONS``.
    """
    if _truthy(environ.get("GITHUB_ACTIONS")):
        return True
    if _truthy(environ.get("SASE_AGENT")) or _truthy(environ.get("SASE_MONITOR_ID")):
        return False
    return _truthy(environ.get("CI"))


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def renderer_identity(hooks: MaintenanceHooks) -> dict[str, Any]:
    if hooks.renderer_identity is not None:
        return hooks.renderer_identity()
    identity: dict[str, Any] = {
        "platform": f"{os.uname().sysname}-{os.uname().machine}"
        if hasattr(os, "uname")
        else "",
        "python_version": sys.version.split()[0],
    }
    try:
        from tests.ace.tui.visual.renderer_env import (
            load_renderer_environment_manifest,
        )

        manifest = load_renderer_environment_manifest()
        identity["packages"] = dict(manifest.packages)
        identity["fonts"] = dict(manifest.fonts)
    except Exception as error:
        identity["manifest_error"] = str(error)
    return identity

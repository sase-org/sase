"""Resource capacity check registry for ``sase doctor``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.axe.config import AxeConfig
from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.doctor import checks_resources_disk as _disk
from sase.doctor import checks_resources_ulimits as _ulimits
from sase.doctor.checks_resources_ace_run_watches import check_ace_run_watches
from sase.doctor.checks_resources_chezmoi import check_chezmoi
from sase.doctor.checks_resources_inotify import (
    INOTIFY_MIN_USER_INSTANCES,
    check_inotify,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_DISK_ERROR_FREE_BYTES = _disk._DISK_ERROR_FREE_BYTES
_DISK_WARN_FREE_BYTES = _disk._DISK_WARN_FREE_BYTES
_INOTIFY_MIN_USER_INSTANCES = INOTIFY_MIN_USER_INSTANCES
_check_chezmoi = check_chezmoi
_check_inotify = check_inotify
_check_ace_run_watches = check_ace_run_watches
workspace_root_path: Callable[[DoctorContext], tuple[Path | None, str | None]] = (
    _disk.workspace_root_path
)
import_resource_module: Callable[[], Any | None] = _ulimits.import_resource_module


def resource_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default host-resource check specs."""
    return (
        CheckSpec(
            id="resources.disk_free",
            group="resources",
            title="Free disk space",
            runner=lambda: _check_disk_free(context),
        ),
        CheckSpec(
            id="resources.chezmoi",
            group="resources",
            title="Chezmoi source",
            runner=check_chezmoi,
            deep=True,
        ),
        CheckSpec(
            id="resources.ulimits",
            group="resources",
            title="Process resource limits",
            runner=_check_ulimits,
            deep=True,
        ),
        CheckSpec(
            id="resources.inotify",
            group="resources",
            title="Linux inotify limits",
            runner=check_inotify,
            deep=True,
        ),
        CheckSpec(
            id="resources.ace_run_watches",
            group="resources",
            title="ACE ace-run watch coverage",
            runner=lambda: check_ace_run_watches(context),
        ),
    )


def _check_disk_free(
    context: DoctorContext,
    *,
    disk_usage_fn: Callable[[str], Any] | None = None,
) -> DiagnosticCheck:
    """Check free space where managed workspaces and SASE state live."""
    return _disk.check_disk_free(
        context,
        disk_usage_fn=disk_usage_fn,
        workspace_root_fn=workspace_root_path,
    )


def _check_ulimits(
    *,
    axe_config: AxeConfig | None = None,
    getrlimit_fn: Callable[[int], tuple[int, int]] | None = None,
    resource_module: Any | None = None,
) -> DiagnosticCheck:
    """Check soft process/file limits against configured runner concurrency."""
    return _ulimits.check_ulimits(
        axe_config=axe_config,
        getrlimit_fn=getrlimit_fn,
        resource_module=resource_module,
        import_resource_module_fn=import_resource_module,
    )

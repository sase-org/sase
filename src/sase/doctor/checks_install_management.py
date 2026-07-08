"""Install/update management readiness checks for ``sase doctor``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TYPE_CHECKING

from sase.diagnostics import DiagnosticCheck
from sase.doctor.checks_runtime_common import which_from_env
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


ProbeUvToolInstallFn = Callable[..., UvToolInstall | NotUvToolInstall]


def check_install_management(
    context: DoctorContext,
    *,
    probe_fn: ProbeUvToolInstallFn | None = None,
) -> DiagnosticCheck:
    """Check whether update/plugin management can safely use ``uv tool``."""
    probe = probe_fn or probe_uv_tool_install
    result = probe(
        which_fn=which_from_env(context.env),
        environ=context.env,
    )

    if isinstance(result, UvToolInstall):
        data = uv_tool_data(result)
        return DiagnosticCheck(
            id="install.management",
            group="install",
            status="OK",
            title="Install management readiness",
            summary="sase is managed by uv tool; install/update workflows are available",
            details=uv_tool_details(data),
            data=data,
        )

    data = uv_tool_data(result)
    reason = result.reason.value
    return DiagnosticCheck(
        id="install.management",
        group="install",
        status="WARN",
        title="Install management readiness",
        summary=(f"sase is not running from a canonical uv-tool install ({reason})"),
        details=(
            *uv_tool_details(data),
            "affected flows: `sase update`, plugin management, Admin Center updates, "
            "chat-driven install/update workers",
        ),
        next_steps=(
            "Install or run SASE via `uv tool install sase` before using install/update management flows.",
            "Rerun `sase doctor -C install.management -v` from the intended environment.",
        ),
        data=data,
    )


def uv_tool_data(result: UvToolInstall | NotUvToolInstall) -> dict[str, Any]:
    if isinstance(result, UvToolInstall):
        return {
            "managed": True,
            "reason": None,
            "uv_path": result.uv_path,
            "tool_dir": str(result.tool_dir),
            "sys_prefix": str(result.sase_dir),
            "receipt_path": str(result.receipt_path),
        }

    return {
        "managed": False,
        "reason": result.reason.value,
        "uv_path": result.uv_path,
        "tool_dir": str(result.expected_sase_dir.parent),
        "sys_prefix": str(result.sys_prefix),
        "receipt_path": str(result.receipt_path),
    }


def uv_tool_details(data: Mapping[str, Any]) -> tuple[str, ...]:
    uv_path = data["uv_path"] if data["uv_path"] else "missing"
    details = [
        f"uv path: {uv_path}",
        f"uv tool dir: {data['tool_dir']}",
        f"sys.prefix: {data['sys_prefix']}",
        f"receipt: {data['receipt_path']}",
    ]
    if data["reason"]:
        details.insert(0, f"reason: {data['reason']}")
    return tuple(details)


__all__ = [
    "check_install_management",
    "probe_uv_tool_install",
    "uv_tool_data",
    "uv_tool_details",
]

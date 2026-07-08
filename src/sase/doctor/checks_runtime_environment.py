"""Python runtime, package inventory, and Rust core checks for ``sase doctor``."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.core.health import HEALTH_OK, check_backend_health
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_runtime_common import safe_resolve
from sase.doctor.checks_vcs_git import git_result
from sase.version.inventory import VersionPackageRecord

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


CheckoutRootFn = Callable[[Path], Path | None]
PythonVersionFn = Callable[[], tuple[int, int]]


def check_runtime_version(context: DoctorContext) -> DiagnosticCheck:
    """Collect the active host/core/plugin runtime inventory."""
    inventory = context.get_runtime_inventory()
    package_warnings = [
        f"{record.name}: {warning}"
        for record in inventory.packages
        for warning in record.warnings
    ]
    host = record_by_role(inventory.packages, "host")
    core = record_by_role(inventory.packages, "core")
    plugin_count = sum(1 for record in inventory.packages if record.role == "plugin")
    status: CheckStatus = "WARN" if package_warnings else "OK"
    summary = (
        f"{len(inventory.packages)} packages detected; "
        f"host={display_record(host)}, core={display_record(core)}, "
        f"plugins={plugin_count}"
    )
    if package_warnings:
        summary = f"{len(package_warnings)} package warning(s) found"

    data: dict[str, Any] = {
        "executable": inventory.executable,
        "python_executable": inventory.python_executable,
        "python_version": inventory.python_version,
        "package_count": len(inventory.packages),
        "packages": [
            {
                "name": record.name,
                "role": record.role,
                "display_version": record.display_version,
                "install_type": record.install_type,
                "source_root": record.source_root,
                "code_directory": record.code_directory,
            }
            for record in inventory.packages
        ],
        "warnings": package_warnings,
    }
    if context.verbose:
        data["inventory"] = inventory.to_dict()

    return DiagnosticCheck(
        id="runtime.version",
        group="runtime",
        status=status,
        title="Runtime package inventory",
        summary=summary,
        details=tuple(package_warnings[:8]),
        next_steps=("Run `sase version -v` for the full runtime package audit.",)
        if package_warnings
        else (),
        data=data,
    )


def check_runtime_core() -> DiagnosticCheck:
    """Adapt ``sase core health`` into the shared doctor model."""
    report = check_backend_health()
    probes = report.extras.get("probes", {})
    if not isinstance(probes, Mapping):
        probes = {}
    passed = sum(1 for ok in probes.values() if ok)
    total = len(probes)
    status: CheckStatus = "OK" if report.status == HEALTH_OK else "ERROR"
    if status == "OK":
        summary = (
            f"{report.rust_extension_module} loaded; {passed}/{total} probes passed"
        )
    else:
        summary = report.error or f"{report.rust_extension_module} health check failed"

    details = [
        f"python: {report.python_version}",
        f"platform: {report.platform}",
    ]
    if report.rust_extension_path:
        details.append(f"extension path: {report.rust_extension_path}")
    if report.rust_extension_version:
        details.append(f"extension version: {report.rust_extension_version}")
    if report.error:
        details.append(f"error: {report.error}")

    return DiagnosticCheck(
        id="runtime.core",
        group="runtime",
        status=status,
        title="Rust core health",
        summary=summary,
        details=tuple(details),
        next_steps=(
            "Run `just install` in this workspace, then `sase core health -j`.",
        )
        if status == "ERROR"
        else (),
        data=report.to_dict(),
    )


def check_runtime_environment(
    context: DoctorContext,
    *,
    checkout_root_fn: CheckoutRootFn | None = None,
    python_version_fn: PythonVersionFn | None = None,
) -> DiagnosticCheck:
    """Check Python support and editable/source-root drift."""
    resolve_checkout_root = checkout_root_fn or current_checkout_root
    get_python_version = python_version_fn or current_python_version

    inventory = context.get_runtime_inventory()
    details: list[str] = [
        f"python: {inventory.python_version}",
        f"python executable: {inventory.python_executable}",
        f"sase executable: {inventory.executable}",
    ]
    next_steps: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    if get_python_version() < (3, 12):
        errors.append("Python 3.12 or newer is required.")
        next_steps.append("Use a Python 3.12+ environment and rerun `just install`.")

    host = record_by_role(inventory.packages, "host")
    checkout_root = resolve_checkout_root(context.cwd)
    host_root = record_source_root(host)
    if checkout_root is not None:
        details.append(f"checkout root: {checkout_root}")
    if host_root is not None:
        details.append(f"host source root: {host_root}")

    if (
        host is not None
        and host.install_type == "editable"
        and checkout_root is not None
        and host_root is not None
        and safe_resolve(checkout_root) != safe_resolve(host_root)
    ):
        warnings.append(
            "active sase import root differs from the current checkout root"
        )
        next_steps.append("Run `just install` in this workspace.")

    status: CheckStatus = "ERROR" if errors else "WARN" if warnings else "OK"
    summary = "runtime environment is consistent"
    if errors:
        summary = errors[0]
    elif warnings:
        summary = warnings[0]

    return DiagnosticCheck(
        id="runtime.environment",
        group="runtime",
        status=status,
        title="Runtime environment",
        summary=summary,
        details=(*details, *errors, *warnings),
        next_steps=tuple(dict.fromkeys(next_steps)),
        data={
            "python_version": inventory.python_version,
            "python_executable": inventory.python_executable,
            "sase_executable": inventory.executable,
            "checkout_root": str(checkout_root) if checkout_root else None,
            "host_source_root": str(host_root) if host_root else None,
            "host_install_type": host.install_type if host else None,
        },
    )


def record_by_role(
    records: Sequence[VersionPackageRecord], role: str
) -> VersionPackageRecord | None:
    return next((record for record in records if record.role == role), None)


def display_record(record: VersionPackageRecord | None) -> str:
    if record is None:
        return "missing"
    return f"{record.name} {record.display_version}"


def record_source_root(record: VersionPackageRecord | None) -> Path | None:
    if record is None:
        return None
    for value in (record.source_root, record.code_directory, record.import_path):
        if value:
            return Path(value)
    return None


def current_checkout_root(cwd: Path) -> Path | None:
    result = git_result(cwd, "rev-parse", "--show-toplevel")
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return find_ancestor_with(cwd, "pyproject.toml")


def find_ancestor_with(start: Path, filename: str) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / filename).is_file():
            return candidate
    return None


def current_python_version() -> tuple[int, int]:
    return (sys.version_info.major, sys.version_info.minor)


__all__ = [
    "check_runtime_core",
    "check_runtime_environment",
    "check_runtime_version",
    "current_checkout_root",
    "current_python_version",
    "display_record",
    "find_ancestor_with",
    "record_by_role",
    "record_source_root",
]

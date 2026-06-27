"""Receipt and runtime routing helpers for ``sase update``."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
from typing import Literal

from sase.main.update_types import DevRoute, InventoryFn, VersionFn
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import ReceiptError, UvToolError
from sase.uv_tool.receipt import Requirement, ToolReceipt, load_receipt
from sase.uv_tool.render import PackageRole, PlannedPackage
from sase.version._utils import normalize_distribution_name
from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord


def installed_version(name: str) -> str | None:
    """Return the installed version of distribution *name*, or ``None``."""
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 — version display must never crash the run.
        return None


def try_load_receipt(install: UvToolInstall) -> ToolReceipt | None:
    """Load the receipt for the package set, tolerating a parse failure.

    The upgrade has already succeeded by this point; a malformed receipt should
    only degrade the pretty "already current" cross-reference, never fail the
    command.
    """
    try:
        return load_receipt(install.receipt_path)
    except ReceiptError:
        return None


def dev_route(
    receipt: ToolReceipt | None, inventory_fn: InventoryFn
) -> DevRoute | UvToolError | None:
    if receipt is None:
        return None

    editable_keys = _editable_receipt_keys(receipt)
    if not editable_keys:
        return None

    try:
        inventory = inventory_fn()
    except Exception as exc:  # noqa: BLE001 - command output must stay actionable.
        return UvToolError(f"could not inspect editable runtime packages: {exc}")

    records_by_name = {
        normalize_distribution_name(record.name): record
        for record in inventory.packages
        if record.install_type == "editable"
    }
    records = tuple(
        record
        for key in _receipt_key_order(receipt)
        if key in editable_keys and (record := records_by_name.get(key)) is not None
    )
    if not records:
        return UvToolError(
            "the uv tool receipt contains editable packages, but no matching "
            "editable runtime records were found; run `sase version` to inspect "
            "the install."
        )

    return DevRoute(
        records=records,
        host_record=_host_record(inventory, receipt),
        managed_requirements=_managed_requirements(receipt),
    )


def _receipt_requirements(receipt: ToolReceipt) -> tuple[Requirement, ...]:
    return (receipt.primary, *receipt.deduped_injected_plugins())


def _receipt_key_order(receipt: ToolReceipt) -> tuple[str, ...]:
    return tuple(req.normalized_name for req in _receipt_requirements(receipt))


def _editable_receipt_keys(receipt: ToolReceipt) -> frozenset[str]:
    return frozenset(
        req.normalized_name for req in _receipt_requirements(receipt) if req.editable
    )


def _managed_requirements(receipt: ToolReceipt) -> tuple[Requirement, ...]:
    return tuple(req for req in _receipt_requirements(receipt) if not req.editable)


def _host_record(
    inventory: RuntimeVersionInventory, receipt: ToolReceipt
) -> VersionPackageRecord:
    host_key = normalize_distribution_name("sase")
    for record in inventory.packages:
        if (
            record.role == "host"
            or normalize_distribution_name(record.name) == host_key
        ):
            return record
    install_type: Literal["editable", "unknown"] = (
        "editable" if receipt.primary.editable else "unknown"
    )
    return VersionPackageRecord(
        name=receipt.primary.name,
        role="host",
        display_version="unknown",
        distribution_version=None,
        source_version=None,
        import_module="sase",
        import_path=None,
        code_directory=None,
        source_root=receipt.primary.editable,
        distribution_location=None,
        install_type=install_type,
        git=None,
    )


def should_run_managed_update(
    receipt: ToolReceipt | None, route: DevRoute | UvToolError | None
) -> bool:
    if receipt is None:
        return True
    if route is None or isinstance(route, UvToolError):
        return True
    return bool(route.managed_requirements)


def update_mode(*, has_dev: bool, has_managed: bool) -> str:
    if has_dev and has_managed:
        return "mixed"
    if has_dev:
        return "dev"
    return "managed"


def managed_summary_receipt(receipt: ToolReceipt | None) -> ToolReceipt | None:
    if receipt is None:
        return None
    if receipt.primary.editable:
        return None
    plugins = tuple(
        plugin for plugin in receipt.deduped_injected_plugins() if not plugin.editable
    )
    return ToolReceipt(
        primary=receipt.primary,
        plugins=plugins,
        requirements=(receipt.primary, *plugins),
    )


def planned_packages(
    receipt: ToolReceipt, version_fn: VersionFn
) -> tuple[PlannedPackage, ...]:
    packages = [
        PlannedPackage(
            name=receipt.primary.name,
            role="primary",
            current_version=version_fn(receipt.primary.name),
        )
    ]
    packages += [
        PlannedPackage(
            name=plugin.name,
            role="plugin",
            current_version=version_fn(plugin.name),
        )
        for plugin in receipt.deduped_injected_plugins()
    ]
    return tuple(packages)


def planned_packages_for_requirements(
    requirements: tuple[Requirement, ...],
    *,
    receipt: ToolReceipt,
    version_fn: VersionFn,
) -> tuple[PlannedPackage, ...]:
    primary_key = receipt.primary.normalized_name
    packages: list[PlannedPackage] = []
    for req in requirements:
        role: PackageRole = (
            "primary" if req.normalized_name == primary_key else "plugin"
        )
        packages.append(
            PlannedPackage(
                name=req.name,
                role=role,
                current_version=version_fn(req.name),
            )
        )
    return tuple(packages)

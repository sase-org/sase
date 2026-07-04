"""Side-effect-free planning for install-mode switching."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from packaging.version import InvalidVersion, Version

from sase.core.paths import sase_home
from sase.main.update_routing import dev_route, update_mode
from sase.mode_switch.models import (
    DetectedMode,
    ModeSwitchCommand,
    SwitchPackagePlan,
    SwitchPlan,
    TargetMode,
)
from sase.mode_switch.repos import (
    RepoSpec,
    config_dev_root,
    load_catalog_best_effort,
    repo_for_package,
)
from sase.plugins.pypi_source import fetch_latest_version
from sase.uv_tool.commands import build_reinstall_set
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import ReceiptError, UvToolError
from sase.uv_tool.receipt import Requirement, ToolReceipt, load_receipt
from sase.version._display import derive_display_version
from sase.version._git import classify_git_upstream, probe_git_metadata_at_ref
from sase.version._models import RuntimeVersionInventory, VersionPackageRecord
from sase.version._sources import python_source_version, rust_source_version
from sase.version._utils import normalize_distribution_name

InventoryFn = Callable[[], RuntimeVersionInventory]
LatestFn = Callable[[str], str | None]
WhichFn = Callable[[str], str | None]

_CORE_DIST = "sase-core-rs"


def plan_mode_switch(
    install: UvToolInstall,
    *,
    target_mode: TargetMode,
    config: dict[str, object] | None,
    inventory_fn: InventoryFn,
    latest_fn: LatestFn = fetch_latest_version,
    which_fn: WhichFn = shutil.which,
) -> SwitchPlan:
    """Build a confirmable mode-switch plan without mutating the environment."""
    try:
        receipt = load_receipt(install.receipt_path)
    except ReceiptError as exc:
        raise UvToolError(str(exc)) from exc

    try:
        inventory = inventory_fn()
    except Exception as exc:  # noqa: BLE001 - keep CLI/TUI errors actionable.
        raise UvToolError(f"could not inspect runtime packages: {exc}") from exc

    current_mode = _detect_mode(receipt, inventory_fn=lambda: inventory)
    dev_root = config_dev_root(config)
    backup_path = sase_home() / "update" / "mode_switch_backup.json"
    restore_command = tuple(
        build_reinstall_set(
            receipt.primary,
            receipt.deduped_injected_plugins(),
            color="never",
        )
    )

    if current_mode != "mixed" and (
        (current_mode == "dev" and target_mode == "dev")
        or (current_mode == "managed" and target_mode == "pypi")
    ):
        return SwitchPlan(
            current_mode=current_mode,
            target_mode=target_mode,
            dev_root=str(dev_root) if target_mode == "dev" else None,
            packages=(),
            commands=(),
            restore_command=restore_command,
            backup_path=str(backup_path),
        )

    if target_mode == "dev":
        return _plan_to_dev(
            receipt,
            inventory,
            current_mode=current_mode,
            dev_root=dev_root,
            restore_command=restore_command,
            backup_path=backup_path,
            which_fn=which_fn,
        )
    return _plan_to_pypi(
        receipt,
        inventory,
        current_mode=current_mode,
        latest_fn=latest_fn,
        restore_command=restore_command,
        backup_path=backup_path,
    )


def _detect_mode(receipt: ToolReceipt, *, inventory_fn: InventoryFn) -> DetectedMode:
    route = dev_route(receipt, inventory_fn)
    if isinstance(route, UvToolError):
        editable = _has_editable(receipt)
        managed = _has_managed(receipt)
        return update_mode(has_dev=editable, has_managed=managed)  # type: ignore[return-value]
    has_dev = route is not None and bool(route.records)
    has_managed = _has_managed(receipt)
    return update_mode(has_dev=has_dev, has_managed=has_managed)  # type: ignore[return-value]


def _plan_to_dev(
    receipt: ToolReceipt,
    inventory: RuntimeVersionInventory,
    *,
    current_mode: DetectedMode,
    dev_root: Path,
    restore_command: tuple[str, ...],
    backup_path: Path,
    which_fn: WhichFn,
) -> SwitchPlan:
    if which_fn("git") is None:
        raise UvToolError("git is required to switch to Dev (editable) mode")

    catalog = load_catalog_best_effort()
    records = _records_by_name(inventory)
    warnings: list[str] = []
    packages: list[SwitchPackagePlan] = []
    clone_or_fetch: list[ModeSwitchCommand] = []
    editable_plugins: list[Requirement] = []
    managed_plugins: list[Requirement] = []

    primary_spec = repo_for_package(receipt.primary.name, catalog=catalog)
    assert primary_spec is not None
    primary_path = dev_root / primary_spec.checkout_name
    packages.append(
        _dev_package_row(
            receipt.primary.name,
            "host",
            records,
            spec=primary_spec,
            checkout_path=primary_path,
            fallback_version=receipt.primary.specifier,
            warnings=warnings,
            commands=clone_or_fetch,
        )
    )
    primary_req = Requirement(name=receipt.primary.name, editable=str(primary_path))

    cargo_available = which_fn("cargo") is not None
    core_spec = repo_for_package(_CORE_DIST, catalog=catalog)
    if cargo_available and core_spec is not None:
        core_path = dev_root / core_spec.checkout_name
        packages.append(
            _dev_package_row(
                _CORE_DIST,
                "core",
                records,
                spec=core_spec,
                checkout_path=core_path,
                fallback_version=None,
                warnings=warnings,
                commands=clone_or_fetch,
            )
        )
    else:
        reason = "cargo is not available; keeping published sase-core-rs wheel"
        warnings.append(reason)
        packages.append(
            SwitchPackagePlan(
                name=_CORE_DIST,
                role="core",
                current_version=_current_version(records, _CORE_DIST),
                target_version=_current_version(records, _CORE_DIST),
                source="stays on PyPI (cargo missing)",
                repo_action="stays-managed",
                warning=reason,
            )
        )

    for plugin in receipt.deduped_injected_plugins():
        spec = repo_for_package(plugin.name, catalog=catalog)
        if spec is None:
            reason = "no known repository; stays on PyPI"
            warnings.append(f"{plugin.name}: {reason}")
            packages.append(
                SwitchPackagePlan(
                    name=plugin.name,
                    role="plugin",
                    current_version=_current_version(records, plugin.name),
                    target_version=_current_version(records, plugin.name),
                    source=reason,
                    repo_action="stays-managed",
                    warning=reason,
                )
            )
            managed_plugins.append(_index_requirement_for(receipt, plugin))
            continue

        path = dev_root / spec.checkout_name
        packages.append(
            _dev_package_row(
                plugin.name,
                "plugin",
                records,
                spec=spec,
                checkout_path=path,
                fallback_version=plugin.specifier,
                warnings=warnings,
                commands=clone_or_fetch,
            )
        )
        editable_plugins.append(Requirement(name=plugin.name, editable=str(path)))

    uv_command = ModeSwitchCommand(
        kind="uv_tool_install",
        label="Install editable package set",
        command=tuple(
            build_reinstall_set(
                primary_req,
                (*editable_plugins, *managed_plugins),
                color="never",
            )
        ),
    )
    commands = [*clone_or_fetch, uv_command]
    if cargo_available and core_spec is not None:
        commands.append(
            ModeSwitchCommand(
                kind="rust_install_uv_tool",
                label="Rebuild sase-core-rs into the uv-tool venv",
                command=("just", "rust-install-uv-tool"),
                cwd=str(primary_path),
            )
        )

    return SwitchPlan(
        current_mode=current_mode,
        target_mode="dev",
        dev_root=str(dev_root),
        packages=tuple(packages),
        commands=tuple(commands),
        warnings=tuple(_dedupe(warnings)),
        restore_command=restore_command,
        backup_path=str(backup_path),
    )


def _plan_to_pypi(
    receipt: ToolReceipt,
    inventory: RuntimeVersionInventory,
    *,
    current_mode: DetectedMode,
    latest_fn: LatestFn,
    restore_command: tuple[str, ...],
    backup_path: Path,
) -> SwitchPlan:
    records = _records_by_name(inventory)
    primary = _index_requirement_for(receipt, receipt.primary)
    plugins = tuple(
        _index_requirement_for(receipt, plugin)
        for plugin in receipt.deduped_injected_plugins()
    )
    packages = [
        _pypi_package_row(primary.name, "host", records, latest_fn),
        _pypi_package_row(_CORE_DIST, "core", records, latest_fn),
    ]
    packages.extend(
        _pypi_package_row(plugin.name, "plugin", records, latest_fn)
        for plugin in plugins
    )
    command = ModeSwitchCommand(
        kind="uv_tool_install",
        label="Install published package set",
        command=tuple(build_reinstall_set(primary, plugins, color="never")),
    )
    return SwitchPlan(
        current_mode=current_mode,
        target_mode="pypi",
        dev_root=None,
        packages=tuple(packages),
        commands=(command,),
        restore_command=restore_command,
        backup_path=str(backup_path),
    )


def _dev_package_row(
    name: str,
    role: str,
    records: dict[str, VersionPackageRecord],
    *,
    spec: RepoSpec,
    checkout_path: Path,
    fallback_version: str | None,
    warnings: list[str],
    commands: list[ModeSwitchCommand],
) -> SwitchPackagePlan:
    exists = checkout_path.exists()
    action = "reuse" if exists else "clone"
    source = f"{action} {checkout_path}" if exists else f"clone {spec.full_name}"
    target = _target_dev_version(
        checkout_path,
        role=role,
        current=_current_version(records, name),
        fallback=fallback_version,
    )
    warning = _checkout_warning(checkout_path) if exists else None
    if warning:
        warnings.append(f"{name}: {warning}")
    if exists:
        commands.append(
            ModeSwitchCommand(
                kind="git_fetch",
                label=f"Fetch {name}",
                command=("git", "fetch", "--quiet", "--tags"),
                cwd=str(checkout_path),
            )
        )
    else:
        commands.append(
            ModeSwitchCommand(
                kind="git_clone",
                label=f"Clone {name}",
                command=("git", "clone", spec.url, str(checkout_path)),
            )
        )
    return SwitchPackagePlan(
        name=name,
        role=role,  # type: ignore[arg-type]
        current_version=_current_version(records, name),
        target_version=target,
        source=source,
        repo_action=action,  # type: ignore[arg-type]
        checkout_path=str(checkout_path),
        repo_url=spec.url,
        warning=warning,
    )


def _pypi_package_row(
    name: str,
    role: str,
    records: dict[str, VersionPackageRecord],
    latest_fn: LatestFn,
) -> SwitchPackagePlan:
    latest = latest_fn(name)
    return SwitchPackagePlan(
        name=name,
        role=role,  # type: ignore[arg-type]
        current_version=_current_version(records, name),
        target_version=latest or "latest on PyPI",
        source="PyPI",
    )


def _target_dev_version(
    checkout_path: Path,
    *,
    role: str,
    current: str | None,
    fallback: str | None,
) -> str:
    if not checkout_path.exists():
        return "dev @ main (will clone)"
    base = (
        rust_source_version(checkout_path)
        if role == "core"
        else python_source_version(checkout_path)
    )
    result = probe_git_metadata_at_ref(checkout_path, "HEAD")
    if result.metadata is None:
        return base or current or fallback or "dev checkout"
    return derive_display_version(base or current or fallback, result.metadata)


def _checkout_warning(path: Path) -> str | None:
    try:
        status = classify_git_upstream(path)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return "git state unavailable"
    if status.detached:
        return "checkout is detached"
    if status.dirty:
        return "checkout has local changes; reused as-is"
    if status.diverged:
        return "checkout has diverged from upstream; reused as-is"
    if not status.has_upstream:
        return "checkout has no upstream; reused as-is"
    return None


def _index_requirement_for(
    receipt: ToolReceipt, requirement: Requirement
) -> Requirement:
    for candidate in receipt.requirements:
        if (
            candidate.normalized_name == requirement.normalized_name
            and candidate.editable is None
        ):
            return candidate
    return Requirement(
        name=requirement.name,
        extras=requirement.extras,
        specifier=requirement.specifier,
        git=requirement.git,
        git_ref=requirement.git_ref,
        url=requirement.url if requirement.editable is None else None,
    )


def _records_by_name(
    inventory: RuntimeVersionInventory,
) -> dict[str, VersionPackageRecord]:
    return {
        normalize_distribution_name(record.name): record
        for record in inventory.packages
    }


def _current_version(records: dict[str, VersionPackageRecord], name: str) -> str | None:
    record = records.get(normalize_distribution_name(name))
    return record.display_version if record is not None else None


def _has_editable(receipt: ToolReceipt) -> bool:
    return any(
        req.editable for req in (receipt.primary, *receipt.deduped_injected_plugins())
    )


def _has_managed(receipt: ToolReceipt) -> bool:
    return any(
        not req.editable
        for req in (receipt.primary, *receipt.deduped_injected_plugins())
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def compare_versions(old: str | None, new: str | None) -> int | None:
    """Return -1/0/1 for old-vs-new when both are parseable."""
    if not old or not new:
        return None
    try:
        old_v = Version(old)
        new_v = Version(new)
    except InvalidVersion:
        return None
    return (new_v > old_v) - (new_v < old_v)


def backup_payload(plan: SwitchPlan) -> dict[str, object]:
    return {
        "schema_version": 1,
        "created_at": time.time(),
        "current_mode": plan.current_mode,
        "target_mode": plan.target_mode,
        "restore_command": list(plan.restore_command),
    }

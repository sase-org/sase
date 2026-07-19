"""Editable-checkout dev-update helpers for the Updates tab."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sase.dev_update.execute import execute_dev_update, run_dev_update_command
from sase.dev_update.models import DevCommandRunner, DevUpdatePlan, DevUpdateResult
from sase.dev_update.plan import plan_dev_update
from sase.main.update_routing import (
    dev_route_from_inventory,
    managed_update_argv,
    managed_update_packages,
)
from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.render_common import humanize_duration
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import ToolReceipt
from sase.uv_tool.render import PlannedPackage
from sase.version._models import VersionPackageRecord
from sase.version._utils import normalize_distribution_name
from sase.version.inventory import collect_runtime_version_inventory


@dataclass(frozen=True)
class DevUpdatePreview:
    """Off-thread dev-update planning result for a confirm-preview modal."""

    plan: DevUpdatePlan | None
    subject: str
    error: str | None = None
    managed_argv: tuple[str, ...] = ()
    managed_packages: tuple[PlannedPackage, ...] = ()


def make_sase_dev_update_preview(
    receipt: ToolReceipt | None,
    *,
    already_refreshed_roots: Collection[str] = (),
) -> DevUpdatePreview:
    """Plan a full ``sase update`` for editable host/core/plugin packages.

    A ``None`` plan means no editable runtime packages are installed, so callers
    should fall back to the managed ``uv tool upgrade sase`` path.
    """
    inventory = collect_runtime_version_inventory(include_plugins=True)
    records = inventory.packages
    host: VersionPackageRecord | None
    stale_core: VersionPackageRecord | None
    if receipt is not None:
        route = dev_route_from_inventory(receipt, inventory)
        if isinstance(route, UvToolError):
            return DevUpdatePreview(plan=None, subject="sase", error=str(route))
        if route is None:
            error = missing_local_requirements_error(receipt.reconstruct())
            if error is not None:
                return DevUpdatePreview(plan=None, subject="sase", error=str(error))
            return DevUpdatePreview(plan=None, subject="sase")
        editable = route.records
        host = route.host_record
        stale_core = route.stale_core_record
        versions = {
            normalize_distribution_name(record.name): record.distribution_version
            or record.display_version
            for record in records
        }
        managed_argv = tuple(managed_update_argv(receipt, route, color="never"))
        if managed_argv:
            error = missing_local_requirements_error(receipt.reconstruct())
            if error is not None:
                return DevUpdatePreview(plan=None, subject="sase", error=str(error))
        managed_packages = managed_update_packages(
            receipt,
            route,
            version_fn=lambda name: versions.get(normalize_distribution_name(name)),
        )
    else:
        editable = tuple(
            record
            for record in records
            if record.install_type == "editable"
            and record.role in {"host", "core", "plugin"}
        )
        host = _host_record(records)
        stale_core = _stale_core_record(records, host)
        managed_argv = ()
        managed_packages = ()
    if not editable:
        return DevUpdatePreview(plan=None, subject="sase")
    if host is None:
        return DevUpdatePreview(
            plan=None,
            subject="sase",
            error="Runtime inventory is missing the host `sase` package.",
        )
    return _plan(
        editable,
        records=records,
        receipt=receipt,
        subject="sase",
        already_refreshed_roots=already_refreshed_roots,
        host_record=host,
        managed_argv=managed_argv,
        managed_packages=managed_packages,
        stale_core_record=stale_core,
    )


def make_plugin_dev_update_preview(
    query: str | None,
    *,
    all_plugins: bool,
    receipt: ToolReceipt | None,
) -> DevUpdatePreview:
    """Plan a dev update for one editable plugin or all editable plugins."""
    records = _runtime_records()
    plugin_records = tuple(
        record
        for record in records
        if record.role == "plugin" and record.install_type == "editable"
    )
    if all_plugins:
        if not plugin_records:
            return DevUpdatePreview(
                plan=None,
                subject="editable plugins",
                error="No editable plugins are installed.",
            )
        return _plan(
            plugin_records,
            records=records,
            receipt=receipt,
            subject="editable plugins",
        )

    if not query:
        return DevUpdatePreview(
            plan=None,
            subject="editable plugin",
            error="No editable plugin selected.",
        )
    target = _find_plugin_record(plugin_records, query)
    if target is None:
        return DevUpdatePreview(
            plan=None,
            subject=query,
            error=f"{query} is not an editable plugin in the runtime inventory.",
        )
    return _plan((target,), records=records, receipt=receipt, subject=query)


def execute_tui_dev_update(
    plan: DevUpdatePlan, *, run: DevCommandRunner | None = None
) -> DevUpdateResult:
    """Execute a dev-update plan with the default subprocess runner."""
    runner = run if run is not None else run_dev_update_command
    return execute_dev_update(plan, run=runner)


def entry_uses_dev_update(entry: PluginCatalogEntry) -> bool:
    """Whether a catalog entry should use the editable dev-update path."""
    return entry.installed.installed and (
        entry.latest.source == "editable" or entry.latest.install_type == "editable"
    )


def dev_update_blocking_reason(plan: DevUpdatePlan) -> str | None:
    """Return the reason a plan must not be executed, if any."""
    if not plan.actionable_roots and not plan.reconcile_steps:
        return _dev_update_skipped_message(plan)
    for step in plan.reconcile_steps:
        if not step.available:
            return step.reason or f"{step.label} unavailable"
    return None


def _dev_update_skipped_message(plan: DevUpdatePlan) -> str:
    """Compact skipped-package explanation for a non-actionable plan."""
    skipped = plan.skipped
    if not skipped:
        return "No editable checkout updates are available."
    if len(skipped) == 1:
        package = skipped[0]
        return f"{package.record.name}: {package.reason}"
    first = skipped[0]
    return f"{len(skipped)} editable checkouts skipped; {first.record.name}: {first.reason}"


def dev_update_preview_summary(plan: DevUpdatePlan, *, subject: str) -> str:
    """Summary line for the dev-update confirm-preview modal."""
    root_count = len(plan.actionable_roots)
    package_count = len(plan.actionable)
    step_count = len(plan.reconcile_steps)
    parts = [
        f"Updates {package_count} editable {_plural(package_count, 'package')}",
        f"across {root_count} {_plural(root_count, 'checkout')}",
    ]
    if step_count:
        parts.append(f"then runs {step_count} reconcile {_plural(step_count, 'step')}")
    if plan.skipped:
        parts.append(f"skips {len(plan.skipped)} unsafe/current")
    return f"{subject}: " + "; ".join(parts)


def dev_update_preview_details(plan: DevUpdatePlan) -> tuple[str, ...]:
    """Short operation lines for the dev-update confirm-preview modal."""
    lines: list[str] = []
    for root in plan.actionable_roots:
        ref = root.upstream or "upstream"
        lines.append(f"fetch + fast-forward {ref} in {_short_root(root.git_root)}")
    for step in plan.reconcile_steps:
        if step.available:
            detail = " ".join(step.command)
            if step.repair_command:
                detail = f"{detail} (fallback: {' '.join(step.repair_command)})"
            lines.append(f"{step.label}: {detail}")
        else:
            lines.append(f"{step.label}: unavailable ({step.reason or 'no command'})")
    for package in plan.skipped[:4]:
        lines.append(f"skip {package.record.name}: {package.reason}")
    if len(plan.skipped) > 4:
        lines.append(f"skip {len(plan.skipped) - 4} more editable checkouts")
    return tuple(lines)


def dev_update_success_message(
    result: DevUpdateResult, *, subject: str, elapsed: float
) -> str:
    """Concise toast for a successful dev update."""
    if not result.changed:
        return "Editable checkouts already up to date."
    updated = tuple(
        outcome for outcome in result.outcomes if outcome.status == "updated"
    )
    count = len(updated)
    if count <= 1:
        return f"Updated {subject} dev checkout in {humanize_duration(elapsed)}"
    return (
        f"Updated {count} editable {_plural(count, 'checkout')} "
        f"in {humanize_duration(elapsed)}"
    )


def dev_update_failure_message(result: DevUpdateResult) -> str:
    """Return the primary failure reason from a dev-update execution result."""
    for outcome in result.outcomes:
        if outcome.status == "failed":
            return outcome.reason
    return "dev update failed"


def dev_update_failed(result: DevUpdateResult) -> bool:
    """Whether execution has any failed package outcome."""
    return any(outcome.status == "failed" for outcome in result.outcomes)


def _runtime_records() -> tuple[VersionPackageRecord, ...]:
    return collect_runtime_version_inventory(include_plugins=True).packages


def _plan(
    targets: tuple[VersionPackageRecord, ...],
    *,
    records: tuple[VersionPackageRecord, ...],
    receipt: ToolReceipt | None,
    subject: str,
    already_refreshed_roots: Collection[str] = (),
    host_record: VersionPackageRecord | None = None,
    managed_argv: tuple[str, ...] = (),
    managed_packages: tuple[PlannedPackage, ...] = (),
    stale_core_record: VersionPackageRecord | None = None,
) -> DevUpdatePreview:
    host = host_record or _host_record(records)
    if host is None:
        return DevUpdatePreview(
            plan=None,
            subject=subject,
            error="Runtime inventory is missing the host `sase` package.",
        )
    try:
        plan = plan_dev_update(
            targets,
            host_record=host,
            receipt=receipt,
            already_refreshed_roots=already_refreshed_roots,
            stale_core_record=stale_core_record,
        )
    except Exception as exc:  # noqa: BLE001 - update planning should toast clearly.
        return DevUpdatePreview(plan=None, subject=subject, error=str(exc))
    return DevUpdatePreview(
        plan=plan,
        subject=subject,
        managed_argv=managed_argv,
        managed_packages=managed_packages,
    )


def _host_record(
    records: tuple[VersionPackageRecord, ...],
) -> VersionPackageRecord | None:
    for record in records:
        if record.role == "host" or normalize_distribution_name(record.name) == "sase":
            return record
    return None


def _stale_core_record(
    records: tuple[VersionPackageRecord, ...],
    host: VersionPackageRecord | None,
) -> VersionPackageRecord | None:
    """Find a wheel-installed core in a dev (editable-host) install."""
    if host is None or host.install_type != "editable":
        return None
    for record in records:
        if record.role == "core" and record.install_type == "wheel":
            return record
    return None


def _find_plugin_record(
    records: tuple[VersionPackageRecord, ...], query: str
) -> VersionPackageRecord | None:
    key = normalize_distribution_name(query)
    for record in records:
        if key in _record_keys(record):
            return record
    return None


def _record_keys(record: VersionPackageRecord) -> set[str]:
    keys = {normalize_distribution_name(record.name)}
    if record.name.startswith("sase-"):
        keys.add(normalize_distribution_name(record.name.removeprefix("sase-")))
    for signal in record.plugin_signals:
        keys.add(normalize_distribution_name(signal))
        if signal.startswith("sase-"):
            keys.add(normalize_distribution_name(signal.removeprefix("sase-")))
    keys.discard("")
    return keys


def _short_root(root: str) -> str:
    name = Path(root).name
    return name or root


def _plural(count: int, singular: str) -> str:
    if count == 1:
        return singular
    if singular.endswith("y"):
        return f"{singular[:-1]}ies"
    return f"{singular}s"


__all__ = [
    "DevUpdatePreview",
    "dev_update_blocking_reason",
    "dev_update_failed",
    "dev_update_failure_message",
    "dev_update_preview_details",
    "dev_update_preview_summary",
    "dev_update_success_message",
    "entry_uses_dev_update",
    "execute_tui_dev_update",
    "make_plugin_dev_update_preview",
    "make_sase_dev_update_preview",
]

"""Handler for the top-level ``sase update`` command.

Managed installs still use ``uv tool upgrade sase``. Editable uv-tool installs
route matching editable package records through the dev-update backend: safe git
fast-forwards first, then uv-tool/Rust reconciliation. Every impure dependency
(install probing, runtime inventory, git/subprocess execution, uv, axe restart,
version lookup, and the clock) is injectable so the command remains unit-testable
without a real uv install or daemon.
"""

from __future__ import annotations

import argparse
import importlib.metadata as importlib_metadata
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.axe.process import (
    AxeStartResult,
    is_axe_running,
    restart_axe_daemon_result,
)
from sase.dev_update import (
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
    execute_dev_update,
    plan_dev_update,
    run_dev_update_command,
)
from sase.dev_update.models import DevCommandRunner
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.receipt import Requirement, ToolReceipt, load_receipt
from sase.uv_tool.render import (
    PackageRole,
    PlannedPackage,
    UpdateOutcome,
    UpdateSummary,
    render_update_dry_run,
    render_update_result,
    render_uv_tool_error,
    summarize_update,
)
from sase.uv_tool.runner import UvChangeSet, run_uv
from sase.version._utils import normalize_distribution_name
from sase.version.inventory import (
    RuntimeVersionInventory,
    VersionPackageRecord,
    collect_runtime_version_inventory,
)

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
UPDATE_JSON_SCHEMA_VERSION = 2

ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]
RunUvFn = Callable[[list[str]], UvChangeSet]
VersionFn = Callable[[str], str | None]
ClockFn = Callable[[], float]
InventoryFn = Callable[[], RuntimeVersionInventory]
AxeRunningFn = Callable[[], bool]
RestartAxeFn = Callable[[], AxeStartResult]
RestartStatus = Literal[
    "skipped_no_change",
    "skipped_not_running",
    "restarted",
    "failed",
]


class _PlanDevFn(Protocol):
    def __call__(
        self,
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        *,
        host_record: VersionPackageRecord,
        receipt: ToolReceipt | None = None,
    ) -> DevUpdatePlan: ...


class _ExecuteDevFn(Protocol):
    def __call__(
        self, plan: DevUpdatePlan, *, run: DevCommandRunner
    ) -> DevUpdateResult: ...


@dataclass(frozen=True)
class _RestartInfo:
    """Axe restart outcome after a changed successful update."""

    attempted: bool
    status: RestartStatus
    pid: int | None = None
    message: str = ""
    reason: str | None = None


@dataclass(frozen=True)
class _DevRoute:
    """Editable package records selected for the dev-update backend."""

    records: tuple[VersionPackageRecord, ...]
    host_record: VersionPackageRecord
    managed_requirements: tuple[Requirement, ...]


def _installed_version(name: str) -> str | None:
    """Return the installed version of distribution *name*, or ``None``."""
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 — version display must never crash the run.
        return None


def handle_update_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    probe_fn: ProbeFn = probe_uv_tool_install,
    run_fn: RunUvFn = run_uv,
    inventory_fn: InventoryFn = collect_runtime_version_inventory,
    plan_dev_update_fn: _PlanDevFn = plan_dev_update,
    execute_dev_update_fn: _ExecuteDevFn = execute_dev_update,
    run_dev_update_fn: DevCommandRunner = run_dev_update_command,
    axe_running_fn: AxeRunningFn = is_axe_running,
    restart_axe_fn: RestartAxeFn = restart_axe_daemon_result,
    version_fn: VersionFn = _installed_version,
    clock: ClockFn = time.monotonic,
) -> int:
    """Run ``sase update``; return the process exit code."""
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    quiet = bool(getattr(args, "quiet", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return _fail(NotAUvToolInstallError(install), as_json=as_json, err=err)

    if dry_run:
        return _handle_dry_run(
            install,
            as_json=as_json,
            out=out,
            err=err,
            version_fn=version_fn,
            inventory_fn=inventory_fn,
            plan_dev_update_fn=plan_dev_update_fn,
        )

    return _handle_live_update(
        install,
        as_json=as_json,
        quiet=quiet,
        out=out,
        err=err,
        run_fn=run_fn,
        inventory_fn=inventory_fn,
        plan_dev_update_fn=plan_dev_update_fn,
        execute_dev_update_fn=execute_dev_update_fn,
        run_dev_update_fn=run_dev_update_fn,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
        version_fn=version_fn,
        clock=clock,
    )


def _handle_live_update(
    install: UvToolInstall,
    *,
    as_json: bool,
    quiet: bool,
    out: Console,
    err: Console,
    run_fn: RunUvFn,
    inventory_fn: InventoryFn,
    plan_dev_update_fn: _PlanDevFn,
    execute_dev_update_fn: _ExecuteDevFn,
    run_dev_update_fn: DevCommandRunner,
    axe_running_fn: AxeRunningFn,
    restart_axe_fn: RestartAxeFn,
    version_fn: VersionFn,
    clock: ClockFn,
) -> int:
    receipt = _try_load_receipt(install)
    route = _dev_route(receipt, inventory_fn)
    if isinstance(route, UvToolError):
        return _fail(route, as_json=as_json, err=err)

    has_dev = route is not None and bool(route.records)
    has_managed = _should_run_managed_update(receipt, route)
    mode = _update_mode(has_dev=has_dev, has_managed=has_managed)
    argv = build_upgrade_all(color="never") if has_managed else []

    start = clock()
    dev_plan: DevUpdatePlan | None = None
    dev_result: DevUpdateResult | None = None

    if route is not None and route.records:
        try:
            dev_plan = plan_dev_update_fn(
                route.records, host_record=route.host_record, receipt=receipt
            )
        except Exception as exc:  # noqa: BLE001 - surface planning failures cleanly.
            return _fail(
                UvToolError(f"could not plan editable checkout update: {exc}"),
                as_json=as_json,
                err=err,
            )
        dev_result = execute_dev_update_fn(dev_plan, run=run_dev_update_fn)
        if not _dev_update_succeeded(dev_result):
            elapsed = max(0.0, clock() - start)
            if as_json:
                print(
                    json.dumps(
                        _combined_result_json(
                            mode=mode,
                            managed_argv=argv,
                            managed_summary=None,
                            dev_plan=dev_plan,
                            dev_result=dev_result,
                            elapsed=elapsed,
                            restart=_restart_skipped(changed=False),
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                _render_dev_update_result(
                    dev_result,
                    elapsed=elapsed,
                    quiet=quiet,
                    console=err,
                    failed=True,
                )
            return 1

    managed_summary: UpdateSummary | None = None
    if has_managed:
        use_spinner = not as_json and not quiet and out.is_terminal
        try:
            if use_spinner:
                with out.status(
                    "Upgrading sase and its plugins via uv…", spinner="dots"
                ):
                    change_set = run_fn(argv)
            else:
                change_set = run_fn(argv)
        except UvToolError as exc:
            return _fail(exc, as_json=as_json, err=err)
        managed_summary = summarize_update(
            change_set, _managed_summary_receipt(receipt), current_version=version_fn
        )

    elapsed = max(0.0, clock() - start)
    changed = _combined_changed(dev_result, managed_summary)
    restart = _restart_after_update(
        changed=changed,
        axe_running_fn=axe_running_fn,
        restart_axe_fn=restart_axe_fn,
    )

    if as_json:
        print(
            json.dumps(
                _combined_result_json(
                    mode=mode,
                    managed_argv=argv,
                    managed_summary=managed_summary,
                    dev_plan=dev_plan,
                    dev_result=dev_result,
                    elapsed=elapsed,
                    restart=restart,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if dev_result is not None:
        _render_dev_update_result(
            dev_result, elapsed=elapsed, quiet=quiet, console=out, failed=False
        )
    if managed_summary is not None:
        render_update_result(managed_summary, elapsed=elapsed, quiet=quiet, console=out)
    if changed:
        _render_restart_info(restart, console=out, quiet=quiet)
    return 0


def _handle_dry_run(
    install: UvToolInstall,
    *,
    as_json: bool,
    out: Console,
    err: Console,
    version_fn: VersionFn,
    inventory_fn: InventoryFn,
    plan_dev_update_fn: _PlanDevFn,
) -> int:
    try:
        receipt = load_receipt(install.receipt_path)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    route = _dev_route(receipt, inventory_fn)
    if isinstance(route, UvToolError):
        return _fail(route, as_json=as_json, err=err)

    has_dev = route is not None and bool(route.records)
    has_managed = _should_run_managed_update(receipt, route)
    mode = _update_mode(has_dev=has_dev, has_managed=has_managed)
    argv = build_upgrade_all(color="never") if has_managed else []
    packages = (
        _planned_packages(receipt, version_fn)
        if mode == "managed"
        else _planned_packages_for_requirements(
            route.managed_requirements if route is not None else (),
            receipt=receipt,
            version_fn=version_fn,
        )
    )

    dev_plan: DevUpdatePlan | None = None
    if route is not None and route.records:
        try:
            dev_plan = plan_dev_update_fn(
                route.records, host_record=route.host_record, receipt=receipt
            )
        except Exception as exc:  # noqa: BLE001 - dry-run should fail legibly.
            return _fail(
                UvToolError(f"could not plan editable checkout update: {exc}"),
                as_json=as_json,
                err=err,
            )

    if as_json:
        print(
            json.dumps(
                _dry_run_json(argv, packages, mode=mode, dev_plan=dev_plan),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if dev_plan is None:
        render_update_dry_run(argv, packages, console=out)
    else:
        _render_dev_update_dry_run(
            dev_plan, managed_argv=argv, managed_packages=packages, console=out
        )
    return 0


def _fail(error: UvToolError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_JSON_SCHEMA_VERSION,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        render_uv_tool_error(str(error), console=err)
    return 1


def _try_load_receipt(install: UvToolInstall) -> ToolReceipt | None:
    """Load the receipt for the package set, tolerating a parse failure.

    The upgrade has already succeeded by this point; a malformed receipt should
    only degrade the pretty "already current" cross-reference, never fail the
    command.
    """
    try:
        return load_receipt(install.receipt_path)
    except ReceiptError:
        return None


def _dev_route(
    receipt: ToolReceipt | None, inventory_fn: InventoryFn
) -> _DevRoute | UvToolError | None:
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

    return _DevRoute(
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


def _should_run_managed_update(
    receipt: ToolReceipt | None, route: _DevRoute | UvToolError | None
) -> bool:
    if receipt is None:
        return True
    if route is None or isinstance(route, UvToolError):
        return True
    return bool(route.managed_requirements)


def _update_mode(*, has_dev: bool, has_managed: bool) -> str:
    if has_dev and has_managed:
        return "mixed"
    if has_dev:
        return "dev"
    return "managed"


def _managed_summary_receipt(receipt: ToolReceipt | None) -> ToolReceipt | None:
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


def _planned_packages(
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


def _planned_packages_for_requirements(
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


def _dev_update_succeeded(result: DevUpdateResult) -> bool:
    return all(outcome.status != "failed" for outcome in result.outcomes)


def _combined_changed(
    dev_result: DevUpdateResult | None, managed_summary: UpdateSummary | None
) -> bool:
    return bool(
        (dev_result is not None and dev_result.changed)
        or (managed_summary is not None and managed_summary.changed)
    )


def _restart_skipped(*, changed: bool) -> _RestartInfo:
    if changed:
        return _RestartInfo(
            attempted=False,
            status="skipped_not_running",
            reason="axe is not running",
        )
    return _RestartInfo(
        attempted=False,
        status="skipped_no_change",
        reason="no code changed",
    )


def _restart_after_update(
    *,
    changed: bool,
    axe_running_fn: AxeRunningFn,
    restart_axe_fn: RestartAxeFn,
) -> _RestartInfo:
    if not changed:
        return _restart_skipped(changed=False)
    try:
        axe_running = axe_running_fn()
    except Exception as exc:  # noqa: BLE001 - update succeeded; report restart only.
        return _RestartInfo(
            attempted=False,
            status="failed",
            message=f"could not check axe status: {exc}",
        )
    if not axe_running:
        return _restart_skipped(changed=True)

    try:
        result = restart_axe_fn()
    except Exception as exc:  # noqa: BLE001 - keep update success separate.
        return _RestartInfo(
            attempted=True,
            status="failed",
            message=f"axe restart failed: {exc}",
        )
    if result.pid is not None:
        return _RestartInfo(
            attempted=True,
            status="restarted",
            pid=result.pid,
            message=f"Axe restarted (pid {result.pid})",
        )
    return _RestartInfo(
        attempted=True,
        status="failed",
        message=result.message or "Failed to restart axe",
    )


def _render_restart_info(
    restart: _RestartInfo, *, console: Console, quiet: bool
) -> None:
    if restart.status in ("skipped_no_change", "skipped_not_running"):
        return
    text = Text()
    if restart.status == "restarted":
        text.append("↻ ", style="green")
        text.append(restart.message, style="green")
        text.append(" to load the updated code.", style="dim")
    else:
        text.append("⚠ ", style="yellow")
        text.append(restart.message or "Axe restart failed.", style="yellow")
    console.print(
        text if quiet else Panel(text, title="Axe Restart", border_style="cyan")
    )


def _render_dev_update_dry_run(
    plan: DevUpdatePlan,
    *,
    managed_argv: list[str],
    managed_packages: tuple[PlannedPackage, ...],
    console: Console,
) -> None:
    body: list[RenderableType] = []
    if plan.packages:
        body.append(_dev_plan_table(plan.packages))
    else:
        body.append(Text("No editable packages found.", style="dim"))

    if plan.roots:
        body.append(Text(""))
        body.append(_dev_roots_table(plan.roots))

    if plan.reconcile_steps:
        body.append(Text(""))
        body.append(_dev_reconcile_table(plan.reconcile_steps))

    if managed_argv:
        body.append(Text(""))
        command = Text()
        command.append("Would also run  ", style="dim")
        command.append(" ".join(managed_argv), style="cyan")
        body.append(command)
        if managed_packages:
            body.append(_planned_table_for_dev_panel(managed_packages))

    body.append(Text(""))
    note = Text()
    note.append("Dry run — nothing was changed. Re-run as ", style="dim")
    note.append("sase update", style="cyan")
    note.append(" to update.", style="dim")
    body.append(note)
    console.print(
        Panel(Group(*body), title="SASE Update (dry run)", border_style="cyan")
    )


def _render_dev_update_result(
    result: DevUpdateResult,
    *,
    elapsed: float,
    quiet: bool,
    console: Console,
    failed: bool,
) -> None:
    if quiet:
        console.print(_dev_quiet_line(result, elapsed, failed=failed))
        return

    body: list[RenderableType] = [_dev_outcomes_table(result.outcomes)]
    reconcile = tuple(
        cmd for cmd in result.commands if not cmd.label.startswith("git ")
    )
    if reconcile:
        body.append(Text(""))
        body.append(_dev_executed_commands_table(reconcile))
    body.append(Text(""))
    body.append(_dev_summary_line(result, elapsed, failed=failed))
    console.print(
        Panel(
            Group(*body),
            title="SASE Dev Update",
            border_style="red" if failed else "cyan",
        )
    )


def _dev_plan_table(packages: tuple[DevUpdatePackagePlan, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold", no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for package in packages:
        table.add_row(
            _dev_plan_glyph(package),
            Text(package.record.name),
            _dev_plan_version_cell(package),
            Text(package.reason, style="dim"),
        )
    return table


def _dev_roots_table(roots: tuple[DevUpdateRootPlan, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="dim")
    table.add_column()
    for root in roots:
        label = "fetch + fast-forward" if root.status == "actionable" else "skip"
        table.add_row(Text("git", style="cyan"), Text(root.git_root), Text(label))
    return table


def _dev_reconcile_table(steps: tuple[DevReconcileStep, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold")
    table.add_column()
    for step in steps:
        command = (
            " ".join(step.command) if step.command else step.reason or "unavailable"
        )
        table.add_row(Text("reconcile", style="cyan"), Text(step.label), Text(command))
    return table


def _planned_table_for_dev_panel(packages: tuple[PlannedPackage, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for package in packages:
        table.add_row(
            Text(package.name),
            Text(package.current_version or "—", style="dim"),
            Text(package.role, style="dim"),
        )
    return table


def _dev_outcomes_table(outcomes: tuple[DevUpdateOutcome, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold", no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for outcome in outcomes:
        table.add_row(
            _dev_outcome_glyph(outcome),
            Text(outcome.record.name),
            _dev_outcome_version_cell(outcome),
            Text(outcome.reason, style="red" if outcome.status == "failed" else "dim"),
        )
    return table


def _dev_executed_commands_table(commands: tuple[Any, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold")
    table.add_column()
    for command in commands:
        rendered = " ".join(command.command)
        table.add_row(
            Text("ran" if command.returncode == 0 else "failed", style="cyan"),
            Text(command.label),
            Text(rendered, style="dim"),
        )
    return table


def _dev_plan_glyph(package: DevUpdatePackagePlan) -> Text:
    if package.status == "actionable":
        return Text("↑", style="green")
    return Text("·", style="dim")


def _dev_outcome_glyph(outcome: DevUpdateOutcome) -> Text:
    if outcome.status == "updated":
        return Text("✓", style="green")
    if outcome.status == "failed":
        return Text("✗", style="red")
    return Text("·", style="dim")


def _dev_plan_version_cell(package: DevUpdatePackagePlan) -> Text:
    return _transition_cell(package.current_version, package.latest_version)


def _dev_outcome_version_cell(outcome: DevUpdateOutcome) -> Text:
    return _transition_cell(outcome.old_version, outcome.new_version)


def _transition_cell(old: str | None, new: str | None) -> Text:
    cell = Text()
    cell.append(old or "—", style="dim")
    if new and new != old:
        cell.append(" → ", style="dim")
        cell.append(new, style="green")
    return cell


def _dev_summary_line(result: DevUpdateResult, elapsed: float, *, failed: bool) -> Text:
    counts = _dev_counts(result)
    updated = counts["updated"]
    skipped = counts["skipped"]
    failed_count = counts["failed"]
    line = Text()
    if failed:
        line.append("Dev update failed", style="red")
    elif updated:
        line.append("Updated ", style="green")
        line.append(
            f"{updated} editable {_plural(updated, 'package')}", style="bold green"
        )
    else:
        line.append("No editable checkouts updated", style="dim")
    line.append(f" in {_humanize_duration(elapsed)}", style="dim")
    if skipped:
        line.append(f" · {skipped} skipped", style="dim")
    if failed_count:
        line.append(f" · {failed_count} failed", style="red")
    return line


def _dev_quiet_line(result: DevUpdateResult, elapsed: float, *, failed: bool) -> Text:
    return _dev_summary_line(result, elapsed, failed=failed)


def _outcome_json(outcome: UpdateOutcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "role": outcome.role,
        "kind": outcome.kind.value,
        "old_version": outcome.old_version,
        "new_version": outcome.new_version,
    }


def _dry_run_json(
    argv: list[str],
    packages: tuple[PlannedPackage, ...],
    *,
    mode: str = "managed",
    dev_plan: DevUpdatePlan | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": True,
        "mode": mode,
        "command": list(argv),
        "packages": [
            {
                "name": package.name,
                "role": package.role,
                "current_version": package.current_version,
            }
            for package in packages
        ],
        "managed": {
            "command": list(argv),
            "packages": [
                {
                    "name": package.name,
                    "role": package.role,
                    "current_version": package.current_version,
                }
                for package in packages
            ],
        }
        if argv
        else None,
        "dev": _dev_plan_json(dev_plan) if dev_plan is not None else None,
    }


def _combined_result_json(
    *,
    mode: str,
    managed_argv: list[str],
    managed_summary: UpdateSummary | None,
    dev_plan: DevUpdatePlan | None,
    dev_result: DevUpdateResult | None,
    elapsed: float,
    restart: _RestartInfo,
) -> dict[str, Any]:
    changed = _combined_changed(dev_result, managed_summary)
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "mode": mode,
        "command": list(managed_argv),
        "changed": changed,
        "elapsed_seconds": round(elapsed, 3),
        "counts": _combined_counts(dev_result, managed_summary),
        "packages": _combined_package_json(dev_result, managed_summary),
        "managed": _managed_result_json(managed_argv, managed_summary)
        if managed_summary is not None
        else None,
        "dev": _dev_result_json(dev_plan, dev_result)
        if dev_result is not None or dev_plan is not None
        else None,
        "restart": _restart_json(restart),
    }


def _managed_result_json(
    argv: list[str], summary: UpdateSummary | None
) -> dict[str, Any]:
    if summary is None:
        return {"command": list(argv), "changed": False, "packages": []}
    return {
        "command": list(argv),
        "changed": summary.changed,
        "counts": {
            "updated": len(summary.updated),
            "already_current": len(summary.already_current),
            "removed": len(summary.removed),
        },
        "packages": [_outcome_json(outcome) for outcome in summary.outcomes],
    }


def _dev_plan_json(plan: DevUpdatePlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "packages": [_dev_package_plan_json(package) for package in plan.packages],
        "roots": [_dev_root_plan_json(root) for root in plan.roots],
        "reconcile_steps": [
            _dev_reconcile_step_json(step) for step in plan.reconcile_steps
        ],
    }


def _dev_result_json(
    plan: DevUpdatePlan | None, result: DevUpdateResult | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if plan is not None:
        payload["plan"] = _dev_plan_json(plan)
    if result is not None:
        payload.update(
            {
                "changed": result.changed,
                "counts": _dev_counts(result),
                "packages": [_dev_outcome_json(outcome) for outcome in result.outcomes],
                "commands": [_dev_command_json(command) for command in result.commands],
            }
        )
    return payload


def _dev_package_plan_json(package: DevUpdatePackagePlan) -> dict[str, Any]:
    return {
        "name": package.record.name,
        "role": package.record.role,
        "status": package.status,
        "reason": package.reason,
        "current_version": package.current_version,
        "latest_version": package.latest_version,
        "git_root": package.git_root,
        "upstream": package.upstream,
        "ahead": package.ahead,
        "behind": package.behind,
    }


def _dev_root_plan_json(root: DevUpdateRootPlan) -> dict[str, Any]:
    return {
        "git_root": root.git_root,
        "status": root.status,
        "reason": root.reason,
        "upstream": root.upstream,
        "remote": root.remote,
        "remote_branch": root.remote_branch,
        "packages": list(root.packages),
        "ahead": root.ahead,
        "behind": root.behind,
    }


def _dev_reconcile_step_json(step: DevReconcileStep) -> dict[str, Any]:
    return {
        "kind": step.kind,
        "label": step.label,
        "command": list(step.command),
        "cwd": step.cwd,
        "available": step.available,
        "reason": step.reason,
    }


def _dev_outcome_json(outcome: DevUpdateOutcome) -> dict[str, Any]:
    return {
        "name": outcome.record.name,
        "role": outcome.record.role,
        "status": outcome.status,
        "reason": outcome.reason,
        "old_version": outcome.old_version,
        "new_version": outcome.new_version,
        "git_root": outcome.git_root,
    }


def _dev_command_json(command: Any) -> dict[str, Any]:
    return {
        "label": command.label,
        "command": list(command.command),
        "cwd": command.cwd,
        "returncode": command.returncode,
        "stdout": command.stdout,
        "stderr": command.stderr,
    }


def _combined_counts(
    dev_result: DevUpdateResult | None, managed_summary: UpdateSummary | None
) -> dict[str, int]:
    managed_updated = len(managed_summary.updated) if managed_summary else 0
    managed_current = len(managed_summary.already_current) if managed_summary else 0
    managed_removed = len(managed_summary.removed) if managed_summary else 0
    if dev_result is None:
        return {
            "updated": managed_updated,
            "already_current": managed_current,
            "removed": managed_removed,
        }
    dev_counts = _dev_counts(dev_result) if dev_result else {}
    return {
        "updated": managed_updated + int(dev_counts.get("updated", 0)),
        "already_current": managed_current,
        "removed": managed_removed,
        "skipped": int(dev_counts.get("skipped", 0)),
        "failed": int(dev_counts.get("failed", 0)),
    }


def _combined_package_json(
    dev_result: DevUpdateResult | None, managed_summary: UpdateSummary | None
) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    if dev_result is not None:
        packages.extend(_dev_outcome_json(outcome) for outcome in dev_result.outcomes)
    if managed_summary is not None:
        packages.extend(_outcome_json(outcome) for outcome in managed_summary.outcomes)
    return packages


def _dev_counts(result: DevUpdateResult | None) -> dict[str, int]:
    if result is None:
        return {"updated": 0, "skipped": 0, "failed": 0}
    return {
        "updated": sum(1 for outcome in result.outcomes if outcome.status == "updated"),
        "skipped": sum(1 for outcome in result.outcomes if outcome.status == "skipped"),
        "failed": sum(1 for outcome in result.outcomes if outcome.status == "failed"),
    }


def _restart_json(restart: _RestartInfo) -> dict[str, Any]:
    return {
        "attempted": restart.attempted,
        "status": restart.status,
        "pid": restart.pid,
        "message": restart.message,
        "reason": restart.reason,
    }


def _plural(count: int, singular: str) -> str:
    if count == 1:
        return singular
    if singular.endswith("y"):
        return f"{singular[:-1]}ies"
    return f"{singular}s"


def _humanize_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m{rest:02d}s"


__all__ = [
    "UPDATE_JSON_SCHEMA_VERSION",
    "handle_update_command",
]

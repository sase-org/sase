"""Summary helpers for SASE self-updates in the Config Center."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import time
from typing import Any

from sase.ace.tui.task_subprocess import TaskReporter
from sase.main.update_types import CombinedUpdateResult
from sase.dev_update.timings import slowest_reconcile_command
from sase.plugins.render_common import humanize_duration
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import ReceiptError
from sase.uv_tool.receipt import ToolReceipt, load_receipt
from sase.uv_tool.render import (
    PlannedPackage,
    UpdateSummary,
    summarize_planned_update,
    summarize_update,
)
from sase.uv_tool.runner import ChangeKind, run_uv
from sase.version._utils import normalize_distribution_name

from .plugins_browser_dev_update import dev_update_success_message

_CORE_DIST_KEYS = {
    normalize_distribution_name("sase"),
    normalize_distribution_name("sase-core-rs"),
}
SASE_UPDATE_NOOP_MESSAGE = "Nothing to update: sase, core, and plugins are current."


def installed_version(name: str) -> str | None:
    """Return the installed version of distribution *name*, or ``None``."""
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - version display must never fail the task.
        return None


def load_receipt_for_summary(install: object | None) -> ToolReceipt | None:
    """Load the uv-tool receipt when available, tolerating parse failures."""
    if not isinstance(install, UvToolInstall):
        return None
    try:
        return load_receipt(install.receipt_path)
    except ReceiptError:
        return None


def run_sase_update_summary(
    install: object | None, *, run_fn: Any = run_uv
) -> tuple[UpdateSummary, float]:
    """Run ``uv tool upgrade sase`` and summarize the changed package set."""
    argv = build_upgrade_all(color="never")
    start = time.monotonic()
    change_set = run_fn(argv)
    elapsed = max(0.0, time.monotonic() - start)
    return (
        summarize_update(
            change_set,
            load_receipt_for_summary(install),
            current_version=installed_version,
        ),
        elapsed,
    )


def run_planned_sase_update_summary(
    argv: tuple[str, ...],
    packages: tuple[PlannedPackage, ...],
    *,
    run_fn: Any = run_uv,
) -> tuple[UpdateSummary, float]:
    """Run and summarize an explicit managed leg from a combined preview."""
    start = time.monotonic()
    change_set = run_fn(list(argv))
    elapsed = max(0.0, time.monotonic() - start)
    return summarize_planned_update(change_set, packages), elapsed


def sase_update_success_message(summary: UpdateSummary, elapsed: float) -> str:
    """Concise toast for a successful ``sase update`` run."""
    if not summary.changed:
        return "Already up to date."

    core_updated = any(
        outcome.is_update
        and normalize_distribution_name(outcome.name) in _CORE_DIST_KEYS
        for outcome in summary.outcomes
    )
    plugin_count = len(summary.updated_plugins)
    dependency_count = sum(
        1
        for outcome in summary.updated_dependencies
        if normalize_distribution_name(outcome.name) not in _CORE_DIST_KEYS
    )

    subjects: list[str] = []
    if core_updated:
        subjects.append("sase")
    if plugin_count:
        subjects.append(f"{plugin_count} {plural(plugin_count, 'plugin')}")
    if not subjects and dependency_count:
        subjects.append(f"{dependency_count} {plural(dependency_count, 'dependency')}")
    if not subjects:
        subjects.append("packages")

    return f"Updated {' + '.join(subjects)} in {humanize_duration(elapsed)}"


def managed_update_changed(outcome: Any) -> bool:
    """Whether a managed update result changed any installed package."""
    changed = getattr(outcome, "changed", None)
    if isinstance(changed, bool):
        return changed
    change_set = getattr(outcome, "change_set", None)
    changes = getattr(change_set, "changes", ())
    return any(
        getattr(change, "kind", None) is not ChangeKind.UNCHANGED for change in changes
    )


def combined_sase_update_success_message(result: CombinedUpdateResult) -> str:
    """Concise success message for a comprehensive mixed update."""
    if not result.changed:
        return "Already up to date."
    if result.managed_summary is None or not result.managed_summary.changed:
        assert result.dev_result is not None
        return dev_update_success_message(
            result.dev_result,
            subject="sase",
            elapsed=result.elapsed,
        )
    if result.dev_result is None or not result.dev_result.changed:
        return sase_update_success_message(result.managed_summary, result.elapsed)

    dev_count = sum(
        1 for outcome in result.dev_result.outcomes if outcome.status == "updated"
    )
    managed_message = sase_update_success_message(
        result.managed_summary, result.elapsed
    ).removeprefix("Updated ")
    managed_subject = managed_message.rsplit(" in ", maxsplit=1)[0]
    return (
        f"Updated {dev_count} editable {plural(dev_count, 'checkout')} + "
        f"{managed_subject} in {humanize_duration(result.elapsed)}"
    )


def plural(count: int, singular: str) -> str:
    """Return a simple count-sensitive form of *singular*."""
    if count == 1:
        return singular
    if singular.endswith("y"):
        return f"{singular[:-1]}ies"
    return f"{singular}s"


def log_update_summary(
    reporter: TaskReporter, summary: UpdateSummary, message: str
) -> None:
    """Write a managed-update result to a tracked task reporter."""
    reporter.section("Summary")
    reporter.log(message, stream="result")
    for outcome in summary.outcomes:
        old = getattr(outcome, "old_version", None)
        new = getattr(outcome, "new_version", None)
        name = getattr(outcome, "name", "package")
        if old and new:
            reporter.log(f"{name}: {old} -> {new}", stream="result")
        elif new:
            reporter.log(f"{name}: installed {new}", stream="result")
        elif old:
            reporter.log(f"{name}: removed {old}", stream="result")


def log_combined_update_result(
    reporter: TaskReporter,
    result: CombinedUpdateResult,
    message: str,
) -> None:
    """Write a combined dev/managed result to a tracked task reporter."""
    reporter.section("Summary")
    reporter.log(message, stream="result")
    if result.dev_result is not None:
        for outcome in result.dev_result.outcomes:
            if outcome.status != "updated":
                continue
            reporter.log(
                f"{outcome.record.name}: {outcome.old_version} -> "
                f"{outcome.new_version}",
                stream="result",
            )
        if slowest := slowest_reconcile_command(result.dev_result.commands):
            reporter.log(
                f"slowest: {slowest.label} "
                f"({humanize_duration(slowest.duration_seconds)})",
                stream="result",
            )
    if result.managed_summary is not None:
        for managed_outcome in result.managed_summary.updated:
            reporter.log(
                f"{managed_outcome.name}: {managed_outcome.old_version} -> "
                f"{managed_outcome.new_version}",
                stream="result",
            )

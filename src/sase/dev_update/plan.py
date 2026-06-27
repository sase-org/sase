"""Plan safe editable-install dev updates."""

from __future__ import annotations

import subprocess
from collections import OrderedDict
from pathlib import Path

from sase.dev_update.models import (
    DevPackagePlanStatus,
    DevReconcileStep,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateRootPlan,
)
from sase.version._display import derive_display_version
from sase.version._git import (
    GitUpstreamStatus,
    classify_git_upstream,
    probe_git_metadata_at_ref,
)
from sase.version._models import VersionPackageRecord
from sase.uv_tool.commands import build_install
from sase.uv_tool.receipt import ToolReceipt


def plan_dev_update(
    records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
    *,
    host_record: VersionPackageRecord,
    receipt: ToolReceipt | None = None,
) -> DevUpdatePlan:
    """Plan a fast-forward-only dev update for editable package records."""
    packages: list[DevUpdatePackagePlan] = []
    by_root: OrderedDict[str, list[VersionPackageRecord]] = OrderedDict()
    root_statuses: OrderedDict[str, GitUpstreamStatus] = OrderedDict()

    for record in records:
        if record.install_type != "editable":
            packages.append(_skipped(record, "package is not an editable install"))
            continue
        if not record.source_root:
            packages.append(_skipped(record, "editable install has no source root"))
            continue
        try:
            status = classify_git_upstream(Path(record.source_root))
        except FileNotFoundError:
            packages.append(_skipped(record, "git is not available on PATH"))
            continue
        except OSError as exc:
            packages.append(_skipped(record, f"git could not be executed: {exc}"))
            continue
        except subprocess.TimeoutExpired:
            packages.append(
                _skipped(record, f"git probe timed out for {record.source_root}")
            )
            continue
        except subprocess.CalledProcessError as exc:
            packages.append(
                _skipped(
                    record,
                    f"git upstream state unavailable: {exc.stderr.strip() or exc}",
                )
            )
            continue

        by_root.setdefault(status.root, []).append(record)
        root_statuses.setdefault(status.root, status)

    root_plans: list[DevUpdateRootPlan] = []
    for root, root_records in by_root.items():
        status = root_statuses[root]
        root_status, reason = _classify_plan_status(status)
        root_plans.append(
            DevUpdateRootPlan(
                git_root=root,
                status=root_status,
                reason=reason,
                upstream=status.upstream,
                remote=status.remote,
                remote_branch=status.remote_branch,
                packages=tuple(record.name for record in root_records),
                ahead=status.ahead,
                behind=status.behind,
            )
        )
        for record in root_records:
            packages.append(_from_status(record, status, root_status, reason))

    reconcile_steps = _reconcile_steps(
        [pkg.record for pkg in packages if pkg.status == "actionable"],
        host_record=host_record,
        receipt=receipt,
    )
    return DevUpdatePlan(
        packages=tuple(packages),
        roots=tuple(root_plans),
        reconcile_steps=reconcile_steps,
    )


def _classify_plan_status(
    status: GitUpstreamStatus,
) -> tuple[DevPackagePlanStatus, str]:
    if status.detached:
        return "skipped", "checkout is detached"
    if not status.has_upstream:
        return "skipped", "checkout has no upstream"
    if status.dirty:
        return "skipped", "checkout has local changes"
    if status.diverged:
        return "skipped", "checkout has diverged from upstream"
    if status.strictly_behind:
        return "actionable", f"behind upstream by {status.behind} commit(s)"
    if status.up_to_date:
        return "skipped", "already current"
    if status.ahead and status.ahead > 0:
        return "skipped", "checkout is ahead of upstream"
    return "skipped", "upstream ancestry unavailable"


def _from_status(
    record: VersionPackageRecord,
    status: GitUpstreamStatus,
    plan_status: DevPackagePlanStatus,
    reason: str,
) -> DevUpdatePackagePlan:
    latest_version = _latest_version(record, status)
    return DevUpdatePackagePlan(
        record=record,
        status=plan_status,
        reason=reason,
        current_version=record.display_version,
        latest_version=latest_version,
        git_root=status.root,
        upstream=status.upstream,
        remote=status.remote,
        remote_branch=status.remote_branch,
        ahead=status.ahead,
        behind=status.behind,
    )


def _skipped(record: VersionPackageRecord, reason: str) -> DevUpdatePackagePlan:
    return DevUpdatePackagePlan(
        record=record,
        status="skipped",
        reason=reason,
        current_version=record.display_version,
        latest_version=None,
    )


def _latest_version(
    record: VersionPackageRecord, status: GitUpstreamStatus
) -> str | None:
    if status.upstream is None:
        return None
    result = probe_git_metadata_at_ref(Path(status.root), status.upstream)
    if result.metadata is None:
        return None
    return derive_display_version(
        record.source_version or record.distribution_version,
        result.metadata,
    )


def _reconcile_steps(
    actionable_records: list[VersionPackageRecord],
    *,
    host_record: VersionPackageRecord,
    receipt: ToolReceipt | None,
) -> tuple[DevReconcileStep, ...]:
    steps: list[DevReconcileStep] = []
    python_changed = any(record.role != "core" for record in actionable_records)
    core_changed = any(record.role == "core" for record in actionable_records)

    if python_changed:
        if receipt is None:
            steps.append(
                DevReconcileStep(
                    kind="uv_tool_install",
                    label="Reinstall uv-tool editable Python packages",
                    command=(),
                    reason="uv tool receipt unavailable",
                )
            )
        else:
            steps.append(
                DevReconcileStep(
                    kind="uv_tool_install",
                    label="Reinstall uv-tool editable Python packages",
                    command=tuple(build_install(receipt, color="never")),
                )
            )

    if core_changed:
        if host_record.source_root:
            steps.append(
                DevReconcileStep(
                    kind="rust_install_uv_tool",
                    label="Rebuild sase-core-rs into the uv-tool venv",
                    command=("just", "rust-install-uv-tool"),
                    cwd=host_record.source_root,
                )
            )
        else:
            steps.append(
                DevReconcileStep(
                    kind="rust_install_uv_tool",
                    label="Rebuild sase-core-rs into the uv-tool venv",
                    command=(),
                    reason="host checkout source root unavailable",
                )
            )

    return tuple(steps)

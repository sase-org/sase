"""Plan dev updates from checkout status and core compatibility."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from sase.dev_update.core_pin import CorePin, core_contains_revision, read_core_pin
from sase.dev_update.models import (
    DevPackagePlanStatus,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateRootPlan,
)
from sase.dev_update.progress import CHECK_STEP_ID, NULL_PROGRESS, check_child_id
from sase.update_progress import StepStatus, UpdateProgress
from sase.uv_tool.receipt import ToolReceipt
from sase.version._models import VersionPackageRecord
from ._plan_core_checkout import core_checkout_dir
from ._plan_reconcile import reconcile_steps
from ._plan_roots import build_package_and_root_plans


def plan_dev_update(
    records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
    *,
    host_record: VersionPackageRecord,
    receipt: ToolReceipt | None = None,
    tool_python: str | None = None,
    already_refreshed_roots: Collection[str] = (),
    stale_core_record: VersionPackageRecord | None = None,
    progress: UpdateProgress = NULL_PROGRESS,
) -> DevUpdatePlan:
    """Plan a fast-forward-only dev update for editable package records.

    *stale_core_record* is a wheel-installed ``sase-core-rs`` found in a dev
    (editable-host) install. Dev installs always use the editable core build,
    so a buildable local checkout makes the restore actionable even when no
    checkout is behind upstream.
    """
    packages, root_plans = build_package_and_root_plans(
        records,
        already_refreshed_roots=already_refreshed_roots,
        stale_core_record=stale_core_record,
        host_record=host_record,
        progress=progress,
    )
    editable_core_record = _editable_core_record(records)
    _apply_core_pin_gate(
        packages,
        root_plans,
        host_record=host_record,
        editable_core_record=editable_core_record,
    )
    _finish_check_step(progress, root_plans)
    reconcile = reconcile_steps(
        [pkg.record for pkg in packages if pkg.status == "actionable"],
        host_record=host_record,
        receipt=receipt,
        tool_python=tool_python,
        editable_core_record=editable_core_record,
        dev_core_present=any(
            record.role == "core" and record.install_type == "editable"
            for record in records
        ),
    )
    return DevUpdatePlan(
        packages=tuple(packages),
        roots=tuple(root_plans),
        reconcile_steps=reconcile,
    )


def _apply_core_pin_gate(
    packages: list[DevUpdatePackagePlan],
    roots: list[DevUpdateRootPlan],
    *,
    host_record: VersionPackageRecord,
    editable_core_record: VersionPackageRecord | None,
) -> None:
    """Keep the editable host and its Rust extension on compatible revisions."""
    if host_record.source_root is None:
        return

    host_package = next(
        (package for package in packages if package.record.name == host_record.name),
        None,
    )
    host_root = next(
        (root for root in roots if host_record.name in root.packages),
        None,
    )
    if host_package is None or host_root is None:
        return

    core_root_path: Path | None = None
    core_root_plan: DevUpdateRootPlan | None = None
    if editable_core_record is not None and editable_core_record.source_root:
        core_package = next(
            (
                package
                for package in packages
                if package.record.name == editable_core_record.name
            ),
            None,
        )
        if core_package is not None and core_package.git_root:
            core_root_path = Path(core_package.git_root)
        else:
            core_root_path = Path(editable_core_record.source_root)
        core_root_plan = next(
            (root for root in roots if root.git_root == str(core_root_path)), None
        )
        if core_root_plan is None:
            core_root_plan = next(
                (root for root in roots if editable_core_record.name in root.packages),
                None,
            )
    else:
        core_root_path = core_checkout_dir(host_record)

    if core_root_path is None:
        return

    actionable_host = host_root.status == "actionable"
    host_ref = (
        host_root.upstream
        if actionable_host and host_root.upstream is not None
        else "HEAD"
    )
    core_ref = (
        core_root_plan.upstream
        if core_root_plan is not None
        and core_root_plan.status == "actionable"
        and core_root_plan.upstream is not None
        else "HEAD"
    )
    pin = read_core_pin(Path(host_record.source_root), host_ref)
    if pin is None:
        return

    contained = core_contains_revision(core_root_path, pin.sha, core_ref)
    if actionable_host and contained is False:
        reason = _core_pin_gate_reason(
            pin,
            core_root_plan=core_root_plan,
            core_ref=core_ref,
        )
        roots[:] = [
            replace(root, status="skipped", reason=reason)
            if root.git_root == host_root.git_root
            else root
            for root in roots
        ]
        packages[:] = [
            replace(package, status="skipped", reason=reason)
            if package.git_root == host_root.git_root
            else package
            for package in packages
        ]
    elif actionable_host or contained is not False:
        return

    host_head_pin = (
        pin
        if host_ref == "HEAD"
        else read_core_pin(Path(host_record.source_root), "HEAD")
    )
    if host_head_pin is None:
        return
    head_contained = core_contains_revision(core_root_path, host_head_pin.sha, core_ref)
    if head_contained is not False:
        return
    core_name = (
        editable_core_record.name
        if editable_core_record is not None
        else "sase-core-rs"
    )
    core_reason = _core_pin_gate_reason(
        host_head_pin,
        core_root_plan=core_root_plan,
        core_ref=core_ref,
        installed_host=True,
    )
    if core_root_plan is not None and core_root_plan.status == "actionable":
        roots[:] = [
            replace(
                root,
                status="skipped",
                reason=f"{root.reason}; {core_reason}",
            )
            if root.git_root == core_root_plan.git_root
            else root
            for root in roots
        ]
    packages[:] = [
        replace(
            package,
            status="skipped",
            reason=f"{package.reason}; {core_reason}",
        )
        if (
            package.record.name == core_name
            or (
                core_root_plan is not None
                and package.git_root == core_root_plan.git_root
            )
        )
        else package
        for package in packages
    ]


def _core_pin_gate_reason(
    pin: CorePin,
    *,
    core_root_plan: DevUpdateRootPlan | None,
    core_ref: str,
    installed_host: bool = False,
) -> str:
    pin_name = f"sase-core {pin.short_sha} ({pin.pin_file})"
    if core_root_plan is not None and core_root_plan.status == "actionable":
        core_state = (
            f"the actionable sase-core upstream {core_ref} does not contain the "
            "pinned revision"
        )
    elif core_root_plan is not None:
        core_state = (
            "the sase-core checkout does not contain the pinned revision "
            f"({core_root_plan.reason})"
        )
    else:
        core_state = (
            f"the sase-core checkout at {core_ref} does not contain the pinned revision"
        )
    if installed_host:
        return (
            f"{pin_name} is required by the installed sase, but {core_state}, so "
            "sase_core_rs may be missing bindings"
        )
    return (
        f"needs {pin_name}, but {core_state}; clean or update the sase-core checkout "
        "to include the pin, then rerun `sase update`"
    )


def _finish_check_step(
    progress: UpdateProgress, root_plans: list[DevUpdateRootPlan]
) -> None:
    """Finish the ``check`` step and its per-root children.

    A no-op on the null sink. A root whose fetch failed is ``warned`` and
    counted as skipped in the parent summary.
    """
    for root_plan in root_plans:
        status, detail = _check_child_outcome(root_plan)
        progress.finish(check_child_id(root_plan.git_root), status, detail=detail)
    behind = sum(
        1
        for root_plan in root_plans
        if root_plan.status == "actionable" and root_plan.fetch_error is None
    )
    current = sum(
        1
        for root_plan in root_plans
        if root_plan.reason == "already current" and root_plan.fetch_error is None
    )
    skipped = len(root_plans) - behind - current
    segments = []
    if behind:
        segments.append(f"{behind} behind")
    if current:
        segments.append(f"{current} current")
    if skipped:
        segments.append(f"{skipped} skipped")
    warned = any(root_plan.fetch_error is not None for root_plan in root_plans)
    progress.finish(
        CHECK_STEP_ID,
        "warned" if warned else "done",
        detail=" · ".join(segments) or None,
    )


def _check_child_outcome(root_plan: DevUpdateRootPlan) -> tuple[StepStatus, str]:
    """Map a root plan entry to a ``(status, detail)`` step finish."""
    if root_plan.fetch_error is not None:
        return "warned", "fetch failed; using cached ref"
    if root_plan.reason == "already current":
        return "done", "current"
    if root_plan.status == "actionable":
        if root_plan.behind is not None and root_plan.upstream is not None:
            return "done", f"behind {root_plan.behind} · {root_plan.upstream}"
        return "done", root_plan.reason
    return "skipped", root_plan.reason


def _editable_core_record(
    records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
) -> VersionPackageRecord | None:
    for record in records:
        if record.role == "core" and record.install_type == "editable":
            return record
    return None

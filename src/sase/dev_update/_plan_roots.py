"""Build package and repository status rows for a dev update plan."""

from __future__ import annotations

import shutil
import subprocess
from collections import OrderedDict
from collections.abc import Collection
from pathlib import Path

from sase.dev_update.models import (
    DevPackagePlanStatus,
    DevUpdatePackagePlan,
    DevUpdateRootPlan,
)
from sase.dev_update.progress import (
    CHECK_STEP_ID,
    CHECK_STEP_TITLE,
    check_child_id,
    root_display_names,
)
from sase.update_progress import StepSpec, StepStatus, UpdateProgress
from sase.version._display import derive_display_version
from sase.version._git import (
    GitUpstreamStatus,
    classify_git_upstream,
    fetch_git_upstream,
    git_probe_cache_key,
    probe_git_metadata_at_ref,
)
from sase.version._models import VersionPackageRecord
from sase.version._sources import rust_source_version
from ._plan_core_checkout import core_checkout_dir


def build_package_and_root_plans(
    records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
    *,
    already_refreshed_roots: Collection[str],
    stale_core_record: VersionPackageRecord | None,
    host_record: VersionPackageRecord,
    progress: UpdateProgress,
) -> tuple[list[DevUpdatePackagePlan], list[DevUpdateRootPlan]]:
    """Inspect editable checkouts and build package and root plan rows."""
    fresh_roots = {git_probe_cache_key(Path(root)) for root in already_refreshed_roots}
    packages: list[DevUpdatePackagePlan] = []
    by_root: OrderedDict[str, list[VersionPackageRecord]] = OrderedDict()
    root_statuses: OrderedDict[str, GitUpstreamStatus] = OrderedDict()
    root_fetch_errors: OrderedDict[str, str | None] = OrderedDict()

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

    display_names = root_display_names(tuple(root_statuses))
    progress.declare(
        (
            StepSpec(CHECK_STEP_ID, CHECK_STEP_TITLE),
            *(
                StepSpec(
                    check_child_id(root),
                    display_names[root],
                    parent_id=CHECK_STEP_ID,
                )
                for root in root_statuses
            ),
        )
    )
    progress.start(CHECK_STEP_ID)
    for root, status in root_statuses.items():
        progress.start(check_child_id(root), detail="fetching…")
        if git_probe_cache_key(Path(root)) in fresh_roots:
            refreshed_status, fetch_error = status, None
        else:
            refreshed_status, fetch_error = _refresh_root_status(status)
        root_statuses[root] = refreshed_status
        root_fetch_errors[root] = fetch_error

    root_plans: list[DevUpdateRootPlan] = []
    for root, root_records in by_root.items():
        status = root_statuses[root]
        fetch_error = root_fetch_errors.get(root)
        root_status, reason = _classify_plan_status(status, fetch_error=fetch_error)
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
                fetch_error=fetch_error,
            )
        )
        for record in root_records:
            packages.append(
                _from_status(
                    record,
                    status,
                    root_status,
                    reason,
                    fetch_error=fetch_error,
                )
            )
    stale_core_plan = _stale_core_plan(stale_core_record, host_record=host_record)
    if stale_core_plan is not None:
        packages.append(stale_core_plan)

    return packages, root_plans


def _refresh_root_status(
    status: GitUpstreamStatus,
) -> tuple[GitUpstreamStatus, str | None]:
    if status.detached or not status.has_upstream:
        return status, None
    try:
        fetch_git_upstream(status)
        return classify_git_upstream(Path(status.root)), None
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        return status, _format_fetch_error(exc)


def _classify_plan_status(
    status: GitUpstreamStatus, *, fetch_error: str | None = None
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
        if fetch_error is not None:
            return "skipped", f"fetch failed; using cached upstream ref: {fetch_error}"
        return "skipped", "already current"
    if status.ahead and status.ahead > 0:
        return "skipped", "checkout is ahead of upstream"
    return "skipped", "upstream ancestry unavailable"


def _from_status(
    record: VersionPackageRecord,
    status: GitUpstreamStatus,
    plan_status: DevPackagePlanStatus,
    reason: str,
    *,
    fetch_error: str | None = None,
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
        fetch_error=fetch_error,
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


def _format_fetch_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return stderr.strip() or str(exc)
    if isinstance(exc, subprocess.TimeoutExpired):
        return "git fetch timed out"
    return str(exc)


def _stale_core_plan(
    stale_core_record: VersionPackageRecord | None,
    *,
    host_record: VersionPackageRecord,
) -> DevUpdatePackagePlan | None:
    """Plan the editable-core restore for a dev install running a wheel core.

    A wheel-installed core in a dev install means an earlier update replaced
    the local build (for example when a published version window excluded the
    checkout's version). The restore is actionable only when the checkout can
    actually be rebuilt; otherwise the wheel is kept and the reason says why.
    """
    if stale_core_record is None:
        return None
    checkout = core_checkout_dir(host_record)
    if checkout is None:
        return _skipped(
            stale_core_record,
            "installed sase-core-rs is a published wheel and no local "
            "sase-core checkout is available to rebuild the editable build",
        )
    if shutil.which("cargo") is None:
        return _skipped(
            stale_core_record,
            "installed sase-core-rs is a published wheel and cargo is not "
            "available to rebuild the editable build",
        )
    return DevUpdatePackagePlan(
        record=stale_core_record,
        status="actionable",
        reason=(
            "installed sase-core-rs is a published wheel; dev installs use "
            "the editable build from the local checkout"
        ),
        current_version=stale_core_record.display_version,
        latest_version=_core_checkout_version(checkout),
    )


def _core_checkout_version(checkout: Path) -> str | None:
    version = rust_source_version(checkout)
    result = probe_git_metadata_at_ref(checkout, "HEAD")
    if result.metadata is None:
        return version
    return derive_display_version(version, result.metadata)

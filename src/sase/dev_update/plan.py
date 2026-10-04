"""Plan safe editable-install dev updates."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from collections import OrderedDict
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from sase.dev_update.command import DEV_UPDATE_BUILD_COMMAND_TIMEOUT_SECONDS
from sase.dev_update.core_pin import CorePin, core_contains_revision, read_core_pin
from sase.dev_update.models import (
    DevPackagePlanStatus,
    DevReconcileStep,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateRootPlan,
)
from sase.dev_update.progress import (
    CHECK_STEP_ID,
    CHECK_STEP_TITLE,
    NULL_PROGRESS,
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
from sase.version._models import CORE_DISTRIBUTION_NAME, VersionPackageRecord
from sase.version._sources import rust_source_version
from sase.version._utils import normalize_distribution_name
from sase.uv_tool.commands import build_install
from sase.uv_tool.overrides import write_editable_overrides
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import ToolReceipt

_CORE_HEALTH_CHECK_SNIPPET = (
    "import importlib.metadata as m; "
    f"import {CORE_DISTRIBUTION_NAME.replace('-', '_')}; "
    f"print(m.version({CORE_DISTRIBUTION_NAME!r}))"
)
_RUST_DEV_PROFILE_ENV = "SASE_RUST_DEV_PROFILE"
_DEFAULT_RUST_DEV_PROFILE = "dev-update"


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

    _apply_core_pin_gate(
        packages,
        root_plans,
        host_record=host_record,
        editable_core_record=_editable_core_record(records),
    )
    _finish_check_step(progress, root_plans)

    editable_core_record = _editable_core_record(records)
    reconcile_steps = _reconcile_steps(
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
        reconcile_steps=reconcile_steps,
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
        core_root_path = _core_checkout_dir(host_record)

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


def _reconcile_steps(
    actionable_records: list[VersionPackageRecord],
    *,
    host_record: VersionPackageRecord,
    receipt: ToolReceipt | None,
    tool_python: str | None,
    editable_core_record: VersionPackageRecord | None = None,
    dev_core_present: bool = False,
) -> tuple[DevReconcileStep, ...]:
    steps: list[DevReconcileStep] = []
    python_changed = any(record.role != "core" for record in actionable_records)
    core_changed = any(record.role == "core" for record in actionable_records)
    # The uv-tool reinstall may rewrite the venv while resolving the editable
    # Python set, so an installed editable core is rebuilt afterwards even
    # when the core checkout itself did not change.
    rebuild_core = core_changed or (python_changed and dev_core_present)

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
            recon = receipt.reconstruct()
            error = missing_local_requirements_error(recon)
            if error is not None:
                steps.append(
                    DevReconcileStep(
                        kind="uv_tool_install",
                        label="Reinstall uv-tool editable Python packages",
                        command=(),
                        reason=str(error),
                    )
                )
            else:
                overrides_path = write_editable_overrides(receipt.requirements)
                steps.append(
                    DevReconcileStep(
                        kind="uv_tool_install",
                        label="Reinstall uv-tool editable Python packages",
                        command=tuple(
                            build_install(
                                receipt,
                                color="never",
                                overrides=str(overrides_path)
                                if overrides_path is not None
                                else None,
                            )
                        ),
                    )
                )

    if rebuild_core:
        steps.append(
            _rust_prebuild_install_step(
                host_record,
                actionable_records=actionable_records,
                editable_core_record=editable_core_record,
                tool_python=tool_python,
            )
        )
        if host_record.source_root:
            steps.append(
                DevReconcileStep(
                    kind="rust_dev_install",
                    label="Rebuild Rust dev artifacts into the uv-tool venv",
                    command=("just", "rust-dev-install-uv-tool"),
                    cwd=host_record.source_root,
                    env=_rust_dev_install_env(),
                    timeout_seconds=DEV_UPDATE_BUILD_COMMAND_TIMEOUT_SECONDS,
                )
            )
        else:
            steps.append(
                DevReconcileStep(
                    kind="rust_dev_install",
                    label="Rebuild Rust dev artifacts into the uv-tool venv",
                    command=(),
                    reason="host checkout source root unavailable",
                )
            )
        steps.append(_rust_health_check_step(host_record, tool_python=tool_python))
        if host_record.source_root:
            host_root = Path(host_record.source_root)
            binding_checker = host_root / "tools" / "check_sase_core_rs_bindings"
            if binding_checker.is_file():
                python = tool_python or sys.executable
                remedy = (
                    "Clean or update the sase-core checkout to the revision pinned by "
                    "this sase checkout, then rerun `sase update`."
                )
                steps.append(
                    DevReconcileStep(
                        kind="rust_binding_check",
                        label="Verify sase-core-rs exposes the bindings sase requires",
                        command=(
                            python,
                            str(binding_checker),
                            "--src",
                            str(host_root / "src" / "sase"),
                            "--remedy",
                            remedy,
                        ),
                    )
                )

    return tuple(steps)


def _editable_core_record(
    records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
) -> VersionPackageRecord | None:
    for record in records:
        if record.role == "core" and record.install_type == "editable":
            return record
    return None


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
    checkout = _core_checkout_dir(host_record)
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


def _core_checkout_dir(host_record: VersionPackageRecord) -> Path | None:
    env_dir = os.environ.get("SASE_CORE_DIR")
    candidates = [Path(env_dir)] if env_dir else []
    if host_record.source_root:
        candidates.append(Path(host_record.source_root).parent / "sase-core")
    for candidate in candidates:
        if (candidate / "Cargo.toml").is_file():
            return candidate
    return None


def _rust_dev_install_env() -> dict[str, str]:
    profile = _rust_dev_profile()
    return {_RUST_DEV_PROFILE_ENV: profile}


def _rust_dev_profile() -> str:
    return os.environ.get(_RUST_DEV_PROFILE_ENV) or _DEFAULT_RUST_DEV_PROFILE


def _rust_prebuild_install_step(
    host_record: VersionPackageRecord,
    *,
    actionable_records: list[VersionPackageRecord],
    editable_core_record: VersionPackageRecord | None,
    tool_python: str | None,
) -> DevReconcileStep:
    python = tool_python or sys.executable
    host_root = host_record.source_root
    core_root = _rust_prebuild_core_root(
        actionable_records,
        host_record=host_record,
        editable_core_record=editable_core_record,
    )
    label = "Install prebuilt Rust dev artifacts into the uv-tool venv"
    if host_root is None:
        return DevReconcileStep(
            kind="rust_prebuild_install",
            label=label,
            command=(),
            reason="host checkout source root unavailable",
        )
    if core_root is None:
        return DevReconcileStep(
            kind="rust_prebuild_install",
            label=label,
            command=(),
            reason="core checkout source root unavailable",
        )
    profile = _rust_dev_profile()
    return DevReconcileStep(
        kind="rust_prebuild_install",
        label=label,
        command=(
            python,
            "-m",
            "sase.dev_update.prebuild",
            "consume",
            "--core-root",
            str(core_root),
            "--host-root",
            host_root,
            "--python",
            python,
            "--profile",
            profile,
        ),
        cwd=host_root,
        env={_RUST_DEV_PROFILE_ENV: profile},
    )


def _rust_prebuild_core_root(
    actionable_records: list[VersionPackageRecord],
    *,
    host_record: VersionPackageRecord,
    editable_core_record: VersionPackageRecord | None,
) -> Path | None:
    for record in actionable_records:
        if record.role == "core" and record.source_root:
            return Path(record.source_root)
    if editable_core_record is not None and editable_core_record.source_root:
        return Path(editable_core_record.source_root)
    return _core_checkout_dir(host_record)


def _core_checkout_version(checkout: Path) -> str | None:
    version = rust_source_version(checkout)
    result = probe_git_metadata_at_ref(checkout, "HEAD")
    if result.metadata is None:
        return version
    return derive_display_version(version, result.metadata)


def _rust_health_check_step(
    host_record: VersionPackageRecord,
    *,
    tool_python: str | None,
) -> DevReconcileStep:
    python = tool_python or sys.executable
    specifier, repair_reason = _core_dependency_specifier(host_record)
    repair_command: tuple[str, ...] = ()
    if specifier is not None:
        repair_command = (
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--force-reinstall",
            f"{CORE_DISTRIBUTION_NAME}{specifier}",
        )
    return DevReconcileStep(
        kind="rust_health_check",
        label="Verify sase-core-rs imports in the uv-tool venv",
        command=(python, "-c", _CORE_HEALTH_CHECK_SNIPPET),
        repair_command=repair_command,
        repair_label="Restore published sase-core-rs wheel",
        repair_reason=repair_reason,
    )


def _core_dependency_specifier(
    host_record: VersionPackageRecord,
) -> tuple[str | None, str | None]:
    if not host_record.source_root:
        return None, "host checkout source root unavailable"
    pyproject = Path(host_record.source_root) / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"host pyproject unavailable: {exc}"
    except tomllib.TOMLDecodeError as exc:
        return None, f"host pyproject could not be parsed: {exc}"
    dependencies = data.get("project", {}).get("dependencies", [])
    if not isinstance(dependencies, list):
        return None, "host pyproject dependencies are not a list"
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement:
            continue
        if normalize_distribution_name(requirement.name) == normalize_distribution_name(
            CORE_DISTRIBUTION_NAME
        ):
            return str(requirement.specifier), None
    return None, "host pyproject does not declare a sase-core-rs dependency"

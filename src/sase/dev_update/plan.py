"""Plan safe editable-install dev updates."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from collections import OrderedDict
from collections.abc import Collection
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

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

    for root, status in root_statuses.items():
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

"""Build reconciliation commands for a planned dev update."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from sase.dev_update.command import DEV_UPDATE_BUILD_COMMAND_TIMEOUT_SECONDS
from sase.dev_update.models import DevReconcileStep
from sase.version._models import CORE_DISTRIBUTION_NAME, VersionPackageRecord
from sase.version._utils import normalize_distribution_name
from sase.uv_tool.commands import build_install
from sase.uv_tool.overrides import write_editable_overrides
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import ToolReceipt
from ._plan_core_checkout import core_checkout_dir

_CORE_HEALTH_CHECK_SNIPPET = (
    "import importlib.metadata as m; "
    f"import {CORE_DISTRIBUTION_NAME.replace('-', '_')}; "
    f"print(m.version({CORE_DISTRIBUTION_NAME!r}))"
)
_RUST_DEV_PROFILE_ENV = "SASE_RUST_DEV_PROFILE"
_DEFAULT_RUST_DEV_PROFILE = "dev-update"


def reconcile_steps(
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
    return core_checkout_dir(host_record)


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

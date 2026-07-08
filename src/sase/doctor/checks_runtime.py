"""Runtime, path, and VCS check registry for ``sase doctor``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.doctor.checks_install_management import (
    check_install_management,
    probe_uv_tool_install,
    uv_tool_data,
    uv_tool_details,
)
from sase.doctor.checks_runtime_common import (
    optional_str,
    resolve_command_from_env,
    safe_resolve,
    which_from_env,
)
from sase.doctor.checks_runtime_environment import (
    check_runtime_core,
    check_runtime_environment,
    check_runtime_version,
    current_checkout_root,
    current_python_version,
    display_record,
    find_ancestor_with,
    record_by_role,
    record_source_root,
)
from sase.doctor.checks_runtime_node import (
    check_runtime_node,
    format_npm_provider_details,
    llm_registry,
    npm_provider_readiness_rows,
    providers_from_payload,
)
from sase.doctor.checks_state_paths import (
    check_state_paths,
    directory_target,
    nearest_existing_parent,
)
from sase.doctor.checks_vcs_git import (
    GIT_TIMEOUT_SECONDS,
    check_vcs_git,
    git_config,
    git_result,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def runtime_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return runtime and install-management check specs."""
    return (
        CheckSpec(
            id="runtime.version",
            group="runtime",
            title="Runtime package inventory",
            runner=lambda: _check_runtime_version(context),
        ),
        CheckSpec(
            id="runtime.core",
            group="runtime",
            title="Rust core health",
            runner=_check_runtime_core,
        ),
        CheckSpec(
            id="runtime.environment",
            group="runtime",
            title="Runtime environment",
            runner=lambda: _check_runtime_environment(context),
        ),
        CheckSpec(
            id="runtime.node",
            group="runtime",
            title="Node/npm setup readiness",
            runner=lambda: _check_runtime_node(context),
        ),
        CheckSpec(
            id="install.management",
            group="install",
            title="Install management readiness",
            runner=lambda: _check_install_management(context),
        ),
        CheckSpec(
            id="state.paths",
            group="state",
            title="State and config paths",
            runner=lambda: _check_state_paths(context),
        ),
        CheckSpec(
            id="vcs.git",
            group="vcs",
            title="Git executable and identity",
            runner=lambda: _check_vcs_git(context),
        ),
    )


def _check_runtime_node(context: DoctorContext) -> DiagnosticCheck:
    return check_runtime_node(
        context,
        metadata_payload_fn=llm_registry.get_llm_metadata_payload,
    )


def _check_install_management(context: DoctorContext) -> DiagnosticCheck:
    return check_install_management(context, probe_fn=probe_uv_tool_install)


def _check_runtime_version(context: DoctorContext) -> DiagnosticCheck:
    return check_runtime_version(context)


def _check_runtime_core() -> DiagnosticCheck:
    return check_runtime_core()


def _check_runtime_environment(context: DoctorContext) -> DiagnosticCheck:
    return check_runtime_environment(
        context,
        checkout_root_fn=_current_checkout_root,
        python_version_fn=_current_python_version,
    )


def _check_state_paths(context: DoctorContext) -> DiagnosticCheck:
    return check_state_paths(context)


def _check_vcs_git(context: DoctorContext) -> DiagnosticCheck:
    return check_vcs_git(
        context,
        which_fn=shutil.which,
        git_result_fn=_git_result,
        git_config_fn=_git_config,
    )


_GIT_TIMEOUT_SECONDS = GIT_TIMEOUT_SECONDS
_record_by_role = record_by_role
_display_record = display_record
_record_source_root = record_source_root


def _current_checkout_root(cwd: Path) -> Path | None:
    result = _git_result(cwd, "rev-parse", "--show-toplevel")
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return _find_ancestor_with(cwd, "pyproject.toml")


def _find_ancestor_with(start: Path, filename: str) -> Path | None:
    return find_ancestor_with(start, filename)


def _git_config(repo_root: Path, key: str) -> str | None:
    result = _git_result(repo_root, "config", key)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_result(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    return git_result(cwd, *args)


def _current_python_version() -> tuple[int, int]:
    return current_python_version()


_which_from_env = which_from_env
_uv_tool_data = uv_tool_data
_uv_tool_details = uv_tool_details
_providers_from_payload = providers_from_payload
_npm_provider_readiness_rows = npm_provider_readiness_rows
_format_npm_provider_details = format_npm_provider_details
_resolve_command_from_env = resolve_command_from_env
_optional_str = optional_str
_directory_target = directory_target
_nearest_existing_parent = nearest_existing_parent
_safe_resolve = safe_resolve


__all__ = [
    "runtime_check_specs",
]

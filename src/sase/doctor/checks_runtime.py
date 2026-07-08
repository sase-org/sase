"""Runtime, path, and VCS checks for ``sase doctor``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.config.core import CONFIG_DIR, load_merged_config
from sase.core.health import HEALTH_OK, check_backend_health
from sase.core.paths import sase_projects_dir
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.llm_provider import registry as llm_registry
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.version.inventory import VersionPackageRecord
from sase.workspace_provider.store import WorkspaceStore

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_GIT_TIMEOUT_SECONDS = 1.0


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
    """Check Node/npm only when registered provider setup may need npm."""
    node_path = _which_from_env(context.env)("node")
    npm_path = _which_from_env(context.env)("npm")
    missing_tools = [
        tool
        for tool, executable in (("node", node_path), ("npm", npm_path))
        if executable is None
    ]

    try:
        payload = llm_registry.get_llm_metadata_payload()
        providers = _providers_from_payload(payload)
    except Exception as exc:  # noqa: BLE001 - llm.registry owns metadata failures.
        return DiagnosticCheck(
            id="runtime.node",
            group="runtime",
            status="SKIP",
            title="Node/npm setup readiness",
            summary="provider metadata unavailable; node/npm setup not checked",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Run `sase doctor -C llm.registry` and fix provider registry errors first.",
            ),
            data={
                "node_path": node_path,
                "npm_path": npm_path,
                "missing_tools": missing_tools,
                "providers": [],
                "missing_provider_clis": [],
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    npm_providers = _npm_provider_readiness_rows(providers, context)
    if not npm_providers:
        return DiagnosticCheck(
            id="runtime.node",
            group="runtime",
            status="SKIP",
            title="Node/npm setup readiness",
            summary="no npm-installed LLM providers are registered",
            data={
                "node_path": node_path,
                "npm_path": npm_path,
                "missing_tools": missing_tools,
                "providers": [],
                "missing_provider_clis": [],
            },
        )

    missing_provider_clis = [
        row["provider"]
        for row in npm_providers
        if row["command"] is not None and row["executable"] is None
    ]
    details = (
        f"node: {node_path or 'missing'}",
        f"npm: {npm_path or 'missing'}",
        *_format_npm_provider_details(npm_providers),
    )

    if missing_tools and missing_provider_clis:
        missing_tool_text = "/".join(missing_tools)
        missing_provider_text = ", ".join(missing_provider_clis)
        return DiagnosticCheck(
            id="runtime.node",
            group="runtime",
            status="WARN",
            title="Node/npm setup readiness",
            summary=(
                f"{missing_tool_text} missing while npm-installed provider CLI(s) "
                f"are unavailable: {missing_provider_text}"
            ),
            details=details,
            next_steps=(
                "Install Node.js/npm before following npm-based provider setup instructions.",
                "Install the missing provider CLI(s), then rerun `sase doctor -C runtime.node -v`.",
            ),
            data={
                "node_path": node_path,
                "npm_path": npm_path,
                "missing_tools": missing_tools,
                "providers": npm_providers,
                "missing_provider_clis": missing_provider_clis,
            },
        )

    if missing_tools:
        summary = (
            "node/npm is missing, but registered npm-installed provider CLIs "
            "are already available"
        )
    else:
        summary = "node and npm are available for npm-installed provider setup"

    return DiagnosticCheck(
        id="runtime.node",
        group="runtime",
        status="OK",
        title="Node/npm setup readiness",
        summary=summary,
        details=details,
        data={
            "node_path": node_path,
            "npm_path": npm_path,
            "missing_tools": missing_tools,
            "providers": npm_providers,
            "missing_provider_clis": missing_provider_clis,
        },
    )


def _check_install_management(context: DoctorContext) -> DiagnosticCheck:
    """Check whether update/plugin management can safely use ``uv tool``."""
    result = probe_uv_tool_install(
        which_fn=_which_from_env(context.env),
        environ=context.env,
    )

    if isinstance(result, UvToolInstall):
        data = _uv_tool_data(result)
        return DiagnosticCheck(
            id="install.management",
            group="install",
            status="OK",
            title="Install management readiness",
            summary="sase is managed by uv tool; install/update workflows are available",
            details=_uv_tool_details(data),
            data=data,
        )

    data = _uv_tool_data(result)
    reason = result.reason.value
    return DiagnosticCheck(
        id="install.management",
        group="install",
        status="WARN",
        title="Install management readiness",
        summary=(f"sase is not running from a canonical uv-tool install ({reason})"),
        details=(
            *_uv_tool_details(data),
            "affected flows: `sase update`, plugin management, Admin Center updates, "
            "chat-driven install/update workers",
        ),
        next_steps=(
            "Install or run SASE via `uv tool install sase` before using install/update management flows.",
            "Rerun `sase doctor -C install.management -v` from the intended environment.",
        ),
        data=data,
    )


def _check_runtime_version(context: DoctorContext) -> DiagnosticCheck:
    """Collect the active host/core/plugin runtime inventory."""
    inventory = context.get_runtime_inventory()
    package_warnings = [
        f"{record.name}: {warning}"
        for record in inventory.packages
        for warning in record.warnings
    ]
    host = _record_by_role(inventory.packages, "host")
    core = _record_by_role(inventory.packages, "core")
    plugin_count = sum(1 for record in inventory.packages if record.role == "plugin")
    status: CheckStatus = "WARN" if package_warnings else "OK"
    summary = (
        f"{len(inventory.packages)} packages detected; "
        f"host={_display_record(host)}, core={_display_record(core)}, "
        f"plugins={plugin_count}"
    )
    if package_warnings:
        summary = f"{len(package_warnings)} package warning(s) found"

    data: dict[str, Any] = {
        "executable": inventory.executable,
        "python_executable": inventory.python_executable,
        "python_version": inventory.python_version,
        "package_count": len(inventory.packages),
        "packages": [
            {
                "name": record.name,
                "role": record.role,
                "display_version": record.display_version,
                "install_type": record.install_type,
                "source_root": record.source_root,
                "code_directory": record.code_directory,
            }
            for record in inventory.packages
        ],
        "warnings": package_warnings,
    }
    if context.verbose:
        data["inventory"] = inventory.to_dict()

    return DiagnosticCheck(
        id="runtime.version",
        group="runtime",
        status=status,
        title="Runtime package inventory",
        summary=summary,
        details=tuple(package_warnings[:8]),
        next_steps=("Run `sase version -v` for the full runtime package audit.",)
        if package_warnings
        else (),
        data=data,
    )


def _check_runtime_core() -> DiagnosticCheck:
    """Adapt ``sase core health`` into the shared doctor model."""
    report = check_backend_health()
    probes = report.extras.get("probes", {})
    if not isinstance(probes, Mapping):
        probes = {}
    passed = sum(1 for ok in probes.values() if ok)
    total = len(probes)
    status: CheckStatus = "OK" if report.status == HEALTH_OK else "ERROR"
    if status == "OK":
        summary = (
            f"{report.rust_extension_module} loaded; {passed}/{total} probes passed"
        )
    else:
        summary = report.error or f"{report.rust_extension_module} health check failed"

    details = [
        f"python: {report.python_version}",
        f"platform: {report.platform}",
    ]
    if report.rust_extension_path:
        details.append(f"extension path: {report.rust_extension_path}")
    if report.rust_extension_version:
        details.append(f"extension version: {report.rust_extension_version}")
    if report.error:
        details.append(f"error: {report.error}")

    return DiagnosticCheck(
        id="runtime.core",
        group="runtime",
        status=status,
        title="Rust core health",
        summary=summary,
        details=tuple(details),
        next_steps=(
            "Run `just install` in this workspace, then `sase core health -j`.",
        )
        if status == "ERROR"
        else (),
        data=report.to_dict(),
    )


def _check_runtime_environment(context: DoctorContext) -> DiagnosticCheck:
    """Check Python support and editable/source-root drift."""
    inventory = context.get_runtime_inventory()
    details: list[str] = [
        f"python: {inventory.python_version}",
        f"python executable: {inventory.python_executable}",
        f"sase executable: {inventory.executable}",
    ]
    next_steps: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    if _current_python_version() < (3, 12):
        errors.append("Python 3.12 or newer is required.")
        next_steps.append("Use a Python 3.12+ environment and rerun `just install`.")

    host = _record_by_role(inventory.packages, "host")
    checkout_root = _current_checkout_root(context.cwd)
    host_root = _record_source_root(host)
    if checkout_root is not None:
        details.append(f"checkout root: {checkout_root}")
    if host_root is not None:
        details.append(f"host source root: {host_root}")

    if (
        host is not None
        and host.install_type == "editable"
        and checkout_root is not None
        and host_root is not None
        and _safe_resolve(checkout_root) != _safe_resolve(host_root)
    ):
        warnings.append(
            "active sase import root differs from the current checkout root"
        )
        next_steps.append("Run `just install` in this workspace.")

    status: CheckStatus = "ERROR" if errors else "WARN" if warnings else "OK"
    summary = "runtime environment is consistent"
    if errors:
        summary = errors[0]
    elif warnings:
        summary = warnings[0]

    return DiagnosticCheck(
        id="runtime.environment",
        group="runtime",
        status=status,
        title="Runtime environment",
        summary=summary,
        details=(*details, *errors, *warnings),
        next_steps=tuple(dict.fromkeys(next_steps)),
        data={
            "python_version": inventory.python_version,
            "python_executable": inventory.python_executable,
            "sase_executable": inventory.executable,
            "checkout_root": str(checkout_root) if checkout_root else None,
            "host_source_root": str(host_root) if host_root else None,
            "host_install_type": host.install_type if host else None,
        },
    )


def _check_state_paths(context: DoctorContext) -> DiagnosticCheck:
    """Check required SASE state, config, project, and workspace paths."""
    path_rows: list[dict[str, Any]] = [
        _directory_target("sase_home", context.sase_home),
        _directory_target("config_dir", CONFIG_DIR),
        _directory_target("projects_dir", sase_projects_dir()),
    ]
    workspace_error: str | None = None
    try:
        config = load_merged_config()
        store = WorkspaceStore(str(context.cwd), config=config)
        path_rows.append(_directory_target("workspace_root", Path(store.root_dir)))
    except Exception as exc:  # noqa: BLE001 - report config/root resolution failures.
        workspace_error = f"{type(exc).__name__}: {exc}"

    errors = [
        f"{row['label']}: {row['problem']}" for row in path_rows if row.get("problem")
    ]
    if workspace_error:
        errors.append(f"workspace_root: {workspace_error}")

    status: CheckStatus = "ERROR" if errors else "OK"
    existing = sum(1 for row in path_rows if row["exists"])
    creatable = sum(1 for row in path_rows if row["creatable"])
    summary = (
        f"{existing}/{len(path_rows)} paths exist; missing paths are creatable"
        if status == "OK"
        else f"{len(errors)} path problem(s) found"
    )

    return DiagnosticCheck(
        id="state.paths",
        group="state",
        status=status,
        title="State and config paths",
        summary=summary,
        details=tuple(errors),
        next_steps=("Fix ownership/permissions for the reported paths.",)
        if errors
        else (),
        data={
            "paths": path_rows,
            "creatable_count": creatable,
            "workspace_error": workspace_error,
        },
    )


def _check_vcs_git(context: DoctorContext) -> DiagnosticCheck:
    """Check git availability, repo detection, and effective identity."""
    git_path = shutil.which("git")
    if git_path is None:
        return DiagnosticCheck(
            id="vcs.git",
            group="vcs",
            status="ERROR",
            title="Git executable and identity",
            summary="git executable was not found on PATH",
            next_steps=("Install git and ensure it is available on PATH.",),
            data={"git_executable": None},
        )

    repo = _git_result(context.cwd, "rev-parse", "--show-toplevel")
    if repo is None or repo.returncode != 0 or not repo.stdout.strip():
        return DiagnosticCheck(
            id="vcs.git",
            group="vcs",
            status="SKIP",
            title="Git executable and identity",
            summary="git is available; current directory is not a git repository",
            data={"git_executable": git_path, "repo_root": None},
        )

    repo_root = Path(repo.stdout.strip())
    user_name = _git_config(repo_root, "user.name")
    user_email = _git_config(repo_root, "user.email")
    missing = []
    if not user_name:
        missing.append("user.name")
    if not user_email:
        missing.append("user.email")

    status: CheckStatus = "WARN" if missing else "OK"
    summary = (
        f"git repo detected at {repo_root}; identity configured"
        if not missing
        else f"git repo detected; missing {', '.join(missing)}"
    )
    next_steps = []
    if "user.name" in missing:
        next_steps.append('Run `git config user.name "Your Name"` in this repo.')
    if "user.email" in missing:
        next_steps.append('Run `git config user.email "you@example.com"` in this repo.')

    return DiagnosticCheck(
        id="vcs.git",
        group="vcs",
        status=status,
        title="Git executable and identity",
        summary=summary,
        details=(f"repo root: {repo_root}",),
        next_steps=tuple(next_steps),
        data={
            "git_executable": git_path,
            "repo_root": str(repo_root),
            "user_name_configured": bool(user_name),
            "user_email_configured": bool(user_email),
        },
    )


def _record_by_role(
    records: Sequence[VersionPackageRecord], role: str
) -> VersionPackageRecord | None:
    return next((record for record in records if record.role == role), None)


def _display_record(record: VersionPackageRecord | None) -> str:
    if record is None:
        return "missing"
    return f"{record.name} {record.display_version}"


def _record_source_root(record: VersionPackageRecord | None) -> Path | None:
    if record is None:
        return None
    for value in (record.source_root, record.code_directory, record.import_path):
        if value:
            return Path(value)
    return None


def _current_checkout_root(cwd: Path) -> Path | None:
    result = _git_result(cwd, "rev-parse", "--show-toplevel")
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return _find_ancestor_with(cwd, "pyproject.toml")


def _find_ancestor_with(start: Path, filename: str) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / filename).is_file():
            return candidate
    return None


def _git_config(repo_root: Path, key: str) -> str | None:
    result = _git_result(repo_root, "config", key)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_result(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _which_from_env(env: Mapping[str, str]) -> Callable[[str], str | None]:
    path = env.get("PATH", "")
    return lambda command: shutil.which(command, path=path)


def _uv_tool_data(result: UvToolInstall | NotUvToolInstall) -> dict[str, Any]:
    if isinstance(result, UvToolInstall):
        return {
            "managed": True,
            "reason": None,
            "uv_path": result.uv_path,
            "tool_dir": str(result.tool_dir),
            "sys_prefix": str(result.sase_dir),
            "receipt_path": str(result.receipt_path),
        }

    return {
        "managed": False,
        "reason": result.reason.value,
        "uv_path": result.uv_path,
        "tool_dir": str(result.expected_sase_dir.parent),
        "sys_prefix": str(result.sys_prefix),
        "receipt_path": str(result.receipt_path),
    }


def _uv_tool_details(data: Mapping[str, Any]) -> tuple[str, ...]:
    uv_path = data["uv_path"] if data["uv_path"] else "missing"
    details = [
        f"uv path: {uv_path}",
        f"uv tool dir: {data['tool_dir']}",
        f"sys.prefix: {data['sys_prefix']}",
        f"receipt: {data['receipt_path']}",
    ]
    if data["reason"]:
        details.insert(0, f"reason: {data['reason']}")
    return tuple(details)


def _providers_from_payload(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return {}
    return {
        str(provider): dict(metadata)
        for provider, metadata in providers.items()
        if isinstance(metadata, dict)
    }


def _npm_provider_readiness_rows(
    providers: Mapping[str, Mapping[str, Any]],
    context: DoctorContext,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider_name in sorted(providers):
        metadata = providers[provider_name]
        install = metadata.get("install")
        if not isinstance(install, Mapping) or install.get("manager") != "npm":
            continue

        cli_name = _optional_str(metadata.get("autodetect_cli_name"))
        path_env = llm_registry.provider_path_env_var(provider_name)
        configured_command = _optional_str(context.env.get(path_env))
        command = configured_command or cli_name
        rows.append(
            {
                "provider": provider_name,
                "manager": "npm",
                "package": _optional_str(install.get("package")),
                "scope": _optional_str(install.get("scope")),
                "cli_name": cli_name,
                "path_env": path_env,
                "configured_command": configured_command,
                "command": command,
                "executable": _resolve_command_from_env(command, context.env),
            }
        )
    return rows


def _format_npm_provider_details(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    details: list[str] = []
    for row in rows:
        package = row.get("package") or "unknown package"
        command = row.get("command")
        executable = row.get("executable")
        command_text = repr(command) if command is not None else "not declared"
        executable_text = executable or "missing" if command is not None else "n/a"
        details.append(
            f"{row['provider']}: {package}; command {command_text}, "
            f"executable: {executable_text}"
        )
    return tuple(details)


def _resolve_command_from_env(
    command: str | None, env: Mapping[str, str]
) -> str | None:
    if not command:
        return None
    expanded = os.path.expanduser(command)
    resolved = _which_from_env(env)(expanded)
    if resolved:
        return resolved
    if os.sep in expanded:
        path = Path(expanded)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _directory_target(label: str, path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    exists = expanded.exists()
    is_dir = expanded.is_dir()
    problem: str | None = None
    creatable = False

    if exists and not is_dir:
        problem = f"{expanded} exists but is not a directory"
    elif exists:
        if not os.access(expanded, os.W_OK | os.X_OK):
            problem = f"{expanded} is not writable"
        else:
            creatable = True
    else:
        parent = _nearest_existing_parent(expanded)
        if parent is None or not os.access(parent, os.W_OK | os.X_OK):
            problem = f"{expanded} does not exist and parent is not writable"
        else:
            creatable = True

    return {
        "label": label,
        "path": str(expanded),
        "exists": exists,
        "is_dir": is_dir,
        "creatable": creatable,
        "problem": problem,
    }


def _nearest_existing_parent(path: Path) -> Path | None:
    for candidate in (path.parent, *path.parents):
        if candidate.exists():
            return candidate if candidate.is_dir() else None
    return None


def _safe_resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _current_python_version() -> tuple[int, int]:
    return (sys.version_info.major, sys.version_info.minor)


__all__ = [
    "runtime_check_specs",
]

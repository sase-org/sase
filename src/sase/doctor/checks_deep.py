"""Deep diagnostic checks for ``sase doctor``."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.ace.hooks.processes import is_process_running
from sase.axe.config import load_axe_config
from sase.axe.maintenance import read_maintenance
from sase.axe.state import read_lumberjack_status
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    verify_agent_artifact_index,
)
from sase.core.paths import sase_projects_dir
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.llm_provider import registry as llm_registry

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_VERSION_TIMEOUT_SECONDS = 2.0


def deep_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return deep diagnostic check specs not owned by another subsystem module."""
    return (
        CheckSpec(
            id="state.agent_index_verify",
            group="state",
            title="Agent artifact index verify",
            runner=_check_agent_index_verify,
            deep=True,
        ),
        CheckSpec(
            id="ops.axe",
            group="ops",
            title="Axe runtime state",
            runner=_check_axe_state,
            deep=True,
        ),
        CheckSpec(
            id="providers.cli_version",
            group="providers",
            title="Provider CLI versions",
            runner=lambda: _check_provider_cli_versions(context),
            deep=True,
        ),
    )


def _check_agent_index_verify() -> DiagnosticCheck:
    """Run the full read-only agent artifact index verifier."""
    result = verify_agent_artifact_index(
        default_agent_artifact_index_path(),
        sase_projects_dir(),
    )
    problem_count_values = {
        "stale_rows": result.stale_rows,
        "missing_rows": result.missing_rows,
        "extra_rows": result.extra_rows,
        "corrupt_rows": result.corrupt_rows,
    }
    data = {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "index_path": result.index_path,
        "projects_root": result.projects_root,
        "indexed_rows": result.indexed_rows,
        "source_rows": result.source_rows,
        **problem_count_values,
    }
    problem_counts = {
        key: value for key, value in problem_count_values.items() if value
    }
    status: CheckStatus = "OK" if result.ok else "WARN"
    summary = (
        f"agent artifact index matches {result.source_rows} source row(s)"
        if result.ok
        else f"agent artifact index drift found: {_format_counts(problem_counts)}"
    )
    details = tuple(f"{key}: {value}" for key, value in problem_counts.items())

    return DiagnosticCheck(
        id="state.agent_index_verify",
        group="state",
        status=status,
        title="Agent artifact index verify",
        summary=summary,
        details=details,
        next_steps=("Run `sase agents index gc`.",) if not result.ok else (),
        data=data,
    )


def _check_provider_cli_versions(context: DoctorContext) -> DiagnosticCheck:
    """Probe registered provider CLIs with bounded ``--version`` commands."""
    try:
        payload = llm_registry.get_llm_metadata_payload()
    except Exception as exc:  # noqa: BLE001 - report provider metadata failures.
        return DiagnosticCheck(
            id="providers.cli_version",
            group="providers",
            status="ERROR",
            title="Provider CLI versions",
            summary="provider metadata could not be loaded",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=("Run `sase doctor -C llm.registry`.",),
            data={"error": f"{type(exc).__name__}: {exc}"},
        )

    providers = _providers_from_payload(payload)
    if not providers:
        return DiagnosticCheck(
            id="providers.cli_version",
            group="providers",
            status="SKIP",
            title="Provider CLI versions",
            summary="no provider CLI metadata is registered",
            data={"providers": []},
        )

    rows = [
        _provider_cli_version_row(context, name, metadata)
        for name, metadata in sorted(providers.items())
    ]
    probed = [row for row in rows if row["probe_status"] != "skipped"]
    failed = [
        row for row in probed if row["probe_status"] not in {"ok", "skipped_no_cli"}
    ]
    status: CheckStatus = "WARN" if failed else "OK"
    ok_count = sum(1 for row in probed if row["probe_status"] == "ok")
    summary = (
        f"{ok_count}/{len(probed)} provider CLI version probe(s) succeeded"
        if probed
        else "registered providers do not declare CLI version probes"
    )
    details = tuple(
        f"{row['provider']}: {row['probe_status']} ({row['detail']})" for row in failed
    )

    return DiagnosticCheck(
        id="providers.cli_version",
        group="providers",
        status=status,
        title="Provider CLI versions",
        summary=summary,
        details=details,
        data={"providers": rows},
    )


def _provider_cli_version_row(
    context: DoctorContext,
    provider: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    cli_name = _optional_str(metadata.get("autodetect_cli_name"))
    env_var = _provider_path_env(provider)
    configured_command = _optional_str(context.env.get(env_var))
    command = configured_command or cli_name
    if command is None:
        return {
            "provider": provider,
            "cli_name": None,
            "path_env": env_var,
            "configured_command": configured_command,
            "executable": None,
            "probe_status": "skipped",
            "detail": "provider declares no CLI",
            "version": None,
        }

    executable = _resolve_executable(command)
    if executable is None:
        return {
            "provider": provider,
            "cli_name": cli_name,
            "path_env": env_var,
            "configured_command": configured_command,
            "executable": None,
            "probe_status": "missing",
            "detail": f"executable {command!r} was not found",
            "version": None,
        }

    result = _run_version_probe(executable)
    return {
        "provider": provider,
        "cli_name": cli_name,
        "path_env": env_var,
        "configured_command": configured_command,
        "executable": executable,
        **result,
    }


def _run_version_probe(executable: str) -> dict[str, str | int | None]:
    try:
        result = subprocess.run(
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "probe_status": "timeout",
            "detail": f"`--version` timed out after {_VERSION_TIMEOUT_SECONDS:g}s",
            "version": None,
            "returncode": None,
        }
    except OSError as exc:
        return {
            "probe_status": "error",
            "detail": f"{type(exc).__name__}: {exc}",
            "version": None,
            "returncode": None,
        }

    output = (result.stdout or result.stderr).strip().splitlines()
    version = output[0].strip() if output else ""
    if result.returncode == 0:
        return {
            "probe_status": "ok",
            "detail": version or "version command succeeded",
            "version": version,
            "returncode": result.returncode,
        }
    return {
        "probe_status": "failed",
        "detail": version or f"exited {result.returncode}",
        "version": version,
        "returncode": result.returncode,
    }


def _check_axe_state() -> DiagnosticCheck:
    """Summarize configured axe/lumberjack runtime state."""
    config = load_axe_config()
    maintenance = read_maintenance()
    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    for name in sorted(config.lumberjacks):
        status = read_lumberjack_status(name)
        if status is None:
            rows.append(
                {
                    "name": name,
                    "configured": True,
                    "state": "not_running",
                    "pid": None,
                    "cycles_run": 0,
                    "errors_encountered": 0,
                }
            )
            continue

        running = is_process_running(status.pid)
        state = "running" if running else "stale_status"
        if not running:
            problems.append(f"{name}: stale status file for PID {status.pid}")
        if status.errors_encountered:
            problems.append(f"{name}: {status.errors_encountered} error(s) encountered")
        rows.append(
            {
                "name": name,
                "configured": True,
                "state": state,
                "pid": status.pid,
                "started_at": status.started_at,
                "interval": status.interval,
                "chops": list(status.chops),
                "cycles_run": status.cycles_run,
                "errors_encountered": status.errors_encountered,
                "uptime_seconds": status.uptime_seconds,
            }
        )

    if maintenance is not None:
        problems.append(
            f"axe maintenance active: {maintenance.get('reason', 'unknown')}"
        )

    running_count = sum(1 for row in rows if row["state"] == "running")
    status_value: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(rows)} configured lumberjack(s); {running_count} running"
        if rows
        else "no axe lumberjacks are configured"
    )

    return DiagnosticCheck(
        id="ops.axe",
        group="ops",
        status=status_value,
        title="Axe runtime state",
        summary=summary,
        details=tuple(problems[:8]),
        next_steps=("Run `sase axe lumberjack status`.",) if problems else (),
        data={
            "lumberjacks": rows,
            "maintenance": maintenance,
            "max_hook_runners": config.max_hook_runners,
            "max_agent_runners": config.max_agent_runners,
            "zombie_timeout_seconds": config.zombie_timeout_seconds,
        },
    )


def _resolve_executable(command: str) -> str | None:
    expanded = os.path.expanduser(command)
    resolved = shutil.which(expanded)
    if resolved:
        return resolved
    if os.sep in expanded:
        path = Path(expanded)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _providers_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return {}
    return {
        str(name): dict(metadata)
        for name, metadata in providers.items()
        if isinstance(metadata, dict)
    }


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _provider_path_env(provider_name: str) -> str:
    import re

    token = re.sub(r"[^A-Za-z0-9]+", "_", provider_name).strip("_").upper()
    return f"SASE_{token}_PATH"


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


__all__ = [
    "deep_check_specs",
]

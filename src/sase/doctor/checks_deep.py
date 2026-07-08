"""Deep diagnostic checks for ``sase doctor``."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
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
from sase.integrations import xprompt_lsp
from sase.llm_provider import registry as llm_registry

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_VERSION_TIMEOUT_SECONDS = 2.0
_TMUX_PASSTHROUGH_MIN_VERSION = (3, 3)
_TMUX_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")


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
        CheckSpec(
            id="tools.xprompt_lsp",
            group="tools",
            title="xprompt LSP command",
            runner=lambda: _check_xprompt_lsp(context),
            deep=True,
        ),
        CheckSpec(
            id="terminal.kitty_graphics",
            group="terminal",
            title="Kitty graphics protocol",
            runner=lambda: _check_kitty_graphics(context),
            deep=True,
        ),
        CheckSpec(
            id="tools.tmux_version",
            group="tools",
            title="tmux passthrough version",
            runner=lambda: _check_tmux_version(context),
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
        next_steps=("Run `sase agent index gc`.",) if not result.ok else (),
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


def _check_xprompt_lsp(context: DoctorContext) -> DiagnosticCheck:
    """Mirror the ``sase lsp`` server-command resolver without launching it."""
    try:
        command = xprompt_lsp.resolve_xprompt_lsp_command(
            environ=context.env,
            which=shutil.which,
            repo_root=None,
        )
    except xprompt_lsp.XPromptLspLaunchError as exc:
        return DiagnosticCheck(
            id="tools.xprompt_lsp",
            group="tools",
            status="WARN",
            title="xprompt LSP command",
            summary="xprompt LSP server command does not resolve",
            details=(
                str(exc),
                "Editor xprompt completions and diagnostics require this server.",
            ),
            next_steps=(
                "Install `sase-xprompt-lsp` into the current venv or PATH, build the sibling `sase-core` LSP binary, or set $SASE_XPROMPT_LSP_CMD.",
            ),
            data={
                "resolved": False,
                "command": [],
                "source": None,
                "env_var": xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV,
                "env_override_set": bool(
                    context.env.get(xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV, "").strip()
                ),
                "cargo_fallback": False,
                "error": str(exc),
            },
        )

    source = _xprompt_lsp_command_source(command, context.env)
    cargo_fallback = _is_xprompt_lsp_cargo_run(command)
    if cargo_fallback:
        return DiagnosticCheck(
            id="tools.xprompt_lsp",
            group="tools",
            status="WARN",
            title="xprompt LSP command",
            summary="xprompt LSP resolves through the slow cargo fallback",
            details=(
                f"Command: {_format_command(command)}",
                "Editor startup can be slow because Cargo must check or build the Rust LSP package before serving requests.",
            ),
            next_steps=(
                "Install `sase-xprompt-lsp` into the current venv or PATH, or build the sibling `sase-core` LSP binary once.",
            ),
            data={
                "resolved": True,
                "command": list(command),
                "source": source,
                "env_var": xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV,
                "env_override_set": bool(
                    context.env.get(xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV, "").strip()
                ),
                "cargo_fallback": True,
            },
        )

    return DiagnosticCheck(
        id="tools.xprompt_lsp",
        group="tools",
        status="OK",
        title="xprompt LSP command",
        summary=f"xprompt LSP server resolves via {source}",
        details=(f"Command: {_format_command(command)}",),
        data={
            "resolved": True,
            "command": list(command),
            "source": source,
            "env_var": xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV,
            "env_override_set": bool(
                context.env.get(xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV, "").strip()
            ),
            "cargo_fallback": False,
        },
    )


def _check_kitty_graphics(context: DoctorContext) -> DiagnosticCheck:
    """Infer kitty-graphics support for inline artifact rendering."""
    support = _kitty_graphics_support(context.env)
    kitten_path = shutil.which("kitten")
    missing_details: list[str] = []
    if not support["supported"]:
        missing_details.append(
            "Inline image/PDF/Markdown artifact rendering needs a terminal that supports the kitty graphics protocol."
        )
    if kitten_path is None:
        missing_details.append(
            "`kitten` is not installed or not on PATH; it is used for terminal image artifact display."
        )

    status: CheckStatus = "WARN" if missing_details else "OK"
    summary = (
        "kitty graphics protocol is advertised for inline artifacts"
        if status == "OK"
        else "kitty graphics inline artifact support is incomplete"
    )
    details = (f"Detection: {support['reason']}.", *missing_details)
    next_steps = tuple(
        step
        for step in (
            "Run ACE in kitty, WezTerm, Ghostty, or another terminal with kitty graphics support."
            if not support["supported"]
            else "",
            "Install `kitten` to enable terminal image artifact display."
            if kitten_path is None
            else "",
            "Inside tmux, also use tmux >= 3.3 with passthrough enabled."
            if context.env.get("TMUX")
            else "",
        )
        if step
    )

    return DiagnosticCheck(
        id="terminal.kitty_graphics",
        group="terminal",
        status=status,
        title="Kitty graphics protocol",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "supported": support["supported"],
            "reason": support["reason"],
            "kitten_resolved_path": kitten_path,
            "term": context.env.get("TERM"),
            "term_program": context.env.get("TERM_PROGRAM"),
            "kitty_window_id_set": bool(context.env.get("KITTY_WINDOW_ID")),
            "wezterm_pane_set": bool(context.env.get("WEZTERM_PANE")),
            "ghostty_resources_dir_set": bool(context.env.get("GHOSTTY_RESOURCES_DIR")),
            "inside_tmux": bool(context.env.get("TMUX")),
        },
    )


def _check_tmux_version(context: DoctorContext) -> DiagnosticCheck:
    """Check the tmux floor needed for kitty graphics passthrough."""
    tmux_path = shutil.which("tmux")
    if tmux_path is None:
        return DiagnosticCheck(
            id="tools.tmux_version",
            group="tools",
            status="SKIP",
            title="tmux passthrough version",
            summary="tmux command is unavailable; version check skipped",
            details=("`tools.tmux` reports missing tmux for ACE tmux workflows.",),
            data={
                "command": "tmux",
                "resolved_path": None,
                "version": None,
                "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
                "inside_tmux": bool(context.env.get("TMUX")),
            },
        )

    probe = _run_tmux_version_probe(tmux_path)
    if probe["probe_status"] != "ok":
        return DiagnosticCheck(
            id="tools.tmux_version",
            group="tools",
            status="WARN",
            title="tmux passthrough version",
            summary="tmux version could not be probed",
            details=(str(probe["detail"]),),
            next_steps=("Run `tmux -V` and verify tmux is healthy on PATH.",),
            data={
                "command": "tmux",
                "resolved_path": tmux_path,
                "version": None,
                "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
                "inside_tmux": bool(context.env.get("TMUX")),
                **probe,
            },
        )

    raw_version = str(probe["version"] or "")
    parsed = _parse_tmux_version(raw_version)
    if parsed is None:
        return DiagnosticCheck(
            id="tools.tmux_version",
            group="tools",
            status="WARN",
            title="tmux passthrough version",
            summary="tmux version output could not be parsed",
            details=(f"Output: {raw_version or probe['detail']}",),
            next_steps=("Run `tmux -V` and confirm tmux is >= 3.3.",),
            data={
                "command": "tmux",
                "resolved_path": tmux_path,
                "version": raw_version,
                "parsed_version": None,
                "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
                "inside_tmux": bool(context.env.get("TMUX")),
                **probe,
            },
        )

    version_ok = parsed >= _TMUX_PASSTHROUGH_MIN_VERSION
    status: CheckStatus = "OK" if version_ok else "WARN"
    summary = (
        f"tmux {raw_version} supports kitty graphics passthrough"
        if version_ok
        else f"tmux {raw_version} is older than the passthrough floor"
    )
    details = (
        (
            "Kitty graphics passthrough still requires `allow-passthrough` enabled in tmux configuration.",
        )
        if version_ok
        else (
            "Inline artifact rendering through tmux needs tmux >= 3.3 with passthrough enabled.",
        )
    )
    next_steps = (
        ()
        if version_ok
        else (
            "Upgrade tmux to 3.3 or newer and enable passthrough with `set -g allow-passthrough on`.",
        )
    )

    return DiagnosticCheck(
        id="tools.tmux_version",
        group="tools",
        status=status,
        title="tmux passthrough version",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "command": "tmux",
            "resolved_path": tmux_path,
            "version": raw_version,
            "parsed_version": list(parsed),
            "minimum_version": _format_tmux_version(_TMUX_PASSTHROUGH_MIN_VERSION),
            "inside_tmux": bool(context.env.get("TMUX")),
            **probe,
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


def _xprompt_lsp_command_source(
    command: tuple[str, ...],
    env: dict[str, str],
) -> str:
    if env.get(xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV, "").strip():
        return "SASE_XPROMPT_LSP_CMD"
    if _is_xprompt_lsp_cargo_run(command):
        return "cargo fallback"
    if len(command) != 1:
        return "command"

    path = Path(command[0])
    if path.name not in _xprompt_lsp_binary_names():
        return "command"

    python_bin_dir = Path(sys.executable).parent
    if _is_relative_to(path, python_bin_dir):
        return "current venv"

    repo_root = Path(__file__).resolve().parents[3]
    sibling_core = repo_root.parent / "sase-core"
    if _is_relative_to(path, sibling_core / "target"):
        return "sibling sase-core build"

    return "PATH"


def _is_xprompt_lsp_cargo_run(command: tuple[str, ...]) -> bool:
    return (
        len(command) >= 2
        and Path(command[0]).name == "cargo"
        and command[1] == "run"
        and "sase_xprompt_lsp" in command
    )


def _xprompt_lsp_binary_names() -> tuple[str, ...]:
    if os.name == "nt":
        return (f"{xprompt_lsp.XPROMPT_LSP_BINARY}.exe", xprompt_lsp.XPROMPT_LSP_BINARY)
    return (xprompt_lsp.XPROMPT_LSP_BINARY,)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _format_command(command: tuple[str, ...]) -> str:
    return " ".join(command)


def _kitty_graphics_support(env: dict[str, str]) -> dict[str, str | bool]:
    term = env.get("TERM", "").lower()
    term_program = env.get("TERM_PROGRAM", "").lower()
    if env.get("KITTY_WINDOW_ID") or term == "xterm-kitty":
        return {"supported": True, "reason": "kitty terminal markers are set"}
    if env.get("WEZTERM_PANE") or term_program == "wezterm" or "wezterm" in term:
        return {"supported": True, "reason": "WezTerm terminal markers are set"}
    if (
        env.get("GHOSTTY_RESOURCES_DIR")
        or term_program == "ghostty"
        or "ghostty" in term
    ):
        return {"supported": True, "reason": "Ghostty terminal markers are set"}
    return {
        "supported": False,
        "reason": "no known kitty-graphics terminal marker was found",
    }


def _run_tmux_version_probe(tmux_path: str) -> dict[str, str | int | None]:
    try:
        result = subprocess.run(
            [tmux_path, "-V"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "probe_status": "timeout",
            "detail": f"`tmux -V` timed out after {_VERSION_TIMEOUT_SECONDS:g}s",
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


def _parse_tmux_version(output: str) -> tuple[int, int] | None:
    match = _TMUX_VERSION_RE.search(output)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2) or "0"))


def _format_tmux_version(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


__all__ = [
    "deep_check_specs",
]

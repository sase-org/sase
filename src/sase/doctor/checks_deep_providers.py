"""Deep provider CLI version checks for ``sase doctor``."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_providers import optional_str, providers_from_payload
from sase.llm_provider import registry as llm_registry

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_VERSION_TIMEOUT_SECONDS = 2.0

# Three unrelated tools compete for the "grok" executable name on PATH:
# xAI's Grok Build, an unrelated `grok-dev`, and Homebrew's deprecated
# `grok` regex tool. Autodetect only checks PATH presence, so an explicit
# `llm_provider.provider: grok` can silently launch the wrong binary. This
# doctor-level advisory checks the resolved `grok` executable's `--version`
# output against Grok Build's real shape — `grok 1.0.3 (1a29d5bc12) [stable]`
# **[verified]** — rather than a loose substring, since neither competitor's
# name alone rules it out. The same collision is called out in
# `_grok_executable_not_found_error` for the not-found/failure path.
_GROK_VERSION_RE = re.compile(
    r"^grok \d+\.\d+\.\d+ \([0-9a-f]+\) \[[a-z]+\]", re.IGNORECASE
)


def check_provider_cli_versions(context: DoctorContext) -> DiagnosticCheck:
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

    providers = providers_from_payload(payload)
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
    _apply_grok_identity_advisory(rows)
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


def _apply_grok_identity_advisory(rows: list[dict[str, Any]]) -> None:
    """Flag a resolved `grok` executable that doesn't look like Grok Build."""
    row = next((r for r in rows if r["provider"] == "grok"), None)
    if row is None or row["probe_status"] != "ok":
        return
    version_text = str(row.get("version") or "").strip()
    if _GROK_VERSION_RE.match(version_text):
        return
    row["probe_status"] = "identity_mismatch"
    row["detail"] = (
        f"{row['executable']} does not identify as Grok Build (got "
        f"{row['version']!r}); likely `grok-dev` or Homebrew's deprecated "
        "`grok` regex tool — set SASE_GROK_PATH to the @xai-official/grok binary"
    )


def _provider_cli_version_row(
    context: DoctorContext,
    provider: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    cli_name = optional_str(metadata.get("autodetect_cli_name"))
    env_var = llm_registry.provider_path_env_var(provider)
    configured_command = optional_str(context.env.get(env_var))
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

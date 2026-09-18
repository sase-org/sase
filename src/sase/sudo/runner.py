"""External sudo runner invocation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.notification_gates.models import GateError


_RUNNER_COMMAND = "sase_sudo_runner"
_DETACHED_EXECUTION_CAPABILITY = "detached_execution"
_CAPABILITIES_TIMEOUT_SECONDS = 5.0
_RUNNER_EXIT_CODES = {
    10: "authentication_failed",
    11: "cancelled",
    12: "tty_required",
    13: "invalid_runner_input",
    14: "runner_failed",
}


def run_sudo_runner(
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Invoke the installed runner with the reviewed manifest."""
    fd, path = tempfile.mkstemp(prefix="sase-sudo-", suffix=".json")
    manifest_path = Path(path)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(manifest), handle, sort_keys=True)
            handle.write("\n")
        return run_sudo_runner_file(
            manifest_path,
            manifest_sha256=manifest_sha256,
            timeout_seconds=timeout_seconds,
        )
    finally:
        try:
            manifest_path.unlink()
        except FileNotFoundError:
            pass


def run_sudo_runner_file(
    manifest_path: Path | str,
    *,
    manifest_sha256: str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Invoke the installed runner against a sealed manifest file."""
    return _run_sudo_runner_argv(
        [
            _resolve_runner_executable(),
            "--manifest",
            str(manifest_path),
            "--expected-sha256",
            manifest_sha256,
        ],
        timeout_seconds=timeout_seconds,
    )


def run_sudo_runner_detached(
    manifest_path: Path | str,
    *,
    manifest_sha256: str,
    detach_dir: Path | str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Invoke the installed runner in auth-then-spawn detach mode."""
    return _run_sudo_runner_argv(
        [
            _resolve_runner_executable(),
            "--manifest",
            str(manifest_path),
            "--expected-sha256",
            manifest_sha256,
            "--detach-dir",
            str(detach_dir),
        ],
        timeout_seconds=timeout_seconds,
    )


def _probe_sudo_runner_capabilities() -> tuple[str, ...]:
    """Return advertised runner capabilities, or empty when the probe fails."""
    runner = _resolve_runner_executable()
    try:
        completed = subprocess.run(
            [runner, "--capabilities"],
            check=False,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            text=True,
            timeout=_CAPABILITIES_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise _runner_unavailable_error() from exc
    except OSError:
        return ()
    except subprocess.TimeoutExpired:
        return ()
    return _parse_capabilities(completed.stdout)


def runner_supports_detached_execution() -> bool:
    """Return whether the installed runner advertises detached execution."""
    return _DETACHED_EXECUTION_CAPABILITY in _probe_sudo_runner_capabilities()


def _parse_capabilities(stdout: str) -> tuple[str, ...]:
    if not stdout.strip():
        return ()
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return ()
    if not isinstance(value, dict):
        return ()
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, list):
        return ()
    return tuple(
        item for item in capabilities if isinstance(item, str) and item.strip()
    )


def _run_sudo_runner_argv(
    argv: list[str],
    *,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            stderr=None,
            stdout=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise _runner_unavailable_error() from exc
    except subprocess.TimeoutExpired as exc:
        raise GateError(
            "timeout",
            "sase_sudo_runner",
            "sudo runner timed out; the gate remains pending",
        ) from exc
    except KeyboardInterrupt as exc:
        raise GateError(
            "cancelled",
            "sase_sudo_runner",
            "sudo authentication was cancelled; the gate remains pending",
        ) from exc
    value = _runner_json(completed.stdout)
    if value is not None:
        return value
    if completed.returncode != 0:
        code = _RUNNER_EXIT_CODES.get(completed.returncode, "runner_failed")
        message = f"runner exited {completed.returncode}; the gate remains pending"
        raise GateError(code, "sase_sudo_runner", message)
    raise GateError(
        "invalid_runner_output",
        "sase_sudo_runner",
        "runner stdout must contain one JSON ledger",
    )


def _runner_json(stdout: str) -> dict[str, Any] | None:
    if not stdout.strip():
        return None
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GateError(
            "invalid_runner_output",
            "sase_sudo_runner",
            "runner stdout must contain one JSON ledger",
        ) from exc
    if not isinstance(value, dict):
        raise GateError(
            "invalid_runner_output",
            "sase_sudo_runner",
            "runner ledger must be an object",
        )
    return value


def _resolve_runner_executable() -> str:
    venv_runner = Path(sys.executable).parent / _RUNNER_COMMAND
    if venv_runner.is_file():
        return str(venv_runner)
    path_runner = shutil.which(_RUNNER_COMMAND)
    if path_runner:
        return path_runner
    raise _runner_unavailable_error()


def _runner_unavailable_error() -> GateError:
    venv_runner = Path(sys.executable).parent / _RUNNER_COMMAND
    return GateError(
        "runner_unavailable",
        _RUNNER_COMMAND,
        (
            f"{_RUNNER_COMMAND} was not found at {venv_runner} "
            f"or by looking up {_RUNNER_COMMAND!r} on PATH"
        ),
    )


__all__ = [
    "run_sudo_runner",
    "run_sudo_runner_detached",
    "run_sudo_runner_file",
    "runner_supports_detached_execution",
]

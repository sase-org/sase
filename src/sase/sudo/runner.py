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
    runner = _resolve_runner_executable()
    try:
        completed = subprocess.run(
            [
                runner,
                "--manifest",
                str(manifest_path),
                "--expected-sha256",
                manifest_sha256,
            ],
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


__all__ = ["run_sudo_runner", "run_sudo_runner_file"]

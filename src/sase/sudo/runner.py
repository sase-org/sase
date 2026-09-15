"""External sudo runner invocation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.notification_gates.models import GateError


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
    try:
        completed = subprocess.run(
            [
                "sase_sudo_runner",
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
        raise GateError(
            "runner_unavailable",
            "sase_sudo_runner",
            "sase_sudo_runner is not installed or not on PATH",
        ) from exc
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


__all__ = ["run_sudo_runner", "run_sudo_runner_file"]

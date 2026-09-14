"""External sudo runner invocation."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any

from sase.notification_gates.models import GateError


def run_sudo_runner(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke the installed runner with the reviewed manifest."""
    try:
        completed = subprocess.run(
            ["sase_sudo_runner"],
            input=json.dumps(dict(manifest), sort_keys=True) + "\n",
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GateError(
            "runner_unavailable",
            "sase_sudo_runner",
            "sase_sudo_runner is not installed or not on PATH",
        ) from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or f"runner exited {completed.returncode}"
        raise GateError("runner_failed", "sase_sudo_runner", message)
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(
            "invalid_runner_output",
            "sase_sudo_runner",
            "runner stdout must contain one JSON receipt",
        ) from exc
    if not isinstance(value, dict):
        raise GateError(
            "invalid_runner_output",
            "sase_sudo_runner",
            "runner receipt must be an object",
        )
    return value


__all__ = ["run_sudo_runner"]

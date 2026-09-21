"""Guarded command execution for native lifecycle operations."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence

from sase.core.state_write_guard import pytest_context_detected
from sase.service.platform_models import (
    SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV,
    CommandResult,
)


def service_lifecycle_blocked_in_tests(
    environ: Mapping[str, str] | None = None,
) -> bool:
    effective_environ = os.environ if environ is None else environ
    if effective_environ.get(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV) == "1":
        return False
    return pytest_context_detected(effective_environ)


def default_runner(argv: Sequence[str]) -> CommandResult:
    if service_lifecycle_blocked_in_tests():
        return CommandResult(
            returncode=125,
            stderr=SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE,
        )
    try:
        result = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError as exc:
        return CommandResult(returncode=127, stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_process_output_text(exc.stdout),
            stderr=_process_output_text(exc.stderr) or "timed out",
        )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def require_ok(result: CommandResult, action: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        raise RuntimeError(f"{action} failed: {detail}")
    raise RuntimeError(f"{action} failed with exit {result.returncode}")


def _process_output_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value

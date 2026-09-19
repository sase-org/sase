"""Diagnostics for a missing or broken remote sudo CLI."""

from __future__ import annotations

import subprocess
from typing import Any

from sase.sudo.models import contains_credential_shape

_REMOTE_OUTPUT_DETAIL_LIMIT = 1200
_SSH_TRANSPORT_FAILURE = 255
_UNSAFE_OUTPUT_MARKERS = ("password", "passphrase", "pam_")


def unavailable_remote_cli_message(
    host: str, completed: subprocess.CompletedProcess[Any]
) -> str:
    """Return a pending-gate diagnostic for a missing or broken target CLI."""
    if completed.returncode == _SSH_TRANSPORT_FAILURE:
        message = f"could not reach sudo target {host!r}"
    else:
        message = (
            f"could not resolve sudo target CLI on {host!r} "
            "through the remote login environment"
        )
    message += f" (exit {completed.returncode})"
    detail = _safe_stdio_detail(completed)
    if detail:
        message += f": {detail}"
    if _missing_sase_output(completed):
        message += "; check that `sase` is installed in the remote login environment"
    return message


def _missing_sase_output(completed: subprocess.CompletedProcess[Any]) -> bool:
    output = "\n".join(
        (_stream_text(completed.stderr), _stream_text(completed.stdout))
    ).lower()
    return (
        completed.returncode == 127
        or "command not found" in output
        or "sase: not found" in output
        or "exec: sase: not found" in output
    )


def _safe_stdio_detail(completed: subprocess.CompletedProcess[Any]) -> str:
    parts = []
    for label, output in (("stderr", completed.stderr), ("stdout", completed.stdout)):
        text = _stream_text(output).strip()
        if not text or _unsafe_remote_output(text):
            continue
        parts.append(f"{label}: {_bounded_output(text)!r}")
    return "; ".join(parts)


def _unsafe_remote_output(text: str) -> bool:
    lowered = text.lower()
    return contains_credential_shape(text) or any(
        marker in lowered for marker in _UNSAFE_OUTPUT_MARKERS
    )


def _stream_text(output: object) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output)


def _bounded_output(text: str) -> str:
    if len(text) <= _REMOTE_OUTPUT_DETAIL_LIMIT:
        return text
    return text[:_REMOTE_OUTPUT_DETAIL_LIMIT] + "...<truncated>"


__all__ = ["unavailable_remote_cli_message"]

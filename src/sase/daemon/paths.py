"""Path and environment helpers for the local SASE daemon."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def default_socket_path(
    *,
    sase_home: str | Path | None = None,
    host_identity: str | None = None,
) -> Path:
    home = _default_sase_home() if sase_home is None else Path(sase_home)
    host = _sanitize_host_identity(
        host_identity if host_identity is not None else os.environ.get("HOSTNAME")
    )
    return home / "run" / host / "sase-daemon.sock"


def daemon_disabled(args: Any | None = None) -> bool:
    """Shared hook for future commands that expose ``--no-daemon``."""
    arg_value = bool(getattr(args, "no_daemon", False)) if args is not None else False
    env_value = os.environ.get("SASE_NO_DAEMON", "").strip().lower()
    return arg_value or env_value in {"1", "true", "yes", "on"}


def _default_sase_home() -> Path:
    if value := os.environ.get("SASE_HOME"):
        return Path(value)
    if value := os.environ.get("HOME"):
        return Path(value) / ".sase"
    return Path(".sase")


def _sanitize_host_identity(value: str | None) -> str:
    if value is None or not value.strip():
        return "sase-host"
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in ".-_") else "-"
        for ch in value.strip()
    ).strip("-")
    return sanitized or "sase-host"

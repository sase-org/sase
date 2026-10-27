"""Classify a CLI invocation without retaining identity or terminal data."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from collections.abc import Mapping
from typing import Protocol, cast


class _TtyStream(Protocol):
    def isatty(self) -> bool: ...


def classify_actor(
    environ: Mapping[str, str] | None = None,
    *,
    stdin: object | None = None,
    stderr: object | None = None,
) -> tuple[str, str]:
    """Return the closed actor and via enums for one CLI invocation."""
    env = os.environ if environ is None else environ
    agent_marked = any(
        _clean(env.get(name)) is not None
        for name in (
            "SASE_AGENT",
            "SASE_AGENT_NAME",
            "SASE_MONITOR_ID",
            "SASE_GATE_COMMAND",
        )
    ) or _agent_meta_present(env)
    if agent_marked:
        return "agent", "cli"

    if any(
        _clean(env.get(name)) is not None
        for name in (
            "SASE_JOB_ROUTINE",
            "SASE_JOB_RUN_ID",
            "SASE_SERVICE_UNIT",
            "SASE_PROC_ID",
        )
    ):
        return "automation", "auto"

    client = (_clean(env.get("SASE_CLIENT")) or "").lower()
    if client == "nvim":
        return "human", "editor"
    if client == "telegram":
        return "human", "chat"

    if _is_tty(sys.stdin if stdin is None else stdin) or _is_tty(
        sys.stderr if stderr is None else stderr
    ):
        return "human", "cli"
    return "unknown", "cli"


def _agent_meta_present(environ: Mapping[str, str]) -> bool:
    """Mirror the identity helper's metadata fallback without importing it."""
    artifacts_dir = _clean(environ.get("SASE_ARTIFACTS_DIR"))
    if artifacts_dir is None:
        return False
    try:
        data = json.loads(
            (Path(artifacts_dir).expanduser() / "agent_meta.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, Mapping):
        return False
    return any(
        isinstance(data.get(key), str) and _clean(data.get(key)) is not None
        for key in ("name", "workflow_name", "agent_name")
    )


def _clean(value: str | None) -> str | None:
    return value.strip() if value is not None and value.strip() else None


def _is_tty(stream: object) -> bool:
    try:
        return bool(cast(_TtyStream, stream).isatty())
    except (AttributeError, OSError, ValueError):
        return False


__all__ = ["classify_actor"]

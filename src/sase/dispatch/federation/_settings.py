"""Resolution of local federation-worker supervision settings."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from ._constants import FEDERATION_MAX_FRAME_BYTES, FEDERATION_WORKER_SOCKET


@dataclass(frozen=True)
class FederationWorkerSettings:
    """Resolved non-secret worker supervision settings."""

    enabled: bool = True
    command: tuple[str, ...] = ()
    sase_home: Path = field(default_factory=sase_home)
    run_root: Path | None = None
    socket_path: Path | None = None
    idle_timeout_seconds: float = 300.0
    startup_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 5.0
    max_frame_bytes: int = FEDERATION_MAX_FRAME_BYTES

    @property
    def resolved_run_root(self) -> Path:
        return self.run_root or self.sase_home / "run" / _host_identity()

    @property
    def resolved_socket_path(self) -> Path:
        return self.socket_path or self.resolved_run_root / FEDERATION_WORKER_SOCKET


def resolve_worker_settings(raw: Mapping[str, Any]) -> FederationWorkerSettings:
    sase_home_value = _optional_path(raw.get("sase_home")) or sase_home()
    run_root = _optional_path(raw.get("run_root"))
    socket_path = _optional_path(raw.get("socket_path"))
    return FederationWorkerSettings(
        enabled=bool(raw.get("enabled", True)),
        command=_command_value(raw.get("command")),
        sase_home=sase_home_value,
        run_root=run_root,
        socket_path=socket_path,
        idle_timeout_seconds=_positive_float(raw.get("idle_timeout_seconds"), 300.0),
        startup_timeout_seconds=_positive_float(
            raw.get("startup_timeout_seconds"), 5.0
        ),
        request_timeout_seconds=_positive_float(
            raw.get("request_timeout_seconds"), 5.0
        ),
        max_frame_bytes=_positive_int(
            raw.get("max_frame_bytes"), FEDERATION_MAX_FRAME_BYTES
        ),
    )


def resolve_timeout(value: float | None, default: float) -> float:
    return _positive_float(value, default)


def _host_identity() -> str:
    raw = os.environ.get("HOSTNAME", "sase-host")
    sanitized = "".join(
        char if (char.isascii() and (char.isalnum() or char in ".-_")) else "-"
        for char in raw.strip()
    ).strip("-")
    return sanitized or "sase-host"


def _command_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value)) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(str(part) for part in value if str(part).strip())
    return ()


def _optional_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value.expanduser()
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _positive_int(value: Any, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default

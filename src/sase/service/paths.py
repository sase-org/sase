"""Machine-local paths for the sase service host."""

from __future__ import annotations

from os import PathLike
from pathlib import Path

from sase.core.paths import sase_home as _sase_home


def service_dir(sase_home: str | PathLike[str] | None = None) -> Path:
    """Return the machine-local service state directory."""
    home = _sase_home() if sase_home is None else Path(sase_home).expanduser()
    return home / "service"


def service_state_path(sase_home: str | PathLike[str] | None = None) -> Path:
    """Return the locked service state JSON path."""
    return service_dir(sase_home) / "state.json"


def service_status_path(sase_home: str | PathLike[str] | None = None) -> Path:
    """Return the atomic service status snapshot JSON path."""
    return service_dir(sase_home) / "status.json"


__all__ = ["service_dir", "service_state_path", "service_status_path"]

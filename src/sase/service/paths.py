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


def service_host_lock_path(sase_home: str | PathLike[str] | None = None) -> Path:
    """Return the foreground service-host lifetime lock path."""
    return service_dir(sase_home) / "host.lock"


def service_host_start_lock_path(sase_home: str | PathLike[str] | None = None) -> Path:
    """Return the short-lived lock that converges concurrent detached starts."""
    return service_dir(sase_home) / "start.lock"


def service_host_log_path(sase_home: str | PathLike[str] | None = None) -> Path:
    """Return the detached service-host stdout/stderr log path."""
    return service_dir(sase_home) / "host.log"


def _service_procs_dir(sase_home: str | PathLike[str] | None = None) -> Path:
    """Return the root for per-service-proc runtime directories."""
    return service_dir(sase_home) / "procs"


def service_proc_dir(
    name: str,
    sase_home: str | PathLike[str] | None = None,
) -> Path:
    """Return the runtime directory for one named service proc."""
    return _service_procs_dir(sase_home) / name


def service_proc_output_log_path(
    name: str,
    sase_home: str | PathLike[str] | None = None,
) -> Path:
    """Return the stable bounded combined-output log for one service proc."""
    return service_proc_dir(name, sase_home) / "output.log"


__all__ = [
    "service_dir",
    "service_host_lock_path",
    "service_host_log_path",
    "service_host_start_lock_path",
    "service_proc_dir",
    "service_proc_output_log_path",
    "service_state_path",
    "service_status_path",
]

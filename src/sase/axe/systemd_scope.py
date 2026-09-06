"""Best-effort systemd scope support for the AXE orchestrator."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path


AXE_SYSTEMD_SCOPE_DISABLE_ENV = "SASE_AXE_DISABLE_SYSTEMD_SCOPE"
AXE_SYSTEMD_SCOPE_PREFIX = "sase-axe"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _systemd_run_path() -> str | None:
    """Return ``systemd-run`` when AXE scope isolation can be attempted."""
    if sys.platform != "linux":
        return None
    if os.environ.get(AXE_SYSTEMD_SCOPE_DISABLE_ENV, "").strip().lower() in _TRUTHY:
        return None
    return shutil.which("systemd-run")


def wrap_axe_start_in_systemd_scope(command: list[str]) -> tuple[list[str], bool]:
    """Wrap an AXE start command in a unique transient user scope when possible."""
    systemd_run = _systemd_run_path()
    if systemd_run is None:
        return command, False

    uniquifier = f"{os.getpid()}-{time.time_ns()}"
    return (
        [
            systemd_run,
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            f"--unit={AXE_SYSTEMD_SCOPE_PREFIX}-{uniquifier}",
            "--description=SASE axe orchestrator",
            "--",
            *command,
        ],
        True,
    )


def _process_systemd_scope(pid: int, *, proc_root: Path = Path("/proc")) -> str | None:
    """Return the process's cgroup-v2 systemd scope unit, when parseable."""
    if pid <= 0:
        return None
    try:
        cgroup = (proc_root / str(pid) / "cgroup").read_text()
    except (OSError, UnicodeError):
        return None

    for line in cgroup.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3 or fields[0] != "0" or fields[1] != "":
            continue
        for component in reversed(fields[2].split("/")):
            if component.endswith(".scope"):
                return component
        return None
    return None


def unsafe_axe_systemd_scope(
    pid: int,
    *,
    proc_root: Path = Path("/proc"),
) -> str | None:
    """Return a non-AXE scope that can die with its launching session."""
    if _systemd_run_path() is None:
        return None
    scope = _process_systemd_scope(pid, proc_root=proc_root)
    if scope is None or scope.startswith(AXE_SYSTEMD_SCOPE_PREFIX):
        return None
    return scope


__all__ = [
    "AXE_SYSTEMD_SCOPE_DISABLE_ENV",
    "AXE_SYSTEMD_SCOPE_PREFIX",
    "unsafe_axe_systemd_scope",
    "wrap_axe_start_in_systemd_scope",
]

"""Best-effort cgroup escape support for long-lived detached SASE work."""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DETACH_SCOPE_DISABLE_ENV = "SASE_DETACH_SCOPE_DISABLE"
LEGACY_AXE_SYSTEMD_SCOPE_DISABLE_ENV = "SASE_AXE_DISABLE_SYSTEMD_SCOPE"
SASE_AXE_SCOPE_PREFIX = "sase-axe"
SASE_SERVICE_UNIT = "sase.service"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_UNIT_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class _DetachScopeCommand:
    """Command and process-session policy for one detached launch."""

    argv: list[str]
    start_new_session: bool
    escaped: bool = False
    method: str | None = None
    parent_unit: str | None = None


def detach_scope(
    argv: Sequence[str],
    *,
    description: str,
    unit_prefix: str,
    start_new_session: bool = True,
    proc_root: Path = Path("/proc"),
) -> _DetachScopeCommand:
    """Return a detach command escaped from SASE's service cgroup when needed."""

    command = [str(part) for part in argv]
    if _detach_scope_disabled():
        return _DetachScopeCommand(command, start_new_session=start_new_session)

    if sys.platform == "darwin":
        return _DetachScopeCommand(
            command,
            start_new_session=True,
            escaped=True,
            method="setsid",
        )

    if sys.platform != "linux":
        return _DetachScopeCommand(command, start_new_session=start_new_session)

    parent_unit = _current_systemd_unit(proc_root=proc_root)
    if not _is_sase_owned_systemd_unit(parent_unit):
        return _DetachScopeCommand(
            command,
            start_new_session=start_new_session,
            parent_unit=parent_unit,
        )

    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        return _DetachScopeCommand(
            command,
            start_new_session=start_new_session,
            parent_unit=parent_unit,
        )

    unit_name = _scope_unit_name(unit_prefix)
    return _DetachScopeCommand(
        [
            systemd_run,
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            f"--unit={unit_name}",
            f"--description={description}",
            "--",
            *command,
        ],
        start_new_session=start_new_session,
        escaped=True,
        method="systemd-run",
        parent_unit=parent_unit,
    )


def _current_systemd_unit(*, proc_root: Path = Path("/proc")) -> str | None:
    """Return the current process's systemd unit/scope name when parseable."""

    return _process_systemd_unit(os.getpid(), proc_root=proc_root)


def _process_systemd_unit(
    pid: int,
    *,
    proc_root: Path = Path("/proc"),
) -> str | None:
    """Return a process's cgroup-v2 systemd unit/scope name when parseable."""

    if pid <= 0:
        return None
    try:
        cgroup = (proc_root / str(pid) / "cgroup").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    for line in cgroup.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3:
            continue
        unit = _unit_from_cgroup_path(fields[2])
        if unit is not None:
            return unit
    return None


def _is_sase_owned_systemd_unit(unit: str | None) -> bool:
    """Return whether *unit* is a SASE-owned systemd unit or scope."""

    if unit is None:
        return False
    if unit == SASE_SERVICE_UNIT:
        return True
    if unit.startswith(SASE_AXE_SCOPE_PREFIX) and unit.endswith(".scope"):
        return True
    return unit.startswith("sase-") and unit.endswith((".scope", ".service"))


def _unit_from_cgroup_path(path: str) -> str | None:
    for component in reversed([part for part in path.split("/") if part]):
        if component.endswith((".scope", ".service")):
            return component
    return None


def _detach_scope_disabled() -> bool:
    for name in (DETACH_SCOPE_DISABLE_ENV, LEGACY_AXE_SYSTEMD_SCOPE_DISABLE_ENV):
        if os.environ.get(name, "").strip().lower() in _TRUTHY:
            return True
    return False


def _scope_unit_name(unit_prefix: str) -> str:
    safe_prefix = _UNIT_SAFE_CHARS.sub("-", unit_prefix).strip(".-") or "sase-detached"
    uniquifier = f"{os.getpid()}-{time.time_ns()}"
    return f"{safe_prefix}-{uniquifier}"


__all__ = [
    "DETACH_SCOPE_DISABLE_ENV",
    "detach_scope",
]

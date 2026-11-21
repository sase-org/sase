"""Systemd slice placement for agent, monitor, and proc scopes.

``agent_scope.slice`` names a slice for the ``sase-agent``, ``sase-monitor``,
and ``sase-proc`` scopes that :func:`sase.detach_scope.detach_scope` creates.
Every other scope keeps the default slice. A slice systemd rejects is dropped
with a warning, so a slice problem can never block a launch.

:mod:`sase.detach_scope` imports this module lazily, on the ``systemd-run``
path only, so it stays out of the TUI's startup import closure.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time

#: Scope prefixes ``agent_scope.slice`` applies to: agent runners, monitor
#: supervisors, and proc supervisors. Every other prefix (``sase-service``,
#: ``sase-federation``, scheduler runners, ...) keeps the default slice.
WORKLOAD_SLICE_UNIT_PREFIXES = frozenset({"sase-agent", "sase-monitor", "sase-proc"})
#: A systemd slice name: dash-separated non-empty parts ending in ``.slice``.
_SLICE_NAME_RE = re.compile(r"^[A-Za-z0-9:_.\\]+(?:-[A-Za-z0-9:_.\\]+)*\.slice$")
_UNIT_NAME_MAX_LENGTH = 255
#: Seconds before a rejected slice is probed again in a long-lived process.
_SLICE_PROBE_RETRY_SECONDS = 300.0
_SLICE_PROBE_TIMEOUT_SECONDS = 5.0
_SLICE_PROBE_UNIT_PREFIX = "sase-slice-probe"
#: ``(systemd_run, slice) -> (accepted, monotonic probe time)``.
_slice_probe_results: dict[tuple[str, str], tuple[bool, float]] = {}

log = logging.getLogger(__name__)


def is_valid_slice_name(name: str) -> bool:
    """Return whether *name* is a usable systemd slice unit name."""

    if len(name) > _UNIT_NAME_MAX_LENGTH:
        return False
    return _SLICE_NAME_RE.fullmatch(name) is not None


def slice_cgroup_components(name: str) -> tuple[str, ...]:
    """Return the cgroup directories systemd nests slice *name* under.

    systemd treats each ``-`` as a nesting level, so ``sase-agents.slice``
    lives at ``sase.slice/sase-agents.slice`` below the manager root.
    """

    parts = name.removesuffix(".slice").split("-")
    return tuple("-".join(parts[: index + 1]) + ".slice" for index in range(len(parts)))


def configured_workload_slice() -> str | None:
    """Return the configured ``agent_scope.slice``, or ``None`` (fail-open)."""

    try:
        from sase.config._settings_system import get_agent_scope_slice

        return get_agent_scope_slice()
    except Exception:  # noqa: BLE001 - a config problem must never block a launch.
        log.warning("Ignoring agent_scope.slice: config read failed", exc_info=True)
        return None


def accepted_workload_slice(systemd_run: str, unit_prefix: str) -> str | None:
    """Return the slice a ``systemd-run`` scope for *unit_prefix* should join.

    ``None`` when the prefix is not an agent, monitor, or proc scope, when no
    slice is configured, or when systemd rejects the configured slice.
    """

    if unit_prefix not in WORKLOAD_SLICE_UNIT_PREFIXES:
        return None
    slice_name = configured_workload_slice()
    if slice_name is None or not _slice_accepted(systemd_run, slice_name):
        return None
    return slice_name


def _slice_accepted(systemd_run: str, slice_name: str) -> bool:
    """Return whether systemd starts a throwaway scope in *slice_name*.

    systemd-run refuses the whole launch (and never runs the command) when
    the slice is malformed, masked, or otherwise unusable, so the slice is
    proven once per process before any real launch uses it. A rejection is
    retried after :data:`_SLICE_PROBE_RETRY_SECONDS`.
    """

    key = (systemd_run, slice_name)
    now = time.monotonic()
    cached = _slice_probe_results.get(key)
    if cached is not None:
        accepted, probed_at = cached
        if accepted or now - probed_at < _SLICE_PROBE_RETRY_SECONDS:
            return accepted
    accepted, detail = _probe_slice(systemd_run, slice_name)
    _slice_probe_results[key] = (accepted, now)
    if not accepted:
        log.warning(
            "systemd rejected agent_scope.slice %r; launching scopes without "
            "it (retry in %ds): %s",
            slice_name,
            int(_SLICE_PROBE_RETRY_SECONDS),
            detail,
        )
    return accepted


def _probe_slice(systemd_run: str, slice_name: str) -> tuple[bool, str]:
    unit = f"{_SLICE_PROBE_UNIT_PREFIX}-{os.getpid()}-{time.time_ns()}"
    probe_argv = [
        systemd_run,
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        f"--unit={unit}",
        "--description=SASE slice probe",
        f"--slice={slice_name}",
        "--",
        "true",
    ]
    try:
        completed = subprocess.run(
            probe_argv,
            capture_output=True,
            text=True,
            timeout=_SLICE_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if completed.returncode == 0:
        return True, ""
    detail = (completed.stderr or completed.stdout or "").strip()
    return False, detail or f"exit {completed.returncode}"


__all__ = [
    "WORKLOAD_SLICE_UNIT_PREFIXES",
    "accepted_workload_slice",
    "configured_workload_slice",
    "is_valid_slice_name",
    "slice_cgroup_components",
]

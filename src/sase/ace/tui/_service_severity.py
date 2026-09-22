"""Shared service-state severity vocabulary for the CLI and the TUI.

The core emits ``running``, ``unavailable``, ``disabled``, ``stopped``,
``crash_loop``, ``backoff``, ``exited`` for procs and ``running``,
``stale``, ``starting``, ``stopped`` for the host. The invented
``failed``/``error`` tokens must not appear in any service rendering.
"""

from __future__ import annotations

from typing import Any, Literal

ServiceSeverity = Literal["ok", "warn", "fail", "muted"]

_OK_STYLE = "bold green"
_FAIL_STYLE = "bold red"
_WARN_STYLE = "bold #FFAF5F"
_MUTED_STYLE = "dim"

_PROC_FAILURE_STATES = frozenset({"crash_loop", "backoff"})


def service_proc_severity(
    state: str | None,
    desired: str | None,
    *,
    available: bool = True,
    enabled: bool = True,
    clean_exit: bool | None = None,
) -> ServiceSeverity:
    """Map a proc state plus its desired state to a severity."""
    if not available or state == "unavailable":
        return "warn"
    if not enabled or state == "disabled":
        return "muted"
    if state == "running":
        return "ok"
    if state in _PROC_FAILURE_STATES:
        return "fail"
    if state == "exited":
        if desired != "running":
            return "muted"
        if clean_exit is True:
            return "warn"
        return "fail"
    if state == "stopped":
        return "muted" if desired != "running" else "fail"
    if not state:
        return "muted" if desired != "running" else "warn"
    return "warn" if desired == "running" else "muted"


def service_proc_style(
    state: str | None,
    desired: str | None,
    *,
    available: bool = True,
    enabled: bool = True,
    clean_exit: bool | None = None,
) -> str:
    """Return the display style for a proc state."""
    severity = service_proc_severity(
        state,
        desired,
        available=available,
        enabled=enabled,
        clean_exit=clean_exit,
    )
    if severity == "ok":
        return _OK_STYLE
    if severity == "fail":
        return _FAIL_STYLE
    if severity == "warn":
        return _WARN_STYLE
    return _MUTED_STYLE


def service_proc_marker(
    state: str | None,
    desired: str | None,
    *,
    available: bool = True,
    enabled: bool = True,
    clean_exit: bool | None = None,
) -> tuple[str, str]:
    """Return the one-character proc marker and its style."""
    if not available:
        return ("?", _WARN_STYLE)
    if not enabled:
        return ("-", _MUTED_STYLE)
    severity = service_proc_severity(
        state,
        desired,
        available=available,
        enabled=enabled,
        clean_exit=clean_exit,
    )
    if state == "running":
        return ("*", _OK_STYLE)
    if severity == "fail":
        return ("!", _FAIL_STYLE)
    if severity == "warn":
        return ("~", _WARN_STYLE)
    if state == "disabled":
        return ("-", _MUTED_STYLE)
    return ("·", _MUTED_STYLE)


def proc_clean_exit(proc: Any) -> bool | None:
    """Read the restart decision's ``clean_exit`` from a proc row, if present."""
    restart = getattr(proc, "restart", None)
    if isinstance(restart, dict):
        value = restart.get("clean_exit")
        return None if value is None else bool(value)
    if restart is not None:
        value = getattr(restart, "clean_exit", None)
        return None if value is None else bool(value)
    return None


def service_host_severity(state: str | None) -> ServiceSeverity:
    """Map a host state to a severity (``starting`` is not a failure)."""
    if state == "running":
        return "ok"
    if state == "starting":
        return "warn"
    if state in ("stale", "stopped"):
        return "fail"
    if not state:
        return "warn"
    return "fail"


def service_host_style(state: str | None) -> str:
    """Return the display style for a service host state."""
    severity = service_host_severity(state)
    if severity == "ok":
        return _OK_STYLE
    if severity == "fail":
        return _FAIL_STYLE
    if severity == "warn":
        return "#FFD700"
    return _MUTED_STYLE


__all__ = [
    "ServiceSeverity",
    "proc_clean_exit",
    "service_host_severity",
    "service_host_style",
    "service_proc_marker",
    "service_proc_severity",
    "service_proc_style",
]

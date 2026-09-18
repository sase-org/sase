"""Shared service-proc action adapter for CLI and TUI callers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from sase.service.config import ServiceProcConfig, load_service_config
from sase.service.control import nudge_service_host
from sase.service.state import (
    ServiceStateMutationOutcome,
    clear_service_stop,
    record_service_stop,
    set_service_enablement,
)

ServiceProcAction = Literal["start", "stop", "restart", "enable", "disable"]


class ServiceProcActionError(RuntimeError):
    """Raised when a configured service proc action cannot be accepted."""


@dataclass(frozen=True)
class _ServiceProcActionOutcome:
    """Typed result of a service-proc control-plane action."""

    action: ServiceProcAction
    name: str
    mutations: tuple[ServiceStateMutationOutcome, ...]
    nudged: bool
    message: str

    @property
    def changed(self) -> bool:
        """Return whether any underlying Rust-owned state mutation changed data."""
        return any(mutation.changed for mutation in self.mutations)


def start_service_proc(
    name: str,
    *,
    actor: str,
    reason: str | None = None,
) -> _ServiceProcActionOutcome:
    """Clear a boot-scoped stop marker and nudge the service host."""
    del actor
    entry = _configured_proc(name, command="start")
    _require_startable(entry, command="start")
    mutation = clear_service_stop(name)
    nudged = nudge_service_host()
    detail = f" ({reason})" if reason else ""
    return _ServiceProcActionOutcome(
        action="start",
        name=name,
        mutations=(mutation,),
        nudged=nudged,
        message=f"requested service proc {name} start{detail}",
    )


def stop_service_proc(
    name: str,
    *,
    actor: str,
    reason: str | None = None,
) -> _ServiceProcActionOutcome:
    """Record a boot-scoped stop marker and nudge the service host."""
    _configured_proc(name, command="stop")
    mutation = record_service_stop(name, actor, reason=reason)
    nudged = nudge_service_host()
    return _ServiceProcActionOutcome(
        action="stop",
        name=name,
        mutations=(mutation,),
        nudged=nudged,
        message=f"requested service proc {name} stop until next boot",
    )


def restart_service_proc(
    name: str,
    *,
    actor: str,
    reason: str | None = None,
    delay: float = 0.5,
) -> _ServiceProcActionOutcome:
    """Request stop, briefly settle, clear the stop marker, and nudge both sides."""
    entry = _configured_proc(name, command="restart")
    _require_startable(entry, command="restart")
    stop = record_service_stop(name, actor, reason=reason)
    first_nudge = nudge_service_host()
    if delay > 0:
        time.sleep(delay)
    start = clear_service_stop(name)
    second_nudge = nudge_service_host()
    return _ServiceProcActionOutcome(
        action="restart",
        name=name,
        mutations=(stop, start),
        nudged=first_nudge or second_nudge,
        message=f"requested service proc {name} restart",
    )


def enable_service_proc(
    name: str,
    *,
    actor: str,
) -> _ServiceProcActionOutcome:
    """Enable a configured service proc on this machine and nudge the host."""
    _configured_proc(name, command="enable")
    mutation = set_service_enablement(name, True, actor)
    nudged = nudge_service_host()
    return _ServiceProcActionOutcome(
        action="enable",
        name=name,
        mutations=(mutation,),
        nudged=nudged,
        message=f"enabled service proc {name} for this machine",
    )


def disable_service_proc(
    name: str,
    *,
    actor: str,
) -> _ServiceProcActionOutcome:
    """Disable a configured service proc on this machine and nudge the host."""
    _configured_proc(name, command="disable")
    mutation = set_service_enablement(name, False, actor)
    nudged = nudge_service_host()
    return _ServiceProcActionOutcome(
        action="disable",
        name=name,
        mutations=(mutation,),
        nudged=nudged,
        message=f"disabled service proc {name} for this machine",
    )


def _configured_proc(name: str, *, command: str) -> ServiceProcConfig:
    config = load_service_config()
    entry = config.get(name)
    if entry is None:
        raise ServiceProcActionError(
            f"sase service proc {command}: unknown service proc {name!r}"
        )
    return entry


def _require_startable(entry: ServiceProcConfig, *, command: str) -> None:
    if entry.available:
        return
    reason = "; ".join(entry.unavailable_reasons) or "proc is unavailable"
    raise ServiceProcActionError(
        f"sase service proc {command}: service proc {entry.name!r} is unavailable: "
        f"{reason}"
    )


__all__ = [
    "ServiceProcAction",
    "ServiceProcActionError",
    "disable_service_proc",
    "enable_service_proc",
    "restart_service_proc",
    "start_service_proc",
    "stop_service_proc",
]

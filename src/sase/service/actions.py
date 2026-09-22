"""Shared service-proc action adapter for CLI and TUI callers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from sase.service.config import ServiceProcConfig, load_service_config
from sase.service.control import nudge_service_host
from sase.service.state import (
    ServiceProcRequest,
    ServiceStateMutationOutcome,
    read_service_state,
    record_service_stop,
    request_service_proc,
    set_service_enablement,
)

ServiceProcAction = Literal["start", "stop", "restart", "enable", "disable"]


class ServiceProcActionError(RuntimeError):
    """Raised when a configured service proc action cannot be accepted."""


@dataclass(frozen=True)
class ServiceProcActionOutcome:
    """Typed result of a service-proc control-plane action."""

    action: ServiceProcAction
    name: str
    mutations: tuple[ServiceStateMutationOutcome, ...]
    nudged: bool
    message: str
    generation: int | None = None

    @property
    def changed(self) -> bool:
        """Return whether any underlying Rust-owned state mutation changed data."""
        return any(mutation.changed for mutation in self.mutations)


def start_service_proc(
    name: str,
    *,
    actor: str,
    reason: str | None = None,
) -> ServiceProcActionOutcome:
    """Record a durable start request and nudge the service host."""
    entry = _configured_proc(name, command="start")
    _require_startable(entry, command="start")
    mutation = request_service_proc(name, "start", actor, reason=reason)
    nudged = nudge_service_host()
    generation = _request_generation(mutation, name)
    detail = f" ({reason})" if reason else ""
    return ServiceProcActionOutcome(
        action="start",
        name=name,
        mutations=(mutation,),
        nudged=nudged,
        message=f"requested service proc {name} start{detail}",
        generation=generation,
    )


def stop_service_proc(
    name: str,
    *,
    actor: str,
    reason: str | None = None,
) -> ServiceProcActionOutcome:
    """Record a boot-scoped stop marker and nudge the service host."""
    _configured_proc(name, command="stop")
    mutation = record_service_stop(name, actor, reason=reason)
    nudged = nudge_service_host()
    return ServiceProcActionOutcome(
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
) -> ServiceProcActionOutcome:
    """Record a durable restart request and nudge the service host."""
    entry = _configured_proc(name, command="restart")
    _require_startable(entry, command="restart")
    mutation = request_service_proc(name, "restart", actor, reason=reason)
    nudged = nudge_service_host()
    generation = _request_generation(mutation, name)
    return ServiceProcActionOutcome(
        action="restart",
        name=name,
        mutations=(mutation,),
        nudged=nudged,
        message=f"requested service proc {name} restart",
        generation=generation,
    )


def wait_for_service_proc_request(
    name: str,
    generation: int,
    *,
    timeout: float,
    poll: float = 0.2,
) -> ServiceProcRequest | None:
    """Poll state until the host confirms *generation*, or return None on timeout.

    Transient state reads never raise; they are retried until *timeout*.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            snapshot = read_service_state()
        except Exception:  # noqa: BLE001 - a transient read must not fail the wait.
            snapshot = None
        if snapshot is not None:
            request = snapshot.state.requests.get(name)
            if (
                request is not None
                and request.generation == generation
                and request.completed
            ):
                return request
        if time.monotonic() >= deadline:
            return None
        time.sleep(max(0.0, poll))


def _request_generation(mutation: ServiceStateMutationOutcome, name: str) -> int | None:
    request = mutation.snapshot.state.requests.get(name)
    return request.generation if request is not None else None


def enable_service_proc(
    name: str,
    *,
    actor: str,
) -> ServiceProcActionOutcome:
    """Enable a configured service proc on this machine and nudge the host."""
    _configured_proc(name, command="enable")
    mutation = set_service_enablement(name, True, actor)
    nudged = nudge_service_host()
    return ServiceProcActionOutcome(
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
) -> ServiceProcActionOutcome:
    """Disable a configured service proc on this machine and nudge the host."""
    _configured_proc(name, command="disable")
    mutation = set_service_enablement(name, False, actor)
    nudged = nudge_service_host()
    return ServiceProcActionOutcome(
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
    "ServiceProcActionOutcome",
    "disable_service_proc",
    "enable_service_proc",
    "restart_service_proc",
    "start_service_proc",
    "stop_service_proc",
    "wait_for_service_proc_request",
]

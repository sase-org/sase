"""Resolve sudo execution hosts without crossing the credential boundary."""

from __future__ import annotations

import socket
from dataclasses import dataclass

from sase.config import core as config_core
from sase.dispatch.ssh_target import resolve_remote_ssh_target
from sase.notification_gates.models import GateError


@dataclass(frozen=True)
class SudoExecutionTarget:
    """Concrete host facts for one sudo request."""

    host: str
    requested_machine: str | None = None
    enrolled_alias: str | None = None
    enrolled: bool = False
    remote: bool = False

    @property
    def unenrolled(self) -> bool:
        return self.remote and not self.enrolled


def _local_sudo_host() -> str:
    """Return the local host label used in Rust sudo manifests."""
    return config_core.get_machine_name() or socket.gethostname() or "local"


def resolve_sudo_target(machine: str | None) -> SudoExecutionTarget:
    """Resolve a request machine value to the SSH host that will authenticate."""
    if machine is None:
        return SudoExecutionTarget(host=_local_sudo_host())
    try:
        target = resolve_remote_ssh_target(machine)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "machine", str(exc)) from exc
    if target.enrolled:
        return SudoExecutionTarget(
            host=target.host,
            requested_machine=machine,
            enrolled_alias=target.enrolled_alias,
            enrolled=True,
            remote=True,
        )
    return SudoExecutionTarget(
        host=target.host,
        requested_machine=machine,
        remote=True,
    )


__all__ = ["SudoExecutionTarget", "resolve_sudo_target"]

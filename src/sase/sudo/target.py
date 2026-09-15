"""Resolve sudo execution hosts without crossing the credential boundary."""

from __future__ import annotations

import socket
from dataclasses import dataclass

from sase.config import core as config_core
from sase.dispatch.config import load_dispatch_config
from sase.dispatch.models import validate_ssh_target
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
    config = load_dispatch_config()
    record = config.machine_by_alias().get(machine)
    if record is not None:
        return SudoExecutionTarget(
            host=record.effective_ssh_target,
            requested_machine=machine,
            enrolled_alias=record.alias,
            enrolled=True,
            remote=True,
        )
    try:
        validate_ssh_target(machine)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "machine", str(exc)) from exc
    return SudoExecutionTarget(
        host=machine,
        requested_machine=machine,
        remote=True,
    )


__all__ = ["SudoExecutionTarget", "resolve_sudo_target"]

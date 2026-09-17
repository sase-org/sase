"""Resolve configured machine aliases into SSH targets."""

from __future__ import annotations

from dataclasses import dataclass

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.models import validate_ssh_target


@dataclass(frozen=True)
class RemoteSshTarget:
    """Concrete SSH target facts for one remote operation."""

    host: str
    requested_machine: str
    enrolled_alias: str | None = None
    enrolled: bool = False


def resolve_remote_ssh_target(machine: str) -> RemoteSshTarget:
    """Resolve an enrolled alias or validate a raw SSH destination."""
    config = load_dispatch_config()
    record = config.machine_by_alias().get(machine)
    if record is not None:
        return RemoteSshTarget(
            host=record.effective_ssh_target,
            requested_machine=machine,
            enrolled_alias=record.alias,
            enrolled=True,
        )
    validate_ssh_target(machine)
    return RemoteSshTarget(host=machine, requested_machine=machine)


__all__ = ["RemoteSshTarget", "resolve_remote_ssh_target"]

"""Python application boundary for machine-qualified agent identities.

The primitive name operations live in :mod:`sase_core_rs`.  This module keeps
configuration discovery and the application's local/foreign policy in one
place so persistence code does not reimplement hood boundary rules and TUI
callers can resolve machine identity once per loaded snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
import re
from typing import Any

from sase.config import discover_machine_names, get_machine_name
from sase.core.rust import require_rust_binding

_DISMISSED_PREFIX_RE = re.compile(r"^(\d{6}\.)(.+)$")


@dataclass(frozen=True, slots=True)
class MachineHoodIdentity:
    """Resolved local machine identity plus known machine overlays."""

    machine_name: str | None
    known_machines: tuple[str, ...] = ()

    @classmethod
    def current(cls) -> MachineHoodIdentity:
        """Resolve one identity snapshot from the current SASE config."""
        machine_name = get_machine_name()
        if machine_name is None:
            return cls(None, ())
        _validate_machine_name(machine_name)
        known = tuple(dict.fromkeys((*discover_machine_names(), machine_name)))
        return cls(machine_name, known)

    @classmethod
    def unconfigured(cls) -> MachineHoodIdentity:
        """Return the strict no-machine compatibility snapshot."""
        return cls(None, ())


def _validate_machine_name(name: str) -> None:
    """Validate *name* with the canonical Rust machine-name rules."""
    _core("validate_machine_name")(name)


def _qualify_machine_agent_name(name: str, machine_name: str) -> str:
    """Qualify *name* with *machine_name* using the canonical Rust helper."""
    return str(_core("qualify_machine_agent_name")(name, machine_name))


def _strip_machine_agent_name(name: str, machine_name: str) -> str:
    """Strip *machine_name* from *name* using the canonical Rust helper."""
    return str(_core("strip_machine_agent_name")(name, machine_name))


def _machine_hood_of(
    name: str, known_machines: tuple[str, ...] | list[str]
) -> str | None:
    """Return the known leading machine hood of *name*, when present."""
    value = _core("machine_hood_of")(name, list(known_machines))
    return str(value) if value is not None else None


def qualify_local_agent_name(
    name: str,
    identity: MachineHoodIdentity | None = None,
) -> str:
    """Return the durable local spelling of *name*.

    Known foreign names remain exact.  With no configured machine this is a
    strict no-op.  A legacy dismissal prefix stays outside the machine hood.
    """
    snapshot = identity or MachineHoodIdentity.current()
    machine_name = snapshot.machine_name
    if machine_name is None:
        return name
    prefix, core_name = _split_dismissed_prefix(name)
    hood = _machine_hood_of(core_name, snapshot.known_machines)
    if hood is not None and hood != machine_name:
        return name
    return prefix + _qualify_machine_agent_name(core_name, machine_name)


def strip_local_agent_name(
    name: str,
    identity: MachineHoodIdentity | None = None,
) -> str:
    """Return the local presentation spelling while retaining foreign hoods."""
    snapshot = identity or MachineHoodIdentity.current()
    machine_name = snapshot.machine_name
    if machine_name is None:
        return name
    prefix, core_name = _split_dismissed_prefix(name)
    return prefix + _strip_machine_agent_name(core_name, machine_name)


def known_foreign_machine(
    name: str,
    identity: MachineHoodIdentity | None = None,
) -> str | None:
    """Return the known foreign machine prefix of *name*, if any."""
    snapshot = identity or MachineHoodIdentity.current()
    if snapshot.machine_name is None:
        return None
    _prefix, core_name = _split_dismissed_prefix(name)
    hood = _machine_hood_of(core_name, snapshot.known_machines)
    if hood is None or hood == snapshot.machine_name:
        return None
    return hood


def canonical_local_agent_name_key(
    name: str,
    identity: MachineHoodIdentity | None = None,
) -> str:
    """Return the collision/lookup key shared by bare and local-qualified names."""
    return strip_local_agent_name(name, identity)


def local_agent_name_lookup_candidates(
    name: str,
    identity: MachineHoodIdentity | None = None,
) -> tuple[str, ...]:
    """Return exact-first durable candidates for a local agent reference."""
    snapshot = identity or MachineHoodIdentity.current()
    if snapshot.machine_name is None or known_foreign_machine(name, snapshot):
        return (name,)

    stripped = strip_local_agent_name(name, snapshot)
    alternate = (
        stripped if stripped != name else qualify_local_agent_name(name, snapshot)
    )
    return tuple(dict.fromkeys((name, alternate)))


def _split_dismissed_prefix(name: str) -> tuple[str, str]:
    match = _DISMISSED_PREFIX_RE.match(name)
    if match is None:
        return "", name
    return match.group(1), match.group(2)


@cache
def _core(name: str) -> Any:
    return require_rust_binding(name)


__all__ = [
    "MachineHoodIdentity",
    "canonical_local_agent_name_key",
    "known_foreign_machine",
    "local_agent_name_lookup_candidates",
    "qualify_local_agent_name",
    "strip_local_agent_name",
]

"""Narrow legacy adapter for v1 machine-qualified sidecar transport.

Locally owned names are identity-relative and must use
``sase.core.agent_identity_facade.normalize_owned_agent_name``.  The existing
v1 agents sidecar still requires ``machine.agent`` transport keys until its v2
replacement lands, so that one deprecated policy remains isolated here.
"""

from __future__ import annotations

from functools import cache
import re
from typing import Any

from sase.core.rust import require_rust_binding

_DISMISSED_PREFIX_RE = re.compile(r"^(\d{6}\.)(.+)$")


def machine_qualify_v1_transport_agent_name(
    name: str,
    machine_name: str,
) -> str:
    """Return the exact machine-qualified spelling required by v1 transport."""
    prefix, core_name = _split_dismissed_prefix(name)
    machine_prefix = f"{machine_name}."
    if core_name.startswith(machine_prefix):
        return name
    return prefix + str(_core("qualify_machine_agent_name")(core_name, machine_name))


def _split_dismissed_prefix(name: str) -> tuple[str, str]:
    match = _DISMISSED_PREFIX_RE.match(name)
    if match is None:
        return "", name
    return match.group(1), match.group(2)


@cache
def _core(name: str) -> Any:
    return require_rust_binding(name)


__all__ = ["machine_qualify_v1_transport_agent_name"]

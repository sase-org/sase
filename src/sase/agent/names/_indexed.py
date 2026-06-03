"""Indexed agent-name template helpers.

``<base>-@`` is a controlled template syntax. It allocates and resolves
concrete names of the form ``<base>-<N>``. The base may contain ordinary
single hyphens, but it cannot contain the reserved agent-family separator.
"""

from __future__ import annotations

import re
from collections.abc import Collection

from sase.plan_chain import AGENT_FAMILY_SEPARATOR

INDEXED_AGENT_NAME_MARKER = "-@"


class IndexedAgentNameError(ValueError):
    """Base class for indexed agent-name template failures."""


class InvalidIndexedAgentNameTemplateError(IndexedAgentNameError):
    """Raised when a value is not a valid ``<base>-@`` template."""

    def __init__(self, template: str, reason: str) -> None:
        self.template = template
        self.reason = reason
        super().__init__(f"Invalid indexed agent name '{template}': {reason}")


class IndexedAgentNameNotFoundError(IndexedAgentNameError):
    """Raised when no concrete indexed name exists for a template."""

    def __init__(self, template: str) -> None:
        self.template = template
        super().__init__(f"No existing indexed agent name found for '{template}'")


def is_indexed_agent_name_template(value: str) -> bool:
    """Return whether *value* uses the strict terminal ``-@`` marker."""
    return value.endswith(INDEXED_AGENT_NAME_MARKER)


def indexed_agent_name_base(template: str) -> str:
    """Return the validated base portion for a ``<base>-@`` template."""
    if not is_indexed_agent_name_template(template):
        raise InvalidIndexedAgentNameTemplateError(
            template, "expected a terminal '-@' marker"
        )

    base = template[: -len(INDEXED_AGENT_NAME_MARKER)]
    if not base:
        raise InvalidIndexedAgentNameTemplateError(template, "base cannot be empty")
    if AGENT_FAMILY_SEPARATOR in base:
        raise InvalidIndexedAgentNameTemplateError(
            template, f"base cannot contain '{AGENT_FAMILY_SEPARATOR}'"
        )
    if "@" in base:
        raise InvalidIndexedAgentNameTemplateError(template, "base cannot contain '@'")
    return base


def validate_indexed_agent_name_template(template: str) -> str:
    """Validate *template* and return its base portion."""
    return indexed_agent_name_base(template)


def allocate_indexed_agent_name(
    template: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Allocate the lowest available concrete name for *template*.

    The provided reservation set is mutated in place. When omitted, the durable
    agent-name registry supplies the initial reservations.
    """
    base = indexed_agent_name_base(template)
    pool = _reserved_names() if reserved is None else reserved
    n = 1
    while True:
        candidate = f"{base}-{n}"
        if candidate not in pool:
            pool.add(candidate)
            return candidate
        n += 1


def latest_indexed_agent_name(
    template: str,
    *,
    names: Collection[str] | None = None,
) -> str | None:
    """Return the highest existing ``<base>-<N>`` name for *template*."""
    base = indexed_agent_name_base(template)
    pool = _reserved_names() if names is None else names
    pattern = re.compile(rf"^{re.escape(base)}-([1-9][0-9]*)$")
    latest: tuple[int, str] | None = None
    for name in pool:
        match = pattern.match(name)
        if match is None:
            continue
        index = int(match.group(1))
        if latest is None or index > latest[0]:
            latest = (index, name)
    return None if latest is None else latest[1]


def is_concrete_indexed_agent_name_for_template(name: str, template: str) -> bool:
    """Return whether *name* is a concrete ``<base>-<N>`` for *template*."""
    base = indexed_agent_name_base(template)
    return re.match(rf"^{re.escape(base)}-[1-9][0-9]*$", name) is not None


def require_latest_indexed_agent_name(
    template: str,
    *,
    names: Collection[str] | None = None,
) -> str:
    """Return the latest concrete name for *template* or raise a typed error."""
    latest = latest_indexed_agent_name(template, names=names)
    if latest is None:
        raise IndexedAgentNameNotFoundError(template)
    return latest


def resolve_indexed_agent_name_reference(name: str) -> str:
    """Resolve ``<base>-@`` to the latest concrete name, otherwise return *name*."""
    if not is_indexed_agent_name_template(name):
        return name
    return require_latest_indexed_agent_name(name)


def _reserved_names() -> set[str]:
    from sase.agent.names._registry import get_reserved_agent_names

    return get_reserved_agent_names()

"""Compatibility wrappers for legacy indexed agent-name templates.

The old public API was named around terminal ``<base>-@`` templates. The
runtime now treats any single ``@`` marker as an agent-name template, so these
helpers delegate to the generic template implementation while keeping the
legacy names importable during the migration.
"""

from __future__ import annotations

from collections.abc import Collection

from sase.plan_chain import AGENT_FAMILY_SEPARATOR
from sase.agent.names._templates import (
    AgentNameTemplateError,
    AgentNameTemplateNotFoundError,
    InvalidAgentNameTemplateError,
    agent_name_template_base,
    allocate_agent_name_template,
    is_agent_name_template,
    latest_agent_name_template,
    match_agent_name_template,
    parse_agent_name_template,
    render_agent_name_template,
)

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
    """Return whether *value* is a single-marker agent-name template."""
    return is_agent_name_template(value)


def indexed_agent_name_base(template: str) -> str:
    """Return a stable compatibility base for an agent-name template."""
    try:
        parse_agent_name_template(template)
        rendered = render_agent_name_template(template, "0")
    except AgentNameTemplateError as exc:
        raise InvalidIndexedAgentNameTemplateError(template, _reason(exc)) from exc
    if AGENT_FAMILY_SEPARATOR in rendered:
        raise InvalidIndexedAgentNameTemplateError(
            template, f"rendered name cannot contain '{AGENT_FAMILY_SEPARATOR}'"
        )
    return agent_name_template_base(template)


def validate_indexed_agent_name_template(template: str) -> str:
    """Validate *template* and return its base portion."""
    return indexed_agent_name_base(template)


def allocate_indexed_agent_name(
    template: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Allocate the lowest available concrete name for *template*."""
    try:
        return allocate_agent_name_template(template, reserved=reserved)
    except InvalidAgentNameTemplateError as exc:
        raise InvalidIndexedAgentNameTemplateError(template, exc.reason) from exc


def latest_indexed_agent_name(
    template: str,
    *,
    names: Collection[str] | None = None,
) -> str | None:
    """Return the highest existing concrete name for *template*."""
    try:
        return latest_agent_name_template(template, names=names)
    except InvalidAgentNameTemplateError as exc:
        raise InvalidIndexedAgentNameTemplateError(template, exc.reason) from exc


def is_concrete_indexed_agent_name_for_template(name: str, template: str) -> bool:
    """Return whether *name* is a concrete rendering for *template*."""
    try:
        return match_agent_name_template(template, name) is not None
    except InvalidAgentNameTemplateError:
        return False


def require_latest_indexed_agent_name(
    template: str,
    *,
    names: Collection[str] | None = None,
) -> str:
    """Return the latest concrete name for *template* or raise a typed error."""
    try:
        latest = latest_agent_name_template(template, names=names)
    except AgentNameTemplateNotFoundError as exc:
        raise IndexedAgentNameNotFoundError(template) from exc
    except InvalidAgentNameTemplateError as exc:
        raise InvalidIndexedAgentNameTemplateError(template, exc.reason) from exc
    if latest is None:
        raise IndexedAgentNameNotFoundError(template)
    return latest


def resolve_indexed_agent_name_reference(name: str) -> str:
    """Resolve ``<base>-@`` to the latest concrete name, otherwise return *name*."""
    if not is_indexed_agent_name_template(name):
        return name
    return require_latest_indexed_agent_name(name)


def _reason(exc: AgentNameTemplateError) -> str:
    return getattr(exc, "reason", str(exc))

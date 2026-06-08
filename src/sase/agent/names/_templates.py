"""Generic agent-name template helpers backed by ``sase_core_rs``."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from functools import cache
from typing import Any

AGENT_NAME_TEMPLATE_MARKER = "@"
_TOKEN_BATCH_SIZE = 256


class AgentNameTemplateError(ValueError):
    """Base class for agent-name template failures."""


class InvalidAgentNameTemplateError(AgentNameTemplateError):
    """Raised when a value is not a valid one-marker template."""

    def __init__(self, template: str, reason: str) -> None:
        self.template = template
        self.reason = reason
        super().__init__(f"Invalid agent name template '{template}': {reason}")


class InvalidAgentNameTemplateTokenError(AgentNameTemplateError):
    """Raised when a template token is not in the auto-name sequence."""

    def __init__(self, token: str, reason: str) -> None:
        self.token = token
        self.reason = reason
        super().__init__(f"Invalid agent name template token '{token}': {reason}")


class AgentNameTemplateNotFoundError(AgentNameTemplateError):
    """Raised when no concrete name exists for a template."""

    def __init__(self, template: str) -> None:
        self.template = template
        super().__init__(f"No existing agent name found for template '{template}'")


@dataclass(frozen=True)
class AgentNameTemplate:
    """Parsed one-marker agent-name template."""

    template: str
    prefix: str
    suffix: str


def is_agent_name_template(value: str) -> bool:
    """Return whether *value* contains exactly one ``@`` marker."""
    return bool(_core("is_agent_name_template")(value))


def parse_agent_name_template(template: str) -> AgentNameTemplate:
    """Parse *template* into prefix/suffix components."""
    try:
        payload = _core("parse_agent_name_template")(template)
    except ValueError as exc:
        raise _template_error(template, exc) from exc
    return AgentNameTemplate(
        template=str(payload["template"]),
        prefix=str(payload["prefix"]),
        suffix=str(payload["suffix"]),
    )


def agent_name_template_base(template: str) -> str:
    """Return a stable legacy reference base for *template*.

    This is a compatibility helper for call sites that used the old
    ``<base>-@`` template base as a display/context key. It is not used for
    allocation semantics.
    """
    parse_agent_name_template(template)
    base = template.replace(AGENT_NAME_TEMPLATE_MARKER, "")
    base = re.sub(r"([.-])\1+", r"\1", base).strip(".-")
    return base or template


def render_agent_name_template(template: str, token: str) -> str:
    """Render *template* by replacing ``@`` with *token*."""
    try:
        return str(_core("render_agent_name_template")(template, token))
    except ValueError as exc:
        raise _value_error(template, token, exc) from exc


def match_agent_name_template(template: str, concrete: str) -> str | None:
    """Return the template token in *concrete*, or ``None`` if it does not match."""
    try:
        token = _core("match_agent_name_template")(template, concrete)
    except ValueError as exc:
        raise _template_error(template, exc) from exc
    return None if token is None else str(token)


def compare_agent_name_template_tokens(left: str, right: str) -> int:
    """Compare two tokens by auto-sequence order."""
    try:
        return int(_core("compare_agent_name_template_tokens")(left, right))
    except ValueError as exc:
        raise _token_error(left, exc) from exc


def iter_agent_name_template_tokens() -> Iterator[str]:
    """Yield template tokens in auto-name sequence order."""
    after: str | None = None
    while True:
        batch = _core("agent_name_template_tokens_after")(after, _TOKEN_BATCH_SIZE)
        if not batch:
            raise AssertionError("token generator returned an empty batch")
        for token in batch:
            yield str(token)
        after = str(batch[-1])


def allocate_agent_name_template(
    template: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Allocate the lowest available concrete name for *template*.

    The provided reservation set is mutated in place. When omitted, the durable
    agent-name registry supplies the initial reservations.
    """
    # Validate the template before loading the registry so syntax errors stay
    # independent of local agent state.
    parse_agent_name_template(template)
    pool = _reserved_names() if reserved is None else reserved
    for token in iter_agent_name_template_tokens():
        candidate = render_agent_name_template(template, token)
        if candidate not in pool:
            pool.add(candidate)
            return candidate
    raise AssertionError("unreachable")


def latest_agent_name_template(
    template: str,
    *,
    names: Collection[str] | None = None,
) -> str | None:
    """Return the highest existing concrete name matching *template*."""
    parse_agent_name_template(template)
    pool = _reserved_names() if names is None else names
    latest: tuple[str, str] | None = None
    for name in pool:
        token = match_agent_name_template(template, name)
        if token is None:
            continue
        if latest is None or compare_agent_name_template_tokens(latest[0], token) < 0:
            latest = (token, name)
    return None if latest is None else latest[1]


def require_latest_agent_name_template(
    template: str,
    *,
    names: Collection[str] | None = None,
) -> str:
    """Return the latest concrete name for *template* or raise a typed error."""
    latest = latest_agent_name_template(template, names=names)
    if latest is None:
        raise AgentNameTemplateNotFoundError(template)
    return latest


@cache
def _core(name: str) -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding(name)


def _reserved_names() -> set[str]:
    from sase.agent.names._registry import get_reserved_agent_names

    return get_reserved_agent_names()


def _value_error(
    template: str,
    token: str,
    exc: ValueError,
) -> AgentNameTemplateError:
    message = str(exc)
    if "template token" in message:
        return _token_error(token, exc)
    return _template_error(template, exc)


def _template_error(template: str, exc: ValueError) -> InvalidAgentNameTemplateError:
    return InvalidAgentNameTemplateError(template, _reason(str(exc)))


def _token_error(token: str, exc: ValueError) -> InvalidAgentNameTemplateTokenError:
    return InvalidAgentNameTemplateTokenError(token, _reason(str(exc)))


def _reason(message: str) -> str:
    if ": " in message:
        return message.rsplit(": ", 1)[-1]
    return message

"""Generic agent-name template helpers backed by ``sase_core_rs``."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    current_owner_agent_name_key,
    normalize_owned_agent_name,
    present_agent_name,
)

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


@dataclass
class AgentNameNamespaceReservationIndex:
    """Exact-name and dotted-namespace reservation index."""

    exact_names: set[str]
    occupied_namespaces: set[str]
    identity: AgentIdentitySnapshot = field(
        default_factory=AgentIdentitySnapshot.current,
        repr=False,
    )

    @classmethod
    def from_names(cls, names: Collection[str]) -> AgentNameNamespaceReservationIndex:
        identity = AgentIdentitySnapshot.current()
        index = cls(
            exact_names={
                current_owner_agent_name_key(name, identity) for name in names
            },
            occupied_namespaces=set(),
            identity=identity,
        )
        for name in names:
            key = current_owner_agent_name_key(name, identity)
            index.occupied_namespaces.update(_dotted_namespace_prefixes(key))
        return index

    @classmethod
    def from_registry_names(
        cls,
        names: Collection[str],
        *,
        namespace_containers: Collection[str] = (),
    ) -> AgentNameNamespaceReservationIndex:
        """Build an index while allowing descendants of container names."""
        identity = AgentIdentitySnapshot.current()
        containers = {
            current_owner_agent_name_key(name, identity)
            for name in namespace_containers
        }
        index = cls(
            exact_names={
                current_owner_agent_name_key(name, identity) for name in names
            },
            occupied_namespaces=set(),
            identity=identity,
        )
        for name in names:
            key = current_owner_agent_name_key(name, identity)
            if key not in containers:
                index.occupied_namespaces.update(_dotted_namespace_prefixes(key))
        return index

    def add_name(self, name: str) -> None:
        key = current_owner_agent_name_key(name, self.identity)
        self.exact_names.add(key)
        self.occupied_namespaces.update(_dotted_namespace_prefixes(key))

    def update_names(self, names: Collection[str]) -> None:
        for name in names:
            self.add_name(name)

    def candidate_available(
        self,
        name: str,
        namespace: str,
        *,
        owned_namespaces: Collection[str] = (),
    ) -> bool:
        name_key = current_owner_agent_name_key(name, self.identity)
        namespace_key = current_owner_agent_name_key(namespace, self.identity)
        owned_namespace_keys = {
            current_owner_agent_name_key(value, self.identity)
            for value in owned_namespaces
        }
        if name_key in self.exact_names:
            return False
        return (
            namespace_key not in self.occupied_namespaces
            or namespace_key in owned_namespace_keys
        )


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
    """Render *template* with the canonical auto-ID separator behavior.

    A letter-leading token gains a dash when the marker follows an ordinary
    character. Leading markers and markers after ``-`` or ``.`` use the token
    directly; digit-leading tokens always remain adjacent to the prefix.
    """
    try:
        return str(_core("render_agent_name_template")(template, token))
    except ValueError as exc:
        raise _value_error(template, token, exc) from exc


def agent_name_template_namespace_template(template: str) -> str:
    """Return the namespace template used to reserve *template* tokens."""
    try:
        return str(_core("agent_name_template_namespace_template")(template))
    except ValueError as exc:
        raise _template_error(template, exc) from exc


def render_agent_name_template_namespace(template: str, token: str) -> str:
    """Render the namespace reserved by *template* for *token*."""
    namespace_template = agent_name_template_namespace_template(template)
    return render_agent_name_template(namespace_template, token)


def match_agent_name_template(template: str, concrete: str) -> str | None:
    """Return the canonical template token in *concrete*, if it matches."""
    identity = AgentIdentitySnapshot.current()
    local_template = present_agent_name(template, identity)
    local_concrete = present_agent_name(concrete, identity)
    try:
        token = _core("match_agent_name_template")(local_template, local_concrete)
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
    index: AgentNameNamespaceReservationIndex | None = None,
) -> str:
    """Allocate the lowest available concrete name for *template*.

    The provided reservation set is mutated in place. When omitted, the durable
    agent-name registry supplies the initial reservations. A caller allocating
    several names from one snapshot may pass a shared *index* (kept in sync with
    *reserved*) so it is built once instead of per call.
    """
    # Validate the template before loading the registry so syntax errors stay
    # independent of local agent state.
    parse_agent_name_template(template)
    registry_backed = reserved is None
    if reserved is None:
        pool = _reserved_names()
    else:
        pool = reserved
    if index is None:
        if registry_backed:
            from sase.agent.names._registry import get_reserved_clan_names

            index = AgentNameNamespaceReservationIndex.from_registry_names(
                pool,
                namespace_containers=get_reserved_clan_names(),
            )
        else:
            index = AgentNameNamespaceReservationIndex.from_names(pool)
    # The namespace template depends only on *template*, so derive it once and
    # render the per-token namespace from it inside the loop.
    namespace_template = agent_name_template_namespace_template(template)
    for token in iter_agent_name_template_tokens():
        candidate = render_agent_name_template(template, token)
        namespace = render_agent_name_template(namespace_template, token)
        if index.candidate_available(candidate, namespace):
            durable_candidate = normalize_owned_agent_name(candidate, index.identity)
            pool.add(durable_candidate)
            index.add_name(durable_candidate)
            return durable_candidate
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


def resolve_agent_name_template_reference(
    name: str,
    *,
    names: Collection[str] | None = None,
) -> str:
    """Resolve a template reference to its latest concrete name.

    Non-template names are returned unchanged. Template names use the generic
    auto-token order, so legacy shapes such as ``build-@`` and newer shapes
    such as ``@.cld`` share the same resolution path.
    """
    if not is_agent_name_template(name):
        return name
    return require_latest_agent_name_template(name, names=names)


@cache
def _core(name: str) -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding(name)


def _reserved_names() -> set[str]:
    from sase.agent.names._registry import get_reserved_agent_names

    return get_reserved_agent_names()


def _dotted_namespace_prefixes(name: str) -> set[str]:
    parts = name.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


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

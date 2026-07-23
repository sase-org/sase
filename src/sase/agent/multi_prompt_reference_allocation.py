"""Shared data and candidate rendering for planned-name allocation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.core.agent_identity_facade import AgentIdentitySnapshot


@dataclass(frozen=True)
class PlannedNameReservation:
    """A parent-side name reservation for a not-yet-started child."""

    name: str
    artifacts_dir: str


@dataclass(frozen=True)
class TemplateGroup:
    """Token-sharing group for related agent-name templates."""

    key: str


def template_candidates(
    templates_with_namespaces: Sequence[tuple[str, str]],
    token: str,
    identity: AgentIdentitySnapshot,
) -> list[tuple[str, str]]:
    """Render concrete name and namespace candidates for one token."""
    return [
        durable_template_candidate(
            template,
            namespace_template,
            token,
            identity,
        )
        for template, namespace_template in templates_with_namespaces
    ]


def durable_template_candidate(
    template: str,
    namespace_template: str,
    token: str,
    identity: AgentIdentitySnapshot,
) -> tuple[str, str]:
    """Render and normalize one locally owned template candidate."""
    from sase.agent.names import render_agent_name_template
    from sase.core.agent_identity_facade import normalize_owned_agent_name

    return (
        normalize_owned_agent_name(
            render_agent_name_template(template, token),
            identity,
        ),
        normalize_owned_agent_name(
            render_agent_name_template(namespace_template, token),
            identity,
        ),
    )


def normalize_template_group(
    group: TemplateGroup | str | None,
    template: str,
) -> TemplateGroup:
    """Normalize an optional group label, deriving one from the template."""
    if isinstance(group, TemplateGroup):
        return group
    if group is not None:
        return TemplateGroup(str(group))
    return TemplateGroup(_template_group_key(template))


def _template_group_key(template: str) -> str:
    """Return the default token-sharing key for a template."""
    from sase.agent.names import agent_name_template_base

    base = agent_name_template_base(template)
    return base.rsplit(".", 1)[0] if "." in base else base

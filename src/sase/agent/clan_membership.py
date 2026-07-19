"""Execution-neutral, rootless agent-clan membership metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path

CLAN_MEMBERSHIP_ENV = "SASE_AGENT_CLAN_MEMBERSHIP"
AGENT_CLAN_FIELD = "agent_clan"
AGENT_CLAN_GENERATION_FIELD = "agent_clan_generation"


class ClanMembershipError(RuntimeError):
    """Raised when a clan target or membership payload cannot be resolved."""


@dataclass(frozen=True)
class ClanMembershipPlan:
    """Resolved clan identity delivered from the launcher to one runner."""

    clan_name: str
    generation: str


def encode_clan_membership_plan(plan: ClanMembershipPlan) -> str:
    """Encode *plan* for ``SASE_AGENT_CLAN_MEMBERSHIP``."""
    return json.dumps(asdict(plan), sort_keys=True)


def consume_clan_membership_plan_from_env() -> ClanMembershipPlan | None:
    """Consume the host-only clan payload so nested launches cannot inherit it."""
    raw = os.environ.pop(CLAN_MEMBERSHIP_ENV, None)
    if not raw:
        return None
    return decode_clan_membership_plan(raw)


def resolve_or_create_clan_membership(
    target: str,
    *,
    generation: str,
    claiming_dir: str | Path,
    member_name: str | None = None,
    member_name_template: str | None = None,
) -> ClanMembershipPlan:
    """Join the newest *target* clan, creating it when it is missing."""
    return _reserve_clan_membership(
        target,
        generation=generation,
        claiming_dir=claiming_dir,
        create_only=False,
        member_name=member_name,
        member_name_template=member_name_template,
    )


def declare_clan_membership(
    target: str,
    *,
    generation: str,
    claiming_dir: str | Path,
    member_name: str | None = None,
    member_name_template: str | None = None,
) -> ClanMembershipPlan:
    """Create a newly declared clan, rejecting an existing clan."""
    return _reserve_clan_membership(
        target,
        generation=generation,
        claiming_dir=claiming_dir,
        create_only=True,
        member_name=member_name,
        member_name_template=member_name_template,
    )


def _reserve_clan_membership(
    target: str,
    *,
    generation: str,
    claiming_dir: str | Path,
    create_only: bool,
    member_name: str | None,
    member_name_template: str | None,
) -> ClanMembershipPlan:
    from sase.agent.names import (
        AgentNameTemplateError,
        NameCollisionError,
        get_reserved_clan_names,
        match_agent_name_template,
        render_agent_name_template,
        reserve_registered_clan_name,
        resolve_agent_name_template_reference,
    )

    try:
        clan_name = resolve_agent_name_template_reference(
            target,
            names=get_reserved_clan_names(),
        )
    except AgentNameTemplateError as exc:
        token = None
        if member_name and member_name_template:
            try:
                token = match_agent_name_template(member_name_template, member_name)
            except AgentNameTemplateError:
                token = None
        if token is None:
            raise ClanMembershipError(
                f"Cannot resolve clan target '{target}' from member name "
                f"'{member_name or ''}'"
            ) from exc
        clan_name = render_agent_name_template(target, token)

    try:
        reserved_generation = reserve_registered_clan_name(
            clan_name,
            generation,
            claiming_dir,
            create_only=create_only,
        )
    except NameCollisionError as exc:
        raise ClanMembershipError(str(exc)) from exc
    return ClanMembershipPlan(
        clan_name=clan_name,
        generation=reserved_generation,
    )


def decode_clan_membership_plan(raw: str) -> ClanMembershipPlan:
    """Decode a clan membership payload without consuming process state."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClanMembershipError(f"Invalid {CLAN_MEMBERSHIP_ENV} payload") from exc
    if not isinstance(data, dict):
        raise ClanMembershipError(f"Invalid {CLAN_MEMBERSHIP_ENV} payload")

    values: dict[str, str] = {}
    for key in ("clan_name", "generation"):
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ClanMembershipError(
                f"Invalid {CLAN_MEMBERSHIP_ENV} payload: missing {key}"
            )
        values[key] = value
    return ClanMembershipPlan(**values)


__all__ = [
    "AGENT_CLAN_FIELD",
    "AGENT_CLAN_GENERATION_FIELD",
    "CLAN_MEMBERSHIP_ENV",
    "ClanMembershipError",
    "ClanMembershipPlan",
    "consume_clan_membership_plan_from_env",
    "declare_clan_membership",
    "decode_clan_membership_plan",
    "encode_clan_membership_plan",
    "resolve_or_create_clan_membership",
]

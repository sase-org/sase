"""Execution-neutral, rootless agent-clan membership metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os

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


def resolve_existing_clan_membership(target: str) -> ClanMembershipPlan:
    """Resolve a directive-only member against an existing clan."""
    from sase.agent.names import (
        AgentNameTemplateError,
        find_agent_clan,
        get_reserved_clan_names,
        resolve_agent_name_template_reference,
    )

    try:
        clan_name = resolve_agent_name_template_reference(
            target,
            names=get_reserved_clan_names(),
        )
    except AgentNameTemplateError as exc:
        raise ClanMembershipError(
            f"Cannot resolve %clan target '{target}': no matching clan exists"
        ) from exc

    clan = find_agent_clan(clan_name)
    if clan is None:
        raise ClanMembershipError(
            f"Cannot resolve %clan target '{target}': no matching clan exists"
        )
    return ClanMembershipPlan(clan_name=clan.name, generation=clan.generation)


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
    "decode_clan_membership_plan",
    "encode_clan_membership_plan",
    "resolve_existing_clan_membership",
]

"""Shared launch helpers for chop proposal launch paths."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION
from sase.core.time import get_timezone

from .chop_proposal_models import (
    PlannedChopProposal,
    resolve_wait_name,
)


def ordinary_batch_manifest(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    run_started_at: str,
    preflight: Any,
    plans: Sequence[PlannedChopProposal],
) -> dict[str, Any]:
    decision = getattr(preflight, "decision", None)
    preflight_digest = None
    checkpoint_scope = None
    if isinstance(decision, Mapping):
        encoded = json.dumps(
            decision,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        preflight_digest = hashlib.sha256(encoded).hexdigest()
        checkpoint_scope_value = decision.get("checkpoint_key")
        if checkpoint_scope_value:
            checkpoint_scope = str(checkpoint_scope_value)
    members: list[dict[str, Any]] = []
    position_by_source_index = {
        plan.proposal.index: position for position, plan in enumerate(plans)
    }
    accepted_ids = {
        plan.proposal.proposal_id
        for plan in plans
        if plan.proposal.proposal_id is not None
    }
    for plan in plans:
        proposal = plan.proposal
        member: dict[str, Any] = {
            "source_index": proposal.index,
            "agent_name": plan.agent_name,
            "prompt": plan.prompt,
            "workspace": proposal.workspace,
            "env": dict(proposal.env),
            "launch_role": ("declare" if plan.declares_clan else "join")
            if plan.clan is not None
            else "standalone",
        }
        wait_on = proposal.wait_on
        if isinstance(wait_on, int):
            mapped_wait = position_by_source_index.get(wait_on)
            if mapped_wait is not None:
                member["wait_on"] = mapped_wait
        elif isinstance(wait_on, str) and wait_on in accepted_ids:
            member["wait_on"] = wait_on
        if proposal.proposal_id is not None:
            member["proposal_id"] = proposal.proposal_id
        if plan.clan is not None:
            member["clan"] = plan.clan
        if proposal.model is not None:
            member["model"] = proposal.model
        if proposal.effort is not None:
            member["effort"] = proposal.effort
        if proposal.dedupe_key is not None:
            member["dedupe_key"] = proposal.dedupe_key
        if proposal.tribe:
            member["tribe"] = proposal.tribe
        members.append(member)
    manifest: dict[str, Any] = {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": run_id,
        "run": {
            "routine": lumberjack_name,
            "job": chop_name,
            "run_id": run_id,
            "run_started_at": run_started_at,
        },
        "created_at": datetime.now(get_timezone()).isoformat(),
        "members": members,
    }
    if preflight_digest is not None:
        manifest["run"]["preflight_digest"] = preflight_digest
    if checkpoint_scope is not None:
        manifest["run"]["checkpoint_scope"] = checkpoint_scope
    return manifest


def query_for_plans(plans: Sequence[PlannedChopProposal]) -> str:
    return "\n---\n".join(plan.prompt.rstrip() for plan in plans) + "\n"


def wait_names_by_proposal_index(
    plans: Sequence[PlannedChopProposal],
) -> dict[int, str | None]:
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    result: dict[int, str | None] = {}
    for plan in plans:
        proposal = plan.proposal
        wait_name = resolve_wait_name(
            proposal.wait_on,
            names_by_index,
            names_by_id,
        )
        result[proposal.index] = wait_name
        names_by_index[proposal.index] = plan.agent_name
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = plan.agent_name
    return result


__all__ = [
    "ordinary_batch_manifest",
    "query_for_plans",
    "wait_names_by_proposal_index",
]

"""Typed-admission metadata for chop proposal launch batches."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.agent_launch_wire import LaunchPlanWire

from .chop_proposal_models import PlannedChopProposal
from .chop_typed_admission import (
    AXE_CHOP_SOURCE_SURFACE,
    UNIT_DISPATCH_METADATA_KEY,
)
from ._chop_proposal_launch_shared import wait_names_by_proposal_index


def _metadata_for_unit(
    *,
    plan: PlannedChopProposal,
    logical_id: str,
    source_order: int,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    wait_name: str | None,
    wait_logical_id: str | None,
) -> dict[str, Any]:
    proposal = plan.proposal
    return {
        "lumberjack_name": lumberjack_name,
        "chop_name": chop_name,
        "run_id": run_id,
        "logical_id": logical_id,
        "source_order": source_order,
        "proposal_index": proposal.index,
        "proposal_id": proposal.proposal_id,
        "agent_name": plan.agent_name,
        "clan": plan.clan,
        "member_id": plan.member_id,
        # The statically planned role, from before admission-time `%if`
        # filtering. Dispatch promotes whichever eligible member reaches the
        # clan first, so this is informational rather than authoritative.
        "declares_clan": plan.declares_clan,
        # Every member of a clan repeats its raw proposal's intended tribe
        # and summary, so a promoted declarer can recover them without
        # re-deriving anything from mutable prompt prose.
        "clan_tribe": proposal.tribe,
        "clan_summary": proposal.clan_summary,
        "workspace": proposal.workspace,
        "dedupe_key": proposal.dedupe_key,
        "wait_on": proposal.wait_on,
        "wait_name": wait_name,
        "wait_logical_id": wait_logical_id,
        "env": dict(proposal.env),
    }


def _plan_for_unit(
    unit: Any,
    plans: Sequence[PlannedChopProposal],
) -> PlannedChopProposal:
    try:
        return plans[int(unit.source_order)]
    except (IndexError, ValueError) as exc:
        from sase.agent.launch_request_types import LaunchRequestError

        raise LaunchRequestError(
            "invalid_request",
            unit.logical_id,
            (
                "typed AXE job plan unit "
                f"{unit.logical_id} has invalid source_order {unit.source_order}"
            ),
        ) from exc


def _proposal_logical_id_maps(
    *,
    typed_plan: LaunchPlanWire,
    plans: Sequence[PlannedChopProposal],
) -> tuple[dict[int, str], dict[str, str]]:
    logical_by_index: dict[int, str] = {}
    logical_by_id: dict[str, str] = {}
    for unit in typed_plan.units:
        plan = _plan_for_unit(unit, plans)
        proposal = plan.proposal
        logical_by_index[proposal.index] = unit.logical_id
        if proposal.proposal_id is not None:
            logical_by_id[proposal.proposal_id] = unit.logical_id
    return logical_by_index, logical_by_id


def _wait_logical_id(
    wait_on: int | str | None,
    *,
    logical_by_index: Mapping[int, str],
    logical_by_id: Mapping[str, str],
) -> str | None:
    if wait_on is None:
        return None
    if isinstance(wait_on, int):
        return logical_by_index.get(wait_on)
    return logical_by_id.get(wait_on)


def unit_dispatch_metadata(
    *,
    typed_plan: LaunchPlanWire,
    plans: Sequence[PlannedChopProposal],
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
) -> dict[str, dict[str, Any]]:
    wait_names = wait_names_by_proposal_index(plans)
    logical_by_index, logical_by_id = _proposal_logical_id_maps(
        typed_plan=typed_plan,
        plans=plans,
    )
    metadata: dict[str, dict[str, Any]] = {}
    for unit in typed_plan.units:
        plan = _plan_for_unit(unit, plans)
        metadata[unit.logical_id] = _metadata_for_unit(
            plan=plan,
            logical_id=unit.logical_id,
            source_order=int(unit.source_order),
            lumberjack_name=lumberjack_name,
            chop_name=chop_name,
            run_id=run_id,
            wait_name=wait_names.get(plan.proposal.index),
            wait_logical_id=_wait_logical_id(
                plan.proposal.wait_on,
                logical_by_index=logical_by_index,
                logical_by_id=logical_by_id,
            ),
        )
    return metadata


def typed_admission_record(
    *,
    bundle_dir: Any,
    payload: Mapping[str, Any],
    typed_plan: LaunchPlanWire,
    metadata: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    for unit in typed_plan.units:
        unit_meta = metadata.get(unit.logical_id, {})
        units.append(
            {
                "logical_id": unit.logical_id,
                "source_order": int(unit.source_order),
                "proposal_index": unit_meta.get("proposal_index"),
                "proposal_id": unit_meta.get("proposal_id"),
                "dedupe_key": unit_meta.get("dedupe_key"),
                "wait_logical_id": unit_meta.get("wait_logical_id"),
            }
        )
    return {
        "request_id": str(payload.get("request_id") or ""),
        "bundle_dir": str(bundle_dir),
        "plan_digest": typed_plan.content_digest,
        "plan_schema_version": typed_plan.schema_version,
        "source_surface": AXE_CHOP_SOURCE_SURFACE,
        "units": units,
    }


def unit_dispatch_metadata_from_payload(
    payload: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    raw = payload.get(UNIT_DISPATCH_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, Mapping)
    }


__all__ = [
    "typed_admission_record",
    "unit_dispatch_metadata",
    "unit_dispatch_metadata_from_payload",
]

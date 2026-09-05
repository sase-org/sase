"""Once-per proposal admission for structured chop results."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    check_and_record_chop_once_per,
    release_chop_once_per,
)
from sase.core.time import get_timezone

from .chop_policy_state import (
    atomic_write_json,
    chop_policy_lock,
    read_seen_document,
    seen_path,
)
from .chop_policy_types import ChopOncePerOutcome, Proposal
from .config import ChopConfig


def apply_chop_once_per(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    proposals: Sequence[Proposal],
    persist: bool,
    now: datetime | None = None,
) -> ChopOncePerOutcome:
    """Apply bounded event dedupe and dependency-aware proposal filtering."""
    if chop.once_per is None and not any(p.dedupe_key for p in proposals):
        return ChopOncePerOutcome(
            accepted_indices=tuple(proposal.index for proposal in proposals),
            decisions={},
            effective_waits={
                proposal.index: proposal.wait_on for proposal in proposals
            },
        )

    timestamp = (now or datetime.now(get_timezone())).isoformat()
    capacity = int((chop.once_per or {}).get("capacity", 1024))
    accepted: list[int] = []
    duplicate_indices: set[int] = set()
    proposal_indices_by_id: dict[str, int] = {}
    resolved_waits: dict[int, int | str | None] = {}
    effective_waits: dict[int, int | str | None] = {}
    decisions: dict[int, dict[str, str]] = {}

    with chop_policy_lock(lumberjack_name, chop.name):
        document = read_seen_document(lumberjack_name, chop.name)
        changed = False
        for proposal in proposals:
            dependency = proposal.wait_on
            dependency_index: int | None = None
            if isinstance(dependency, int):
                dependency_index = dependency
            elif isinstance(dependency, str):
                dependency_index = proposal_indices_by_id.get(dependency)

            effective_wait = dependency
            relinked_dependency: int | str | None = None
            if dependency_index in duplicate_indices:
                relinked_dependency = dependency
                effective_wait = resolved_waits[dependency_index]
            resolved_waits[proposal.index] = effective_wait
            if proposal.proposal_id is not None:
                proposal_indices_by_id[proposal.proposal_id] = proposal.index

            key = proposal_once_per_key(chop, proposal)
            if key is None:
                accepted.append(proposal.index)
                effective_waits[proposal.index] = effective_wait
                if relinked_dependency is not None:
                    decisions[proposal.index] = {
                        "outcome": "accept",
                        "reason": once_per_relink_reason(
                            relinked_dependency,
                            effective_wait,
                        ),
                        "key": "",
                    }
                continue

            result = check_and_record_chop_once_per(
                {
                    "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                    "document": document,
                    "key": key,
                    "now": timestamp,
                    "capacity": capacity,
                }
            )
            outcome = str(result["outcome"])
            decisions[proposal.index] = {
                "outcome": outcome,
                "reason": str(result["reason"]),
                "key": key,
            }
            if outcome == "duplicate":
                duplicate_indices.add(proposal.index)
                continue
            if outcome != "accept":
                raise ValueError(f"unexpected once-per outcome: {outcome}")
            if relinked_dependency is not None:
                decisions[proposal.index]["reason"] = once_per_relink_reason(
                    relinked_dependency,
                    effective_wait,
                )
            document = dict(result["document"])
            changed = True
            accepted.append(proposal.index)
            effective_waits[proposal.index] = effective_wait

        if persist and changed:
            atomic_write_json(seen_path(lumberjack_name, chop.name), document)

    return ChopOncePerOutcome(tuple(accepted), decisions, effective_waits)


def once_per_relink_reason(
    dependency: int | str,
    effective_wait: int | str | None,
) -> str:
    target = repr(effective_wait) if effective_wait is not None else "none"
    return f"wait dependency {dependency!r} was deduped; relinked to {target}"


def release_chop_once_per_keys(
    lumberjack_name: str,
    chop_name: str,
    keys: Sequence[str],
) -> int:
    """Release exact once-per keys and persist the transformed seen store."""
    if not keys:
        return 0

    with chop_policy_lock(lumberjack_name, chop_name):
        document = read_seen_document(lumberjack_name, chop_name)
        result = release_chop_once_per(
            {
                "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                "document": document,
                "keys": list(keys),
            }
        )
        released = int(result["released"])
        if released:
            atomic_write_json(
                seen_path(lumberjack_name, chop_name),
                dict(result["document"]),
            )
        return released


def proposal_once_per_key(chop: ChopConfig, proposal: Proposal) -> str | None:
    if proposal.dedupe_key:
        return proposal.dedupe_key
    once_per = chop.once_per
    if once_per is None:
        return None
    template = str(once_per["key"])
    proposal_value = SimpleNamespace(
        id=proposal.proposal_id or "",
        index=proposal.index,
        workspace=proposal.workspace,
        agent_name=proposal.agent_name,
        dedupe_key=proposal.dedupe_key or "",
    )
    try:
        rendered = template.format_map(
            {
                "chop": NamedTemplateValue(chop.name),
                "proposal": proposal_value,
                "target": TargetTemplateValue(chop.target),
            }
        )
    except (AttributeError, KeyError, ValueError) as exc:
        raise ValueError(
            f"could not render once_per key template {template!r}: {exc}"
        ) from exc
    if not rendered.strip():
        raise ValueError("once_per key template rendered an empty key")
    return rendered


class NamedTemplateValue(str):
    @property
    def name(self) -> str:
        return str(self)


class TargetTemplateValue(dict[str, Any]):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


__all__ = [
    "NamedTemplateValue",
    "TargetTemplateValue",
    "apply_chop_once_per",
    "once_per_relink_reason",
    "proposal_once_per_key",
    "release_chop_once_per_keys",
]

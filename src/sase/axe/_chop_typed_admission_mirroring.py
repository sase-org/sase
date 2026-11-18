"""Mirror typed admission progress into the enclosing chop batch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ._chop_typed_admission_utils import int_or_none, unit_metadata


def mirror_typed_dispatch_start(
    routine: str,
    job: str,
    batch_id: str,
    metadata: Mapping[str, Any],
) -> None:
    source_index = int_or_none(metadata.get("proposal_index"))
    if source_index is None:
        return
    _ensure_typed_member_dispatching(routine, job, batch_id, source_index)


def mirror_typed_launch(
    routine: str,
    job: str,
    batch_id: str,
    launch: Mapping[str, Any],
) -> None:
    from . import chop_batch_store

    source_index = int_or_none(launch.get("index"))
    if source_index is None:
        return
    member_index = _typed_member_index(
        chop_batch_store.load_chop_batch(routine, job, batch_id), source_index
    )
    if member_index is None:
        return
    manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
    status = str(manifest["members"][member_index].get("status") or "pending")
    if status == "pending":
        chop_batch_store.apply_chop_batch_event(
            routine,
            job,
            batch_id,
            "begin_dispatch",
            member_index=member_index,
        )
        status = "dispatching"
    if status == "dispatching":
        chop_batch_store.apply_chop_batch_event(
            routine,
            job,
            batch_id,
            "acknowledge_launch",
            member_index=member_index,
        )


def _ensure_typed_member_dispatching(
    routine: str,
    job: str,
    batch_id: str,
    source_index: int,
) -> None:
    from . import chop_batch_store

    manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
    member_index = _typed_member_index(manifest, source_index)
    if member_index is None:
        return
    status = str(manifest["members"][member_index].get("status") or "pending")
    if status in {"pending", "dispatching"}:
        chop_batch_store.apply_chop_batch_event(
            routine,
            job,
            batch_id,
            "begin_dispatch",
            member_index=member_index,
        )


def mirror_typed_unit_results(
    routine: str,
    job: str,
    batch_id: str,
    payload: Mapping[str, Any],
    unit_results: Sequence[Any],
) -> None:
    from . import chop_batch_store

    metadata = unit_metadata(payload)
    manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
    if manifest.get("status") in {"cancelled", "complete"}:
        return
    for result in unit_results:
        logical_id = str(getattr(result, "logical_id", "") or "")
        unit_meta = metadata.get(logical_id)
        if unit_meta is None:
            continue
        source_index = int_or_none(unit_meta.get("proposal_index"))
        if source_index is None:
            continue
        member_index = _typed_member_index(manifest, source_index)
        if member_index is None:
            continue
        outcome = _outcome_name(getattr(result, "outcome", ""))
        if outcome == "launched":
            mirror_typed_launch(
                routine,
                job,
                batch_id,
                {
                    "index": source_index,
                    "agent_name": unit_meta.get("agent_name"),
                },
            )
            manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
            continue
        if outcome not in {"skipped", "condition_error", "launch_error", "cancelled"}:
            continue
        member_status = str(
            manifest["members"][member_index].get("status") or "pending"
        )
        if member_status not in {"pending", "dispatching", "skipped"}:
            continue
        message = str(getattr(result, "message", "") or outcome)
        reason = f"typed admission {outcome}: {message}"
        if len(reason) > 240:
            reason = reason[:237] + "..."
        chop_batch_store.apply_chop_batch_event(
            routine,
            job,
            batch_id,
            "record_skip",
            member_index=member_index,
            reason=reason,
        )
        manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)


def _typed_member_index(manifest: Mapping[str, Any], source_index: int) -> int | None:
    members = manifest.get("members")
    if not isinstance(members, list):
        return None
    for index, member in enumerate(members):
        if (
            isinstance(member, Mapping)
            and int_or_none(member.get("source_index")) == source_index
        ):
            return index
    return None


def _outcome_name(value: Any) -> str:
    return str(getattr(value, "value", value) or "")

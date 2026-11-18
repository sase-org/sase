"""Once-per key release helpers for script-chop structured results."""

from __future__ import annotations

from typing import Any

from .chop_policy import release_chop_once_per_keys
from .state import append_chop_run_output


def release_unlaunched_once_per_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    accepted_proposals: list[Any],
    successful_launches: list[dict[str, Any]],
    after: str = "launch failure",
) -> None:
    journal_statuses = _batch_member_statuses(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
    )
    if journal_statuses is None:
        launched_indices = {int(launch["index"]) for launch in successful_launches}
        release_indices = {
            proposal.index
            for proposal in accepted_proposals
            if proposal.index not in launched_indices
        }
        keys = list(
            dict.fromkeys(
                proposal.dedupe_key
                for proposal in accepted_proposals
                if proposal.index in release_indices and proposal.dedupe_key
            )
        )
    else:
        keys = _keys_for_releasable_members(
            {
                proposal.index: proposal.dedupe_key
                for proposal in accepted_proposals
                if proposal.dedupe_key
            },
            journal_statuses,
        )
    if not keys:
        return

    try:
        released = release_chop_once_per_keys(lumberjack_name, chop_name, keys)
    except Exception as exc:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Failed to release once-per keys after {after}: {exc}\n",
        )
        return
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Released {released} once-per key(s) after {after}\n",
    )


def release_typed_nonlaunched_once_per_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    typed_admission: dict[str, Any],
    admission_result: Any,
    after: str,
) -> None:
    units = typed_admission.get("units")
    if not isinstance(units, list):
        return
    keys_by_logical_id = {
        str(unit.get("logical_id") or ""): str(unit.get("dedupe_key") or "")
        for unit in units
        if isinstance(unit, dict)
    }
    journal_statuses = _batch_member_statuses(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
    )
    if journal_statuses is None:
        keys = list(
            dict.fromkeys(
                keys_by_logical_id.get(str(getattr(unit, "logical_id", "") or ""), "")
                for unit in getattr(admission_result, "unit_results", ()) or ()
                if str(getattr(unit, "outcome", "") or "") != "launched"
            )
        )
    else:
        keys = _keys_for_releasable_members(
            {
                index: str(unit.get("dedupe_key") or "")
                for unit in units
                if isinstance(unit, dict)
                and (index := _int_or_none(unit.get("proposal_index"))) is not None
            },
            journal_statuses,
        )
    keys = [key for key in keys if key]
    if not keys:
        return

    try:
        released = release_chop_once_per_keys(lumberjack_name, chop_name, keys)
    except Exception as exc:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Failed to release once-per keys after {after}: {exc}\n",
        )
        return
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Released {released} once-per key(s) after {after}\n",
    )


def _batch_member_statuses(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
) -> dict[int, str] | None:
    """Return the durable journal states, or None when no durable batch exists."""
    from . import chop_batch_store

    try:
        manifest = chop_batch_store.load_chop_batch(lumberjack_name, chop_name, run_id)
    except chop_batch_store.ChopBatchNotFoundError:
        return None
    except chop_batch_store.ChopBatchError as exc:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Kept once-per claims because the batch journal could not be read: {exc}\n",
        )
        return {}
    return {
        int(member["source_index"]): str(member.get("status") or "pending")
        for member in manifest.get("members", [])
        if isinstance(member, dict) and isinstance(member.get("source_index"), int)
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _keys_for_releasable_members(
    key_by_index: dict[int, str], journal_statuses: dict[int, str]
) -> list[str]:
    indices_by_key: dict[str, set[int]] = {}
    for index, key in key_by_index.items():
        if key:
            indices_by_key.setdefault(key, set()).add(index)
    return [
        key
        for key in dict.fromkeys(key_by_index.values())
        if key
        and all(
            journal_statuses.get(index) in {"skipped", "blocked", "cancelled"}
            for index in indices_by_key[key]
        )
    ]


__all__ = [
    "release_typed_nonlaunched_once_per_keys",
    "release_unlaunched_once_per_keys",
]

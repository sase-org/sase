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
    launched_indices = {int(launch["index"]) for launch in successful_launches}
    keys = list(
        dict.fromkeys(
            proposal.dedupe_key
            for proposal in accepted_proposals
            if proposal.index not in launched_indices and proposal.dedupe_key
        )
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
    keys = list(
        dict.fromkeys(
            keys_by_logical_id.get(str(getattr(unit, "logical_id", "") or ""), "")
            for unit in getattr(admission_result, "unit_results", ()) or ()
            if str(getattr(unit, "outcome", "") or "") != "launched"
        )
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


__all__ = [
    "release_typed_nonlaunched_once_per_keys",
    "release_unlaunched_once_per_keys",
]

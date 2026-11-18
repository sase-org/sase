"""Once-per key release and unmatched-record logging for chop lifecycle."""

from __future__ import annotations

from ._chop_lifecycle_types import AgentCompletion, MatchedAgentRecord
from .chop_policy import release_chop_once_per_keys
from .state import append_chop_run_output

_RELEASABLE_BATCH_STATUSES = {"skipped", "blocked", "cancelled"}


def log_unmatched_records(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    records: list[object],
) -> None:
    if not records:
        return
    details = ", ".join(
        (
            f"pid {int(getattr(record, 'pid', 0) or 0)} "
            f"(artifacts timestamp "
            f"{str(getattr(record, 'artifacts_timestamp', '') or 'unknown')})"
        )
        for record in records
    )
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Ignored {len(records)} unmatched agent registry record(s): {details}\n",
    )


def release_failed_launch_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    matched_records: list[MatchedAgentRecord],
    completions: list[AgentCompletion],
) -> None:
    keys: list[str] = []
    for matched, completion in zip(matched_records, completions, strict=True):
        if completion.succeeded:
            continue
        key = str(matched.launch.get("dedupe_key") or "").strip()
        if key and key not in keys:
            keys.append(key)
    if not keys:
        return

    keys = _filter_keys_by_batch_status(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
        keys=keys,
        key_by_index={
            index: str(matched.launch.get("dedupe_key") or "").strip()
            for matched in matched_records
            if (index := _int_or_none(matched.launch.get("index"))) is not None
        },
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
            f"Failed to release once-per keys for failed launches: {exc}\n",
        )
        return
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Released {released} once-per key(s) for failed launches\n",
    )


def release_typed_nonlaunched_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    keys: list[str],
    typed_admission: dict[str, object] | None = None,
) -> None:
    keys = list(dict.fromkeys(key for key in keys if key))
    if not keys:
        return
    units = (typed_admission or {}).get("units")
    key_by_index = (
        {
            index: str(unit.get("dedupe_key") or "").strip()
            for unit in units
            if isinstance(unit, dict)
            and (index := _int_or_none(unit.get("proposal_index"))) is not None
        }
        if isinstance(units, list)
        else {}
    )
    keys = _filter_keys_by_batch_status(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        run_id=run_id,
        keys=keys,
        key_by_index=key_by_index,
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
            f"Failed to release once-per keys after typed admission: {exc}\n",
        )
        return
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Released {released} once-per key(s) after typed admission\n",
    )


def _filter_keys_by_batch_status(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    keys: list[str],
    key_by_index: dict[int, str],
) -> list[str]:
    """Release only claims whose every journal member is non-dispatchable."""
    from . import chop_batch_store

    try:
        manifest = chop_batch_store.load_chop_batch(lumberjack_name, chop_name, run_id)
    except chop_batch_store.ChopBatchNotFoundError:
        return keys
    except chop_batch_store.ChopBatchError as exc:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Kept once-per claims because the batch journal could not be read: {exc}\n",
        )
        return []

    status_by_index: dict[int, str] = {}
    for member in manifest.get("members", []):
        if not isinstance(member, dict):
            continue
        source_index = member.get("source_index")
        if isinstance(source_index, int):
            status_by_index[source_index] = str(member.get("status") or "pending")
    indices_by_key: dict[str, set[int]] = {}
    for index, key in key_by_index.items():
        if key:
            indices_by_key.setdefault(key, set()).add(index)
    return [
        key
        for key in keys
        if indices_by_key.get(key)
        and all(
            status_by_index.get(index) in _RELEASABLE_BATCH_STATUSES
            for index in indices_by_key[key]
        )
    ]


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "log_unmatched_records",
    "release_failed_launch_keys",
    "release_typed_nonlaunched_keys",
]

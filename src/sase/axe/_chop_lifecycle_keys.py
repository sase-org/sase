"""Once-per key release and unmatched-record logging for chop lifecycle."""

from __future__ import annotations

from ._chop_lifecycle_types import _AgentCompletion, _MatchedAgentRecord
from .chop_policy import release_chop_once_per_keys
from .state import append_chop_run_output


def _log_unmatched_records(
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


def _release_failed_launch_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    matched_records: list[_MatchedAgentRecord],
    completions: list[_AgentCompletion],
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


def _release_typed_nonlaunched_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    keys: list[str],
) -> None:
    keys = list(dict.fromkeys(key for key in keys if key))
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

"""What a waiting run prints about the grant it cannot get yet.

Split out of :mod:`tests._suite_gate`. A run blocked on the pool is otherwise
indistinguishable from a hung one, so it says every thirty seconds what it
asked for, what was free, and who is holding the rest — and, when a holder is
past a reclaim bound, that too.
"""

from __future__ import annotations

import time
from pathlib import Path

from tests._suite_gate_env import holder_max_hold, holder_stale_timeout
from tests._suite_gate_holders import load_holder_state, reclaim_reason_from_state


def _request_description(floor: int, ceiling: int) -> str:
    if floor == ceiling:
        return f"{floor} worker tokens"
    return f"{floor}-{ceiling} worker tokens"


def waiting_message(
    floor: int,
    ceiling: int,
    available: int,
    holders: dict[Path, str],
    *,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str:
    """Describe an in-progress wait for a grant that is not available yet."""
    return (
        "Waiting for a SASE pytest worker-token grant of "
        f"{_request_description(floor, ceiling)}; {available} tokens were "
        f"available below the floor. Current holders: "
        f"{_format_holders(holders, stale=stale, max_hold=max_hold)}"
    )


def timeout_message(
    timeout: float,
    floor: int,
    ceiling: int,
    available: int,
    holders: dict[Path, str],
    *,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str:
    """Describe a wait that hit its deadline, and every knob that bounds it."""
    return (
        "Timed out waiting for a SASE pytest worker-token grant of "
        f"{_request_description(floor, ceiling)} after {timeout:g}s; "
        f"{available} tokens were available below the floor. Current holders: "
        f"{_format_holders(holders, stale=stale, max_hold=max_hold)}. "
        "Adjust SASE_TEST_GATE_TIMEOUT, SASE_TEST_GATE_SLOTS, "
        "SASE_TEST_GATE_STALE, SASE_TEST_GATE_MAX_HOLD, "
        "SASE_PYTEST_WORKER_FLOOR, or SASE_PYTEST_WORKER_CEILING; set "
        "SASE_TEST_GATE_DISABLED=1 only to bypass the pool deliberately."
    )


def _format_holders(
    holders: dict[Path, str],
    *,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str:
    if not holders:
        return "unknown"

    directory = next(iter(holders)).parent
    grouped: dict[str, tuple[int, str]] = {}
    for metadata in holders.values():
        key, formatted = _holder_identity_and_text(
            metadata, directory=directory, stale=stale, max_hold=max_hold
        )
        count, _ = grouped.get(key, (0, formatted))
        grouped[key] = (count + 1, formatted)
    return "; ".join(
        f"{count} token{'s' if count != 1 else ''}: {formatted}"
        for count, formatted in sorted(grouped.values(), key=lambda item: item[1])
    )


def _holder_identity_and_text(
    metadata: str,
    *,
    directory: Path | None = None,
    stale: float | None = None,
    max_hold: float | None = None,
) -> tuple[str, str]:
    state = load_holder_state(metadata, directory)
    if state is None:
        return f"unavailable-{metadata}", "holder metadata unavailable"

    now = time.time()
    age_seconds = max(0, round(now - float(state["started"])))
    heartbeat_seconds = max(0, round(now - float(state["heartbeat"])))
    reason = reclaim_reason_from_state(
        state,
        now=now,
        stale=holder_stale_timeout() if stale is None else stale,
        max_hold=holder_max_hold() if max_hold is None else max_hold,
    )
    reclaimable = f", {reason}" if reason is not None else ""
    return (
        str(state["lease_id"]),
        (
            f"pid {int(state['pid'])}, grant {int(state['granted'])}, "
            f"age {age_seconds}s, heartbeat {heartbeat_seconds}s, "
            f"argv {state['argv']!r}{reclaimable}"
        ),
    )

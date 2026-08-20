"""Other processes' grants: writing, reading, judging, and reclaiming them.

Split out of :mod:`tests._suite_gate`. Every token file carries a JSON record
of who holds it; this module is both ends of that record. It writes one when a
grant is taken, parses one back when a waiter finds a token locked, decides
from it whether the holder has gone wedged, and — when it has — signals the
holder so the pool does not deadlock behind a run that will never finish.

Reclaim is bounded two ways, because one bound is not enough: a holder that
stops writing heartbeats is *stale*, and a holder that keeps writing them but
never finishes hits the absolute *max-hold* age cap.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any

from tests._suite_gate_env import holder_max_hold, holder_stale_timeout
from tests._suite_gate_progress import read_progress_sidecar


def write_holder_metadata(
    token_files: list[IO[str]], *, floor: int, ceiling: int, budget: int
) -> dict[str, Any]:
    """Stamp every freshly locked token with this grant's identity record."""
    started = time.time()
    metadata: dict[str, Any] = {
        "argv": shlex.join(sys.argv),
        "budget": budget,
        "granted": len(token_files),
        "heartbeat": started,
        "lease_id": f"{os.getpid()}-{time.time_ns()}",
        "pid": os.getpid(),
        "progress": 0,
        "requested_ceiling": ceiling,
        "requested_floor": floor,
        "started": started,
        "starttime": process_starttime(os.getpid()),
    }
    for token_file in token_files:
        token_file.seek(0)
        token_file.truncate()
        json.dump(metadata, token_file, sort_keys=True)
        token_file.write("\n")
        token_file.flush()
    return metadata


def load_holder_state(metadata: str, directory: Path | None) -> dict[str, Any] | None:
    """Parse a token file's record, preferring the sidecar's newer heartbeat."""
    try:
        parsed: Any = json.loads(metadata)
        pid = int(parsed["pid"])
        started = float(parsed["started"])
        argv = str(parsed["argv"])
        lease_id = str(parsed.get("lease_id", f"{pid}-{started}-{argv}"))
        granted = int(parsed.get("granted", 1))
        heartbeat = float(parsed.get("heartbeat", started))
        starttime = parsed.get("starttime")
        if starttime is not None:
            starttime = int(starttime)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    if directory is not None:
        sidecar = read_progress_sidecar(directory, lease_id)
        if sidecar is not None:
            sidecar_heartbeat = float(sidecar["heartbeat"])
            if sidecar_heartbeat > heartbeat:
                heartbeat = sidecar_heartbeat

    return {
        "argv": argv,
        "granted": granted,
        "heartbeat": heartbeat,
        "lease_id": lease_id,
        "pid": pid,
        "started": started,
        "starttime": starttime,
    }


def reclaim_reason_from_state(
    state: Mapping[str, Any],
    *,
    now: float | None = None,
    stale: float,
    max_hold: float,
) -> str | None:
    """Return ``max-hold``, ``stale-heartbeat``, or ``None`` for a healthy grant."""
    current = time.time() if now is None else now
    started = float(state["started"])
    heartbeat = float(state.get("heartbeat", started))
    if max_hold > 0 and current - started >= max_hold:
        return "max-hold"
    if stale > 0 and current - heartbeat >= stale:
        return "stale-heartbeat"
    return None


def holder_reclaim_reason(
    metadata: str,
    *,
    now: float | None = None,
    directory: Path | None = None,
    stale: float | None = None,
    max_hold: float | None = None,
) -> str | None:
    """Return ``stale-heartbeat``, ``max-hold``, or ``None`` if the grant is healthy."""
    state = load_holder_state(metadata, directory)
    if state is None:
        return None
    return reclaim_reason_from_state(
        state,
        now=now,
        stale=holder_stale_timeout() if stale is None else stale,
        max_hold=holder_max_hold() if max_hold is None else max_hold,
    )


def process_starttime(pid: int) -> int | None:
    """Return ``pid``'s boot-relative start time, which makes a pid unambiguous."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    rparen = stat.rfind(")")
    if rparen < 0:
        return None
    fields = stat[rparen + 2 :].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _signal_holder(pid: int, starttime: object, signum: int) -> bool:
    """Signal ``pid`` only if it is still the same process that took the grant."""
    if pid <= 0 or pid == os.getpid():
        return False
    live_starttime = process_starttime(pid)
    if live_starttime is None:
        return False
    if starttime is not None and int(starttime) != live_starttime:
        return False
    try:
        os.kill(pid, signum)
    except OSError:
        return False
    return True


def reclaim_message(
    pid: int,
    granted: int,
    reason: str,
    *,
    action: str,
    stale: float,
    max_hold: float,
) -> str:
    """Describe a reclaim of a wedged grant, and the bounds that judged it."""
    return (
        "Reclaiming a wedged SASE pytest worker-token grant: "
        f"{action} pid {pid}, {granted} token{'s' if granted != 1 else ''}, "
        f"{reason}. A live holder is bounded by SASE_TEST_GATE_STALE "
        f"({stale:g}s without progress) and "
        f"SASE_TEST_GATE_MAX_HOLD ({max_hold:g}s absolute)."
    )


def reclaim_wedged_holders(
    holders: Mapping[Path, str],
    signaled_leases: dict[str, int],
    *,
    now: float | None = None,
    stale: float,
    max_hold: float,
) -> None:
    """Signal every wedged holder among ``holders``, escalating on the second try.

    ``signaled_leases`` is the caller's memory of who it has already signalled,
    and is updated in place: a lease that ignored a ``SIGTERM`` gets a
    ``SIGKILL`` the next time the same waiter finds it still holding.
    """
    seen: set[str] = set()
    for token_path, raw in holders.items():
        state = load_holder_state(raw, token_path.parent)
        if state is None:
            continue
        lease_id = str(state["lease_id"])
        if lease_id in seen:
            continue
        seen.add(lease_id)
        reason = reclaim_reason_from_state(
            state, now=now, stale=stale, max_hold=max_hold
        )
        if reason is None:
            continue
        pid = int(state["pid"])
        previous = signaled_leases.get(lease_id)
        signum = signal.SIGKILL if previous == signal.SIGTERM else signal.SIGTERM
        if not _signal_holder(pid, state.get("starttime"), signum):
            continue
        signaled_leases[lease_id] = signum
        print(
            reclaim_message(
                pid,
                int(state.get("granted", 1)),
                reason,
                action="signaled",
                stale=stale,
                max_hold=max_hold,
            ),
            file=sys.stderr,
            flush=True,
        )

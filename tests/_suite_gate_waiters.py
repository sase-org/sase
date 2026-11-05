"""Cross-process FIFO tickets for the pytest worker-token pool."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from sase.core.process_identity import process_identity_token


WAITERS_FILE_NAME = "waiters.json"
_MAX_BACKFILL_GRANTS_PER_WAITER = 1


def read_waiter_state(directory: Path) -> dict[str, Any]:
    """Read the queue; callers serialize access with the pool's flock."""
    path = directory / WAITERS_FILE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": 1, "next_ticket": 1, "waiters": []}
    try:
        parsed: Any = json.loads(raw)
        if not isinstance(parsed, dict) or parsed.get("version") != 1:
            raise ValueError("unsupported waiter-state version")
        next_ticket = int(parsed["next_ticket"])
        waiters = parsed["waiters"]
        if next_ticket < 1 or not isinstance(waiters, list):
            raise ValueError("invalid waiter-state shape")
        for entry in waiters:
            if not isinstance(entry, dict):
                raise ValueError("invalid waiter entry")
            ticket = int(entry["ticket"])
            pid = int(entry["pid"])
            floor = int(entry["floor"])
            backfills = int(entry["backfills"])
            identity = entry["process_identity"]
            if (
                ticket < 1
                or pid < 1
                or floor < 1
                or backfills < 0
                or not isinstance(identity, str)
                or not identity
                or ":" not in identity
            ):
                raise ValueError("invalid waiter identity or counters")
            entry.update(ticket=ticket, pid=pid, floor=floor, backfills=backfills)
        if any(int(entry["ticket"]) >= next_ticket for entry in waiters):
            raise ValueError("waiter ticket sequence moved backwards")
        return {"version": 1, "next_ticket": next_ticket, "waiters": waiters}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise pytest.UsageError(
            "The pytest worker-token waiter queue is malformed. Wait for active "
            f"holders to exit, then remove {path} before retrying."
        ) from error


def write_waiter_state(directory: Path, state: dict[str, Any]) -> None:
    """Atomically persist queue changes while the caller holds the pool lock."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / WAITERS_FILE_NAME
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".worker-token-waiters-",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(
                {
                    "version": 1,
                    "next_ticket": int(state["next_ticket"]),
                    "waiters": state["waiters"],
                },
                temporary,
                sort_keys=True,
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        try:
            directory_fd = os.open(
                directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def remove_dead_waiters(
    waiters: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Drop tickets whose PID is gone or now belongs to another process."""
    live = [entry for entry in waiters if _waiter_process_is_live(entry)]
    return live, len(live) != len(waiters)


def _waiter_process_is_live(entry: dict[str, Any]) -> bool:
    pid = int(entry["pid"])
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    current_identity = process_identity_token(pid)
    if not current_identity:
        # Missing evidence is not enough to discard a ticket. A later poll can
        # reclaim it once process identity becomes verifiable.
        return True
    return current_identity == entry["process_identity"]


def find_waiter(
    waiters: list[dict[str, Any]], ticket: int | None
) -> dict[str, Any] | None:
    if ticket is None:
        return None
    return next((entry for entry in waiters if int(entry["ticket"]) == ticket), None)


def bounded_grant_limit(
    *,
    floor: int,
    ceiling: int,
    available: int,
    waiters: list[dict[str, Any]],
    requester_ticket: int,
) -> tuple[int, set[int]]:
    """Reserve older floors and permit one bounded grant past each waiter."""
    if available < floor:
        return 0, set()
    requester_index = next(
        (
            index
            for index, entry in enumerate(waiters)
            if int(entry["ticket"]) == requester_ticket
        ),
        len(waiters),
    )
    grant_limit = min(ceiling, available)
    backfilled: set[int] = set()
    for older in waiters[:requester_index]:
        if int(older["backfills"]) >= _MAX_BACKFILL_GRANTS_PER_WAITER:
            return 0, set()
        older_floor = int(older["floor"])
        if available >= older_floor:
            # Keep enough free capacity for this older waiter to reach its floor.
            grant_limit = min(grant_limit, available - older_floor)
        else:
            # One younger grant may use some capacity while the older floor is
            # still out of reach, but it cannot consume the whole reservation.
            grant_limit = min(grant_limit, older_floor - 1)
        if grant_limit < floor:
            return 0, set()
        backfilled.add(int(older["ticket"]))
    return grant_limit, backfilled

"""In-flight scheduler launch detection for quit/restart guards.

Internal helper module — public API is re-exported through
``sase.axe.state``. Do not import from this module directly.

A chop run is in-flight when its routine is alive, its newest run is still
``running``, its result file already lists ``proposed_launches``, and fewer
durable launch records exist than were proposed. Job-script-phase runs (no
result yet) and ``launched`` runs are excluded: job scripts are short and
re-run on the next tick, and launched agents survive a scheduler stop because
runners are detached.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import sase.axe.state as _state  # noqa: I001


@dataclass(frozen=True)
class InflightChopLaunch:
    """One chop run partway through launching its proposals."""

    lumberjack_name: str
    chop_name: str
    run_id: str
    started_at: str
    proposed_count: int
    launched_count: int
    clan: str | None = None

    @property
    def remaining_count(self) -> int:
        """Return how many proposed launches have not been recorded yet."""
        return max(0, self.proposed_count - self.launched_count)

    def summary_line(self) -> str:
        """Render the quit-guard line for this run."""
        if self.clan:
            head = f"Scheduler is launching {self.chop_name} ({self.clan})"
        else:
            head = f"Scheduler is launching {self.chop_name}"
        return (
            f"{head}: {self.launched_count}/{self.proposed_count} agents "
            f"launched \u2014 stopping it drops the remaining "
            f"{self.remaining_count}"
        )


def _pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _list_chop_names(lumberjack_name: str) -> list[str]:
    try:
        chops_dir = _state.lumberjack_state_dir(lumberjack_name) / "chops"
        if not chops_dir.exists():
            return []
        return sorted(d.name for d in chops_dir.iterdir() if d.is_dir())
    except OSError:
        return []


def _read_proposed_launches(
    lumberjack_name: str, chop_name: str, run_id: str
) -> list[dict[str, Any]] | None:
    try:
        path = _state.chop_run_result_path(lumberjack_name, chop_name, run_id)
    except Exception:
        return None
    try:
        data = _state.read_json(path)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    proposed = data.get("proposed_launches")
    if not isinstance(proposed, list) or not proposed:
        return None
    return [item for item in proposed if isinstance(item, dict)] or None


def _clan_from_proposals(proposed: list[dict[str, Any]]) -> str | None:
    for item in proposed:
        clan = item.get("clan")
        if isinstance(clan, str) and clan:
            return clan
    return None


def _count_launched(lumberjack_name: str, chop_name: str, run_id: str) -> int | None:
    try:
        from sase.axe.chop_agents import get_chop_agent_records

        records = get_chop_agent_records(
            lumberjack_name, chop_name=chop_name, run_id=run_id
        )
        return len(records)
    except Exception:
        return None


def find_inflight_chop_launches() -> list[InflightChopLaunch]:
    """Return chop runs that would lose unlaunched proposals on scheduler stop.

    Read-only and bounded: newest run only per chop, no log tails. Never
    raises; unreadable or corrupt entries are skipped.

    Clan proposals reach agents through two in-process paths in
    ``chop_proposal_launch.py`` — the typed-admission ``%if`` dispatch and
    the multi-prompt loop — but both record launches into the same
    ``agent_chops.json`` registry from the routine process. The status-based
    rule below therefore holds either way.
    """
    found: list[InflightChopLaunch] = []
    try:
        lumberjacks = _state.list_lumberjack_names()
    except Exception:
        return []
    for lumberjack_name in lumberjacks:
        try:
            pid = _state.read_lumberjack_pid(lumberjack_name)
        except Exception:
            continue
        if not _pid_is_alive(pid):
            continue
        try:
            chop_names = _list_chop_names(lumberjack_name)
        except Exception:
            continue
        for chop_name in chop_names:
            try:
                index = _state.read_chop_run_index(lumberjack_name, chop_name)
            except Exception:
                continue
            if not index:
                continue
            run_id = index[0]
            try:
                entry = _state.read_chop_run(lumberjack_name, chop_name, run_id)
            except Exception:
                continue
            if entry is None:
                continue
            if entry.status != "running" or entry.finished_at is not None:
                continue
            proposed = _read_proposed_launches(lumberjack_name, chop_name, run_id)
            if not proposed:
                continue
            launched = _count_launched(lumberjack_name, chop_name, run_id)
            if launched is None:
                continue
            if launched >= len(proposed):
                continue
            found.append(
                InflightChopLaunch(
                    lumberjack_name=lumberjack_name,
                    chop_name=chop_name,
                    run_id=run_id,
                    started_at=entry.started_at,
                    proposed_count=len(proposed),
                    launched_count=launched,
                    clan=_clan_from_proposals(proposed),
                )
            )
    return found


__all__ = ["InflightChopLaunch", "find_inflight_chop_launches"]

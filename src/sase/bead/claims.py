"""Failure-tolerant lifecycle helpers for waiting-agent bead claims."""

from __future__ import annotations

import random
import sys
import time

from sase.bead.model import Status

_MAX_CLAIM_ATTEMPTS = 3
_CLAIM_RETRY_DELAY_SECONDS = 0.1


def claim_bead_for_waiting_agent(
    *,
    project_name: str,
    bead_id: str,
    agent_name: str,
) -> bool:
    """Claim *bead_id* in its canonical store without blocking agent startup."""
    try:
        from sase.bead.store_locator import (
            canonical_beads_dir_for_project,
            open_bead_project_for_beads_dir,
        )
        from sase.bead.sync import commit_bead_claim, refresh_bead_store

        beads_dir = canonical_beads_dir_for_project(project_name)
        if beads_dir is None:
            raise RuntimeError(f"no canonical bead store for project '{project_name}'")

        refreshed = False
        for attempt in range(_MAX_CLAIM_ATTEMPTS):
            try:
                with open_bead_project_for_beads_dir(beads_dir) as project:
                    issue, changed = project.claim_for_agent_wait(bead_id, agent_name)

                held_by_us = (
                    issue.status == Status.CLAIMED and issue.assignee == agent_name
                )
                if changed:
                    commit_bead_claim(beads_dir, bead_id, agent_name)

                if held_by_us:
                    action = "Claimed" if changed else "Retained claim on"
                    print(f"{action} bead {bead_id} for waiting agent {agent_name}")
                else:
                    holder = issue.assignee or "<unassigned>"
                    print(
                        f"Bead {bead_id} claim declined: "
                        f"status={issue.status.value}, holder={holder}"
                    )
                return held_by_us
            except Exception as exc:
                is_missing = _is_missing_bead_error(exc)
                is_lock_timeout = _is_lock_timeout_error(exc)
                if (
                    not (is_missing or is_lock_timeout)
                    or attempt + 1 >= _MAX_CLAIM_ATTEMPTS
                ):
                    raise
                if is_missing and not refreshed:
                    refresh_bead_store(beads_dir)
                    refreshed = True
                    continue
                _sleep_before_claim_retry()
        raise RuntimeError("claim retry budget ended without a terminal outcome")
    except Exception as exc:  # noqa: BLE001 - claims are advisory visibility.
        print(
            f"Warning: Failed to claim bead '{bead_id}' for waiting agent "
            f"'{agent_name}': {exc}",
            file=sys.stderr,
        )
        return False


def _is_missing_bead_error(exc: Exception) -> bool:
    return isinstance(exc, KeyError) and "Issue not found:" in str(exc)


def _is_lock_timeout_error(exc: Exception) -> bool:
    return "lock_timeout:" in str(exc).lower()


def _sleep_before_claim_retry() -> None:
    time.sleep(
        random.uniform(
            _CLAIM_RETRY_DELAY_SECONDS / 2,
            _CLAIM_RETRY_DELAY_SECONDS * 3 / 2,
        )
    )


def release_bead_claim_for_agent(
    *,
    project_name: str,
    bead_id: str,
    agent_name: str,
) -> bool:
    """Release *agent_name*'s waiting claim without disrupting shutdown."""
    try:
        from sase.bead.store_locator import (
            canonical_beads_dir_for_project,
            open_bead_project_for_beads_dir,
        )
        from sase.bead.sync import commit_bead_claim_release

        beads_dir = canonical_beads_dir_for_project(project_name)
        if beads_dir is None:
            raise RuntimeError(f"no canonical bead store for project '{project_name}'")

        with open_bead_project_for_beads_dir(beads_dir) as project:
            issue, changed = project.release_agent_claim(bead_id, agent_name)

        if changed:
            commit_bead_claim_release(beads_dir, bead_id, agent_name)
            print(f"Released bead claim on {bead_id} from waiting agent {agent_name}")
        return changed
    except Exception as exc:  # noqa: BLE001 - shutdown must remain best effort.
        print(
            f"Warning: Failed to release bead claim on '{bead_id}' from agent "
            f"'{agent_name}': {exc}",
            file=sys.stderr,
        )
        return False


__all__ = [
    "claim_bead_for_waiting_agent",
    "release_bead_claim_for_agent",
]

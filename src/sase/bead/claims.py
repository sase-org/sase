"""Failure-tolerant lifecycle helpers for waiting-agent bead claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
import random
from pathlib import Path
import sys
import time
from typing import Any

from sase.bead._store_contention import is_bead_store_lock_timeout
from sase.bead.model import Status

BEAD_CLAIM_MARKER = "bead_claim.json"
_MAX_CLAIM_ATTEMPTS = 3
_CLAIM_RETRY_DELAY_SECONDS = 0.1


@dataclass(frozen=True)
class BeadClaimMarker:
    bead_id: str
    agent_name: str
    project_name: str


class BeadClaimReleaseOutcome(Enum):
    """Terminal result of a best-effort waiting-claim release."""

    RELEASED = "released"
    NOTHING_TO_RELEASE = "nothing_to_release"
    ERROR = "error"


def _bead_claim_marker_path(artifacts_dir: str | Path) -> Path:
    return Path(artifacts_dir) / BEAD_CLAIM_MARKER


def _warn_marker_action(action: str, path: Path, exc: BaseException | str) -> None:
    print(
        f"Warning: Failed to {action} bead claim marker {path}: {exc}", file=sys.stderr
    )


def _marker_from_payload(path: Path, payload: Any) -> BeadClaimMarker | None:
    if not isinstance(payload, dict):
        _warn_marker_action("read", path, "expected JSON object")
        return None

    bead_id = payload.get("bead_id")
    agent_name = payload.get("agent_name")
    project_name = payload.get("project_name")
    if not (
        isinstance(bead_id, str)
        and bead_id
        and isinstance(agent_name, str)
        and agent_name
        and isinstance(project_name, str)
        and project_name
    ):
        _warn_marker_action(
            "read",
            path,
            "expected non-empty bead_id, agent_name, and project_name strings",
        )
        return None

    return BeadClaimMarker(
        bead_id=bead_id,
        agent_name=agent_name,
        project_name=project_name,
    )


def read_bead_claim_marker(artifacts_dir: str | Path) -> BeadClaimMarker | None:
    path = _bead_claim_marker_path(artifacts_dir)
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        _warn_marker_action("read", path, exc)
        return None
    return _marker_from_payload(path, payload)


def write_bead_claim_marker(
    artifacts_dir: str | Path,
    *,
    project_name: str,
    bead_id: str,
    agent_name: str,
) -> bool:
    path = _bead_claim_marker_path(artifacts_dir)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {
        "bead_id": bead_id,
        "agent_name": agent_name,
        "project_name": project_name,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        tmp_path.replace(path)
    except OSError as exc:
        _warn_marker_action("write", path, exc)
        try:
            tmp_path.unlink()
        except OSError:
            pass
        return False
    return True


def clear_bead_claim_marker(artifacts_dir: str | Path) -> bool:
    path = _bead_claim_marker_path(artifacts_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError as exc:
        _warn_marker_action("clear", path, exc)
        return False
    return True


def claim_bead_for_waiting_agent(
    *,
    project_name: str,
    bead_id: str,
    agent_name: str,
) -> bool:
    """Claim *bead_id* locally, then synchronously publish without rollback."""
    if project_name == "home":
        return False

    try:
        from sase.bead.background_store import (
            WritableBeadStore,
            schedule_beads_sidecar_convergence,
            writable_bead_store_for_machine,
        )
        from sase.bead.store_locator import open_bead_project_for_beads_dir
        from sase.bead.sync import (
            bead_store_write_lock,
            commit_bead_claim,
            publish_bead_claim,
            refresh_bead_store,
        )

        store: WritableBeadStore
        with writable_bead_store_for_machine(
            project_name,
            workflow="bead_claim",
            holder=f"wait-claim:{agent_name}",
            prefer_existing_claim=True,
        ) as store:
            beads_dir = store.beads_dir
            refreshed = False
            for attempt in range(_MAX_CLAIM_ATTEMPTS):
                try:
                    committed = False
                    with bead_store_write_lock(beads_dir) as already_locked:
                        with open_bead_project_for_beads_dir(beads_dir) as project:
                            issue, changed = project.claim_for_agent_wait(
                                bead_id, agent_name
                            )

                        held_by_us = (
                            issue.status in {Status.CLAIMED, Status.IN_PROGRESS}
                            and issue.assignee == agent_name
                        )
                        if changed:
                            committed = commit_bead_claim(
                                beads_dir,
                                bead_id,
                                agent_name,
                                already_locked=already_locked,
                                mutation_origin="machine",
                                operation_context=store.context,
                            )

                    if committed:
                        publish_bead_claim(beads_dir, bead_id, agent_name)
                        schedule_beads_sidecar_convergence(store.project)
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
                    is_lock_timeout = is_bead_store_lock_timeout(exc)
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


def retain_in_progress_bead_for_replacement(
    *,
    project_name: str,
    bead_id: str,
    agent_name: str,
    prior_owner: str,
) -> bool:
    """Return true when a confirmed replacement already owns an in-progress bead."""
    if project_name == "home":
        return False

    try:
        from sase.bead.background_store import writable_bead_store_for_machine
        from sase.bead.force_reuse import issue_retains_force_reuse_owner
        from sase.bead.store_locator import open_bead_project_for_beads_dir
        from sase.bead.sync import bead_store_write_lock

        with writable_bead_store_for_machine(
            project_name,
            workflow="bead_claim",
            holder=f"wait-retain:{agent_name}",
            prefer_existing_claim=True,
        ) as store:
            beads_dir = store.beads_dir
            with bead_store_write_lock(beads_dir):
                with open_bead_project_for_beads_dir(beads_dir) as project:
                    issue = project.show(bead_id)

        if not issue_retains_force_reuse_owner(
            issue,
            agent_name=agent_name,
            prior_owner=prior_owner,
        ):
            return False
        print(f"Retained in-progress bead {bead_id} for replacement agent {agent_name}")
        return True
    except Exception as exc:  # noqa: BLE001 - replacement retention is advisory.
        print(
            f"Warning: Failed to retain bead '{bead_id}' for replacement agent "
            f"'{agent_name}': {exc}",
            file=sys.stderr,
        )
        return False


def _is_missing_bead_error(exc: Exception) -> bool:
    return isinstance(exc, KeyError) and "Issue not found:" in str(exc)


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
) -> BeadClaimReleaseOutcome:
    """Release and publish *agent_name*'s claim without disrupting shutdown."""
    try:
        from sase.bead.background_store import (
            schedule_beads_sidecar_convergence,
            writable_bead_store_for_machine,
        )
        from sase.bead.store_locator import open_bead_project_for_beads_dir
        from sase.bead.sync import (
            bead_store_write_lock,
            commit_bead_claim_release,
            publish_bead_claim,
        )

        with writable_bead_store_for_machine(
            project_name,
            workflow="bead_claim",
            holder=f"wait-release:{agent_name}",
            prefer_existing_claim=True,
        ) as store:
            beads_dir = store.beads_dir
            committed = False
            with bead_store_write_lock(beads_dir) as already_locked:
                with open_bead_project_for_beads_dir(beads_dir) as project:
                    _issue, changed = project.release_agent_claim(bead_id, agent_name)

                if changed:
                    committed = commit_bead_claim_release(
                        beads_dir,
                        bead_id,
                        agent_name,
                        already_locked=already_locked,
                        mutation_origin="machine",
                        operation_context=store.context,
                    )
            if committed:
                publish_bead_claim(beads_dir, bead_id, agent_name)
                schedule_beads_sidecar_convergence(store.project)
            if changed:
                print(
                    f"Released bead claim on {bead_id} from waiting agent {agent_name}"
                )
                return BeadClaimReleaseOutcome.RELEASED
            return BeadClaimReleaseOutcome.NOTHING_TO_RELEASE
    except Exception as exc:  # noqa: BLE001 - shutdown must remain best effort.
        print(
            f"Warning: Failed to release bead claim on '{bead_id}' from agent "
            f"'{agent_name}': {exc}",
            file=sys.stderr,
        )
        return BeadClaimReleaseOutcome.ERROR


__all__ = [
    "BEAD_CLAIM_MARKER",
    "BeadClaimMarker",
    "BeadClaimReleaseOutcome",
    "claim_bead_for_waiting_agent",
    "clear_bead_claim_marker",
    "read_bead_claim_marker",
    "release_bead_claim_for_agent",
    "write_bead_claim_marker",
]

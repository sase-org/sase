"""Failure-tolerant lifecycle helpers for waiting-agent bead claims."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import random
from pathlib import Path
import sys
import time
from typing import Any

from sase.bead.model import Status

BEAD_CLAIM_MARKER = "bead_claim.json"
_MAX_CLAIM_ATTEMPTS = 3
_CLAIM_RETRY_DELAY_SECONDS = 0.1


@dataclass(frozen=True)
class BeadClaimMarker:
    bead_id: str
    agent_name: str
    project_name: str


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
    try:
        from sase.bead.store_locator import (
            canonical_beads_dir_for_project,
            open_bead_project_for_beads_dir,
        )
        from sase.bead.sync import (
            bead_store_write_lock,
            commit_bead_claim,
            publish_bead_claim,
            refresh_bead_store,
        )

        beads_dir = canonical_beads_dir_for_project(project_name)
        if beads_dir is None:
            raise RuntimeError(f"no canonical bead store for project '{project_name}'")

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
                        issue.status == Status.CLAIMED and issue.assignee == agent_name
                    )
                    if changed:
                        if already_locked:
                            committed = commit_bead_claim(
                                beads_dir,
                                bead_id,
                                agent_name,
                                already_locked=True,
                            )
                        else:
                            committed = commit_bead_claim(
                                beads_dir, bead_id, agent_name
                            )

                if committed:
                    publish_bead_claim(beads_dir, bead_id, agent_name)
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
    """Release and publish *agent_name*'s claim without disrupting shutdown."""
    try:
        from sase.bead.store_locator import (
            canonical_beads_dir_for_project,
            open_bead_project_for_beads_dir,
        )
        from sase.bead.sync import (
            bead_store_write_lock,
            commit_bead_claim_release,
            publish_bead_claim,
        )

        beads_dir = canonical_beads_dir_for_project(project_name)
        if beads_dir is None:
            raise RuntimeError(f"no canonical bead store for project '{project_name}'")

        committed = False
        with bead_store_write_lock(beads_dir) as already_locked:
            with open_bead_project_for_beads_dir(beads_dir) as project:
                _issue, changed = project.release_agent_claim(bead_id, agent_name)

            if changed:
                if already_locked:
                    committed = commit_bead_claim_release(
                        beads_dir,
                        bead_id,
                        agent_name,
                        already_locked=True,
                    )
                else:
                    committed = commit_bead_claim_release(
                        beads_dir, bead_id, agent_name
                    )
        if committed:
            publish_bead_claim(beads_dir, bead_id, agent_name)
        if changed:
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
    "BEAD_CLAIM_MARKER",
    "BeadClaimMarker",
    "claim_bead_for_waiting_agent",
    "clear_bead_claim_marker",
    "read_bead_claim_marker",
    "release_bead_claim_for_agent",
    "write_bead_claim_marker",
]

"""Collect launch evidence used to reconcile interrupted chop batches."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def collect_spawn_observations(
    routine: str, job: str, manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Build the complete spawn-evidence snapshot for one batch.

    Durable chop-agent linkage proves a launch even when the member row
    is still ``pending`` (the stop landed in the spawn/ack window): a
    record for this routine/job/run whose proposal index (or non-empty
    proposal id) matches the member is ``matched_spawn``. ``cl_name`` is
    the project name or VCS ref, never a member identity, so it is never
    compared here. A live or visible agent that owns the name without
    that linkage is a ``foreign_conflict`` and is never relaunched under
    a new identity. The durable name registry tells a provably unspawned
    reservation (``reservation_only``, which may relaunch after its
    reserver died) from a reservation whose reserving process is still
    alive (``live_owner``). A PID alone is never launch proof. Absent
    observations mean the caller proved no reservation or spawn evidence
    exists, so the member is safe to launch.
    """
    from .chop_agents import get_chop_agent_records

    members = manifest.get("members")
    if not isinstance(members, list):
        return []
    batch_id = str(manifest.get("batch_id") or "")
    run = manifest.get("run")
    run_id = batch_id
    if isinstance(run, Mapping):
        run_id = str(run.get("run_id") or batch_id)
    try:
        records = get_chop_agent_records(routine, chop_name=job, run_id=run_id)
    except Exception:
        records = []
    linked_indexes: set[int] = set()
    linked_proposal_ids: set[str] = set()
    for record in records:
        proposal_index = getattr(record, "proposal_index", None)
        if isinstance(proposal_index, int) and not isinstance(proposal_index, bool):
            linked_indexes.add(proposal_index)
        proposal_id = getattr(record, "proposal_id", "")
        if isinstance(proposal_id, str) and proposal_id:
            linked_proposal_ids.add(proposal_id)
    try:
        from sase.agent.names import get_active_agent_names

        live_names = set(get_active_agent_names())
    except Exception:
        live_names = set()
    observations: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, Mapping):
            continue
        status = str(member.get("status") or "pending")
        if status not in {"pending", "dispatching"}:
            continue
        name = str(member.get("agent_name") or "")
        if not name:
            continue
        source_index = member.get("source_index")
        proposal_id = member.get("proposal_id")
        linked = (
            isinstance(source_index, int)
            and not isinstance(source_index, bool)
            and source_index in linked_indexes
        ) or (
            isinstance(proposal_id, str)
            and bool(proposal_id)
            and proposal_id in linked_proposal_ids
        )
        if linked:
            observations.append({"agent_name": name, "observation": "matched_spawn"})
        elif name in live_names or _name_has_foreign_owner(name):
            observations.append({"agent_name": name, "observation": "foreign_conflict"})
        else:
            entry = _lookup_registry_entry(name)
            if entry is None:
                continue
            if _registry_reservation_is_live(entry):
                observations.append({"agent_name": name, "observation": "live_owner"})
            else:
                observations.append(
                    {"agent_name": name, "observation": "reservation_only"}
                )
    return observations


def _lookup_registry_entry(name: str) -> dict[str, Any] | None:
    """Return the durable registry entry reserving *name*, if any."""
    try:
        from sase.agent.names import lookup_registered_name

        entry = lookup_registered_name(name)
    except Exception:
        return None
    return entry if isinstance(entry, dict) else None


def _name_has_foreign_owner(name: str) -> bool:
    """Return whether *name* sits inside a reserved foreign owner namespace."""
    try:
        from sase.agent.names import get_blocked_local_namespace_roots

        blocked = get_blocked_local_namespace_roots()
    except Exception:
        return False
    if not isinstance(blocked, Mapping):
        return False
    return any(
        name == root or name.startswith(f"{root}.")
        for root in blocked
        if isinstance(root, str) and root
    )


def _registry_reservation_is_live(entry: Mapping[str, Any]) -> bool:
    """Return whether the process behind a registry reservation is alive.

    Liveness is proven through the reservation's artifact metadata PID, so
    a planned reservation that never published artifacts (a reserver that
    died before spawn, or a claim no live process can substantiate) reads
    as unspawned. A racing live executor holding only a planned
    reservation is indistinguishable here; batch ownership (a later phase)
    closes that race.
    """
    artifacts_dir = entry.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return False
    try:
        from sase.agent.names._common import is_process_alive

        directory = Path(artifacts_dir)
        raw = (directory / "agent_meta.json").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        import json

        meta = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(meta, dict):
        return False
    try:
        return bool(is_process_alive(meta, directory))
    except Exception:
        return False

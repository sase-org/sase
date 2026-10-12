"""Assemble Configure-stage planner facts from already-observed TUI state.

Typing never gathers facts or probes a provider. The Source probe cache and
local inventory supply whatever observation exists; missing remote fields stay
absent so the planner can show unknown honestly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_REMOTE_FIELDS = (
    "status",
    "visibility",
    "is_empty",
    "is_archived",
    "can_push",
    "sase_managed",
    "repo_id",
    "default_branch",
    "message",
    "web_url",
)


def remote_facts_from_probe(probe: Any | None) -> dict[str, Any] | None:
    """Copy provider-probe fields the planner already understands."""
    if probe is None:
        return None
    status = str(getattr(probe, "status", "") or "unavailable")
    if status not in {"found", "not_found", "unavailable"}:
        status = "unavailable"
    remote: dict[str, Any] = {
        "status": status,
        "visibility": str(getattr(probe, "visibility", "") or ""),
        "can_push": getattr(probe, "can_push", None),
        "sase_managed": getattr(probe, "sase_managed", None),
        "repo_id": str(getattr(probe, "repo_id", "") or ""),
        "default_branch": str(getattr(probe, "default_branch", "") or ""),
        "message": str(getattr(probe, "message", "") or ""),
        "web_url": str(getattr(probe, "web_url", "") or ""),
    }
    is_empty = getattr(probe, "is_empty", None)
    if is_empty is not None:
        remote["is_empty"] = is_empty
    is_archived = getattr(probe, "is_archived", None)
    if is_archived is not None:
        remote["is_archived"] = is_archived
    return {key: remote[key] for key in _REMOTE_FIELDS if key in remote}


def matching_project_record(
    records: Sequence[Mapping[str, Any]],
    identity_key: str,
) -> dict[str, Any] | None:
    """Return the inventory record for *identity_key*, if one exists."""
    wanted = identity_key.casefold()
    if not wanted:
        return None
    for record in records:
        keys = record.get("identity_keys") or ()
        if any(str(item).casefold() == wanted for item in keys):
            return dict(record)
        if str(record.get("identity_key") or "").casefold() == wanted:
            return dict(record)
    return None


def _checkout_facts_from_source(
    *, group: str, checkout_dir: str
) -> dict[str, Any] | None:
    """Describe a local clone already classified by Source inventory.

    This does not run git. Discovery already attached the path to this identity
    when *group* is ``local``.
    """
    if group != "local" or not checkout_dir:
        return None
    return {
        "state": "matching",
        "origin_url": "",
        "config_dirty": False,
        "on_default_branch": None,
    }


def assemble_configure_facts(
    *,
    records: Sequence[Mapping[str, Any]],
    probe: Any | None,
    identity_key: str,
    source_group: str,
    checkout_dir: str,
) -> dict[str, Any]:
    """Build planner facts from the Source cache and local inventory."""
    projects = [
        {
            "key": str(record.get("key") or ""),
            "name": str(record.get("name") or ""),
            "aliases": list(record.get("aliases") or []),
            "state": str(record.get("state") or "enabled"),
        }
        for record in records
    ]
    facts: dict[str, Any] = {"projects": projects}
    remote = remote_facts_from_probe(probe)
    if remote is not None:
        facts["remote"] = remote
    matching = matching_project_record(records, identity_key)
    if matching is not None:
        facts["record"] = {
            "key": str(matching.get("key") or ""),
            "name": str(matching.get("name") or ""),
            "aliases": list(matching.get("aliases") or []),
            "state": str(matching.get("state") or "enabled"),
        }
    checkout = _checkout_facts_from_source(
        group=source_group, checkout_dir=checkout_dir
    )
    if checkout is not None:
        facts["checkout"] = checkout
    return facts


__all__ = [
    "assemble_configure_facts",
    "_checkout_facts_from_source",
    "matching_project_record",
    "remote_facts_from_probe",
]

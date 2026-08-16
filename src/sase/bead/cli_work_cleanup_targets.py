"""Owner discovery and target classification for bead-work cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.cli_work_cleanup_types import (
    BeadWorkSlot,
    CleanupAction,
    CleanupTarget,
)
from sase.bead.cli_work_name_cleanup import ForcedReuseCleanupError

if TYPE_CHECKING:
    from sase.core.agent_identity_facade import AgentIdentitySnapshot
    from sase.core.agent_scan_wire import AgentArtifactRecordWire


@dataclass(frozen=True)
class _AgentOwnerView:
    """Indexed agent artifacts used to classify registered owners."""

    records_by_artifact_dir: dict[str, AgentArtifactRecordWire]
    family_members_by_key: dict[str, tuple[AgentArtifactRecordWire, ...]]
    clan_members_by_key: dict[str, tuple[AgentArtifactRecordWire, ...]]
    identity: AgentIdentitySnapshot


def load_agent_owner_view() -> _AgentOwnerView:
    """Scan agent artifacts and index them by owner container."""
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
    )
    from sase.core.agent_scan_facade import scan_agent_artifacts
    from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
    from sase.core.paths import sase_projects_dir

    identity = AgentIdentitySnapshot.current()
    snapshot = scan_agent_artifacts(
        sase_projects_dir(),
        AgentArtifactScanOptionsWire(
            include_prompt_step_markers=False,
            only_workflow_dirs=("ace-run",),
        ),
    )
    records_by_artifact_dir: dict[str, AgentArtifactRecordWire] = {}
    family_members: dict[str, list[AgentArtifactRecordWire]] = {}
    clan_members: dict[str, list[AgentArtifactRecordWire]] = {}
    for record in snapshot.records:
        records_by_artifact_dir[_normalized_path_key(record.artifact_dir)] = record
        meta = record.agent_meta
        if meta is None:
            continue
        family_name = meta.agent_family or (
            meta.workflow_name if meta.agent_family_role else None
        )
        if family_name:
            key = current_owner_agent_name_key(family_name, identity)
            family_members.setdefault(key, []).append(record)
        if meta.agent_clan:
            key = current_owner_agent_name_key(meta.agent_clan, identity)
            clan_members.setdefault(key, []).append(record)

    return _AgentOwnerView(
        records_by_artifact_dir=records_by_artifact_dir,
        family_members_by_key={
            key: tuple(value) for key, value in family_members.items()
        },
        clan_members_by_key={key: tuple(value) for key, value in clan_members.items()},
        identity=identity,
    )


def _normalized_path_key(value: object) -> str:
    return str(Path(str(value)).expanduser().resolve(strict=False))


def classify_slot_owner(
    slot: BeadWorkSlot,
    owner: dict[str, object],
    *,
    bead_assignees: dict[str, str],
    view: _AgentOwnerView,
) -> tuple[CleanupTarget, ...] | None:
    """Classify one registered name as preserved or safe to clean up."""
    container_kind = owner.get("container_kind")
    if container_kind == "family":
        return _classify_family_owner(
            slot,
            bead_assignees=bead_assignees,
            view=view,
        )
    if container_kind == "clan":
        return _classify_clan_owner(
            slot,
            bead_assignees=bead_assignees,
            view=view,
        )

    record = _record_for_owner(owner, view)
    if record is None:
        return (
            _classify_stale_registry_owner(
                slot,
                owner,
                bead_assignees=bead_assignees,
            ),
        )
    return (
        _classify_artifact_record(
            slot,
            record,
            owner_name=slot.owner_name,
            bead_assignees=bead_assignees,
        ),
    )


def _record_for_owner(
    owner: dict[str, object],
    view: _AgentOwnerView,
) -> AgentArtifactRecordWire | None:
    artifacts_dir = owner.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return None
    return view.records_by_artifact_dir.get(_normalized_path_key(artifacts_dir))


def _classify_family_owner(
    slot: BeadWorkSlot,
    *,
    bead_assignees: dict[str, str],
    view: _AgentOwnerView,
) -> tuple[CleanupTarget, ...]:
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    key = current_owner_agent_name_key(slot.owner_name, view.identity)
    members = view.family_members_by_key.get(key, ())
    if not members:
        return (
            CleanupTarget(
                name=slot.owner_name,
                action="RELEASE",
                current_state="stale",
                detail=f"orphaned family reservation for bead {slot.expected_bead_id}",
                expected_bead_id=slot.expected_bead_id,
                slot_id=slot.slot_id,
            ),
        )

    member_targets = tuple(
        _classify_artifact_record(
            slot,
            member,
            owner_name=_record_agent_name(member) or slot.owner_name,
            bead_assignees=bead_assignees,
        )
        for member in members
    )
    if any(target.preserved for target in member_targets):
        preserved = next(target for target in member_targets if target.preserved)
        return (
            CleanupTarget(
                name=slot.owner_name,
                action="PRESERVE",
                current_state=preserved.current_state,
                detail=f"family member {preserved.name} {preserved.detail}",
                expected_bead_id=slot.expected_bead_id,
                slot_id=slot.slot_id,
                artifacts_dir=preserved.artifacts_dir,
                generation=preserved.generation,
            ),
        )
    return member_targets


def _classify_clan_owner(
    slot: BeadWorkSlot,
    *,
    bead_assignees: dict[str, str],
    view: _AgentOwnerView,
) -> tuple[CleanupTarget, ...] | None:
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    key = current_owner_agent_name_key(slot.owner_name, view.identity)
    members = view.clan_members_by_key.get(key, ())
    if members and slot.allow_populated_clan_skip:
        return None
    if members:
        raise ForcedReuseCleanupError(
            f"agent name '{slot.owner_name}' is reserved by a populated clan "
            "container and cannot be force-reused; retry after the concrete "
            "member finishes or dismiss the conflicting clan"
        )
    return (
        CleanupTarget(
            name=slot.owner_name,
            action="RELEASE",
            current_state="stale",
            detail=f"orphaned clan reservation for bead {slot.expected_bead_id}",
            expected_bead_id=slot.expected_bead_id,
            slot_id=slot.slot_id,
        ),
    )


def _classify_artifact_record(
    slot: BeadWorkSlot,
    record: AgentArtifactRecordWire,
    *,
    owner_name: str,
    bead_assignees: dict[str, str],
) -> CleanupTarget:
    _require_record_bead(slot, record, owner_name=owner_name)
    _require_compatible_assignee(
        slot,
        owner_name=owner_name,
        bead_assignees=bead_assignees,
    )

    current_state = _record_current_state(record)
    detail = f"for bead {slot.expected_bead_id} at {record.artifact_dir}"
    generation = str(getattr(record, "timestamp", ""))
    artifacts_dir = str(getattr(record, "artifact_dir", ""))
    if current_state == "WAITING":
        action: CleanupAction = "KILL"
    elif current_state.startswith("FAILED"):
        action = "REMOVE"
    elif _record_is_live(record):
        action = "PRESERVE"
    else:
        action = "REMOVE"
    return CleanupTarget(
        name=owner_name,
        action=action,
        current_state=current_state,
        detail=detail,
        expected_bead_id=slot.expected_bead_id,
        slot_id=slot.slot_id,
        artifacts_dir=artifacts_dir,
        generation=generation,
    )


def _classify_stale_registry_owner(
    slot: BeadWorkSlot,
    owner: dict[str, object],
    *,
    bead_assignees: dict[str, str],
) -> CleanupTarget:
    _require_compatible_assignee(
        slot,
        owner_name=slot.owner_name,
        bead_assignees=bead_assignees,
    )
    state = owner.get("state")
    current_state = (
        state
        if isinstance(state, str) and state not in {"active", "done"}
        else "completed"
        if state == "done"
        else "interrupted"
    )
    path = owner.get("bundle_path") or owner.get("artifacts_dir")
    detail = (
        f"for bead {slot.expected_bead_id} at {path}"
        if isinstance(path, str) and path
        else f"stored owner for bead {slot.expected_bead_id}"
    )
    return CleanupTarget(
        name=slot.owner_name,
        action="REMOVE",
        current_state=current_state,
        detail=detail,
        expected_bead_id=slot.expected_bead_id,
        slot_id=slot.slot_id,
    )


def _record_agent_name(record: AgentArtifactRecordWire) -> str | None:
    meta = getattr(record, "agent_meta", None)
    value = getattr(meta, "name", None)
    return value if isinstance(value, str) and value else None


def _record_bead_ids(record: AgentArtifactRecordWire) -> set[str]:
    meta = getattr(record, "agent_meta", None)
    if meta is None:
        return set()
    return {
        value
        for value in (
            getattr(meta, "bead_id", None),
            getattr(meta, "phase_bead_id", None),
            getattr(meta, "epic_bead_id", None),
        )
        if isinstance(value, str) and value
    }


def _require_record_bead(
    slot: BeadWorkSlot,
    record: AgentArtifactRecordWire,
    *,
    owner_name: str,
) -> None:
    bead_ids = _record_bead_ids(record)
    if slot.expected_bead_id in bead_ids:
        return
    observed = ", ".join(sorted(bead_ids)) or "none"
    raise ForcedReuseCleanupError(
        f"agent owner '{owner_name}' is not associated with expected bead "
        f"{slot.expected_bead_id}; observed bead association(s): {observed}"
    )


def _require_compatible_assignee(
    slot: BeadWorkSlot,
    *,
    owner_name: str,
    bead_assignees: dict[str, str],
) -> None:
    assignee = bead_assignees.get(slot.expected_bead_id, "")
    if not assignee:
        return
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
    )

    identity = AgentIdentitySnapshot.current()
    allowed = {owner_name}
    if slot.launch_name:
        allowed.add(slot.launch_name)
    assignee_key = current_owner_agent_name_key(assignee, identity)
    if assignee_key in {
        current_owner_agent_name_key(name, identity) for name in allowed
    }:
        return
    raise ForcedReuseCleanupError(
        f"bead {slot.expected_bead_id} is assigned to {assignee}, which does "
        f"not match the relaunch owner {owner_name}"
    )


def _record_current_state(record: AgentArtifactRecordWire) -> str:
    done = getattr(record, "done", None)
    if getattr(record, "has_done_marker", False):
        outcome = getattr(done, "outcome", None)
        if outcome == "failed":
            return "FAILED"
        if isinstance(outcome, str) and outcome:
            return outcome.upper()
        return "DONE"
    if _record_is_live(record):
        from sase.agent.running_listing import active_status_for_record

        status = active_status_for_record(record)
        if status:
            return status
        raise ForcedReuseCleanupError(
            f"agent owner at {record.artifact_dir} has unknown live state"
        )
    return "interrupted"


def _record_is_live(record: AgentArtifactRecordWire) -> bool:
    if getattr(record, "has_done_marker", False):
        return False
    meta = getattr(record, "agent_meta", None)
    if meta is None:
        return False
    meta_dict: dict[str, object] = {}
    pid = getattr(meta, "pid", None)
    if pid is not None:
        meta_dict["pid"] = pid
    stopped_at = getattr(meta, "stopped_at", None)
    if stopped_at is not None:
        meta_dict["stopped_at"] = stopped_at
    from sase.agent.names import is_process_alive

    return is_process_alive(meta_dict, Path(str(record.artifact_dir)))

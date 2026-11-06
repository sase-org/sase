"""Custody exemptions so every release path respects an active hijack.

Stale cleanup, kill persistence, and listing/show consult this module. The
Rust ledger owns the ``held → expired`` transition; Python owns the
snapshot-before-release effects and the TTL clock (``hijacked_at``, not the
claim launch stamp).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sase.agent.hijack.ledger import (
    HijackLedgerConflict,
    cas_advance_record,
    list_active_records,
    load_record,
    load_record_by_agent_name,
    load_record_by_artifacts_dir,
    load_record_by_workspace,
)
from sase.core.time import local_now, parse_local
from sase.notification_gates.durability import atomic_write_json, file_lock
from sase.running_field import WorkspaceClaim

LOG = logging.getLogger(__name__)

HIJACK_EVENT_EXPIRE = "expire"

ACTIVE_CUSTODY_STATES = frozenset({"requested", "stopping", "held", "resolving"})
USER_PARKED_RECOVERY_STATES = frozenset({"pending", "expired"})


def matching_active_record(
    project_file: str, claim: WorkspaceClaim
) -> dict[str, Any] | None:
    """Return the active hijack record for *claim*, if one still holds it.

    A ``resolving`` record pins its ``(project_file, workspace_num)`` pair
    for the whole settlement window, whoever currently holds the claim:
    the predecessor pid, the reserved successor pid, or a dead successor.
    Requested/held records keep exact pid matching so unrelated later
    occupants of a released workspace are unaffected.
    """
    wanted_project = str(project_file)
    wanted_workspace = int(claim.workspace_num)
    wanted_pid = int(claim.pid)
    for record in list_active_records():
        if str(record.get("state") or "") not in ACTIVE_CUSTODY_STATES:
            continue
        if str(record.get("project_file") or "") != wanted_project:
            continue
        try:
            workspace = int(record.get("workspace_num"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if workspace != wanted_workspace:
            continue
        if str(record.get("state") or "") == "resolving":
            if _resolving_claim_matches(record, claim):
                return record
            continue
        expected = record.get("expected_claim_owner_pid")
        if expected is None:
            expected = record.get("pid")
        try:
            if int(expected) != wanted_pid:  # type: ignore[arg-type]
                continue
        except (TypeError, ValueError):
            continue
        return record
    return None


def resolving_record_for_workspace(
    project_file: str, workspace_num: int
) -> dict[str, Any] | None:
    """Return the active ``resolving`` record for a workspace, if any."""
    wanted_project = str(project_file)
    try:
        wanted_workspace = int(workspace_num)
    except (TypeError, ValueError):
        return None
    for record in list_active_records():
        if str(record.get("state") or "") != "resolving":
            continue
        if str(record.get("project_file") or "") != wanted_project:
            continue
        try:
            workspace = int(record.get("workspace_num"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if workspace == wanted_workspace:
            return record
    return None


def _resolving_claim_matches(record: dict[str, Any], claim: WorkspaceClaim) -> bool:
    """Return whether *claim* belongs to a resolving recovery workspace.

    The workspace pair is authoritative. The pid is accepted when it is the
    predecessor's expected owner, the recorded successor pid, or — when the
    record carries launch identity or a reserved successor name — any live
    occupant of the pinned workspace. The latter covers the deferred-dispatch
    window where the claim already moved to the successor pid before
    reconciliation adopts it. Records without any launch/successor evidence
    keep exact matching so a bare resolving row cannot pin a foreign claim.
    """
    try:
        wanted_pid = int(claim.pid)
    except (TypeError, ValueError):
        return False
    for key in ("expected_claim_owner_pid", "pid", "successor_pid"):
        try:
            candidate = record.get(key)
            if candidate is not None and int(candidate) == wanted_pid:  # type: ignore[arg-type]
                return True
        except (TypeError, ValueError):
            continue
    has_launch_evidence = bool(
        str(record.get("launch_identity") or "").strip()
        or str(record.get("admission_request_id") or "").strip()
        or str(record.get("reserved_successor_name") or "").strip()
    )
    return has_launch_evidence


def hijack_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
    """Return whether an active hijack record still owns this claim."""
    return matching_active_record(project_file, claim) is not None


def hijack_skips_claim_release(
    *,
    artifacts_dir: str | None = None,
    project_file: str | None = None,
    workspace_num: int | None = None,
) -> bool:
    """Return whether persist-cleanup must leave this claim pinned."""
    record = None
    if artifacts_dir:
        record = load_record_by_artifacts_dir(artifacts_dir)
    if record is None and project_file and workspace_num is not None:
        record = load_record_by_workspace(project_file, int(workspace_num))
    if record is None:
        return False
    return str(record.get("state") or "") in ACTIVE_CUSTODY_STATES


def hijacked_at_exceeds_ttl(
    hijacked_at: str | None,
    ttl_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether *hijacked_at* is older than the held-claim TTL.

    ``ttl_days <= 0`` disables age-based release. Unparseable stamps keep
    the hold.
    """
    if ttl_days <= 0 or not hijacked_at:
        return False
    parsed = parse_local(hijacked_at)
    if parsed is None:
        return False
    current = local_now() if now is None else now
    parsed_naive = parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    current_naive = current.replace(tzinfo=None) if current.tzinfo else current
    return current_naive - parsed_naive > timedelta(days=ttl_days)


def expire_hijack_hold(
    project_file: str,
    claim: WorkspaceClaim,
    record: dict[str, Any],
) -> bool:
    """Snapshot, expire the ledger record, then release the claim.

    A snapshot failure keeps the hold. Returns True only after the claim
    is released.
    """
    if str(record.get("state") or "") != "held":
        return False
    snapshots, error = _ensure_expiry_snapshots(record)
    if error:
        LOG.warning(
            "hijack %s expiry snapshot failed; keeping hold: %s",
            record.get("hijack_id"),
            error,
        )
        return False
    if snapshots:
        try:
            _merge_record_fields(str(record["hijack_id"]), {"snapshots": snapshots})
        except Exception as exc:
            LOG.warning("could not record expiry snapshots: %s", exc)
            return False
        record = dict(record)
        record["snapshots"] = snapshots
    try:
        expired = cas_advance_record(record, {"event": HIJACK_EVENT_EXPIRE})
    except HijackLedgerConflict as exc:
        LOG.warning("hijack expiry lost the CAS: %s", exc)
        return False
    except Exception as exc:
        LOG.warning("hijack expiry transition failed: %s", exc)
        return False
    artifacts_dir = str(
        expired.get("artifacts_dir") or record.get("artifacts_dir") or ""
    )
    if artifacts_dir:
        try:
            _set_done_recovery_state(artifacts_dir, "expired")
        except Exception as exc:
            LOG.warning("could not mark hijacked done.json expired: %s", exc)
    from sase.running_field import release_workspace

    released = release_workspace(
        project_file,
        claim.workspace_num,
        claim.workflow,
        claim.cl_name,
        caller_tag="stale-cleanup",
        expected_pid=claim.pid,
        artifacts_timestamp=claim.artifacts_timestamp,
    )
    if not released.success:
        LOG.warning(
            "hijack %s expired but claim release failed: %s",
            expired.get("hijack_id"),
            released.error,
        )
        return False
    return True


def _ensure_expiry_snapshots(
    record: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Verify (or refresh) recovery snapshots before an expiry release."""
    from sase.workspace_provider._snapshot_capture_source import (
        snapshot_git_repo,
        snapshot_source_fingerprint,
    )

    workspace_dir = record.get("workspace_dir")
    workspace_num = record.get("workspace_num")
    existing = [
        dict(entry)
        for entry in record.get("snapshots") or []
        if isinstance(entry, dict)
    ]
    roots = _snapshot_roots(record)
    if not roots:
        return existing, None
    if workspace_dir is None or workspace_num is None:
        if existing:
            return existing, None
        return [], "workspace dir missing; cannot snapshot before expiry"
    updated: list[dict[str, Any]] = []
    errors: list[str] = []
    by_repo = {
        str(entry.get("repo") or ""): entry for entry in existing if entry.get("repo")
    }
    for root in roots:
        recorded = by_repo.get(root)
        try:
            current = snapshot_source_fingerprint(root)
        except Exception as exc:
            errors.append(f"{root}: {exc}")
            continue
        token = _fingerprint_token(current)
        if recorded is not None and str(recorded.get("fingerprint") or "") == token:
            updated.append(recorded)
            continue
        try:
            snap = snapshot_git_repo(
                root,
                workspace_dir=str(workspace_dir),
                workspace_num=int(workspace_num),
                label=f"hijack-expire-{record.get('agent_name') or 'agent'}",
                reason="hijack hold expiry",
            )
        except Exception as exc:
            errors.append(f"{root}: {exc}")
            continue
        if snap is None:
            if recorded is not None:
                updated.append(recorded)
            continue
        updated.append(
            {
                "repo": root,
                "reference": str(
                    getattr(snap, "snapshot_id", "") or getattr(snap, "head", "")
                ),
                "fingerprint": token or str(getattr(snap, "worktree_tree", "")),
            }
        )
    if errors:
        return existing, "; ".join(errors)
    return updated, None


def _set_done_recovery_state(artifacts_dir: str, state: str) -> None:
    """Rewrite ``done.json`` ``recovery.state`` without touching the outcome."""
    path = Path(artifacts_dir) / "done.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    recovery = payload.get("recovery")
    if not isinstance(recovery, dict):
        recovery = {"kind": "hijack"}
    recovery = dict(recovery)
    recovery["state"] = state
    payload["recovery"] = recovery
    atomic_write_json(path, payload)


def record_for_agent(
    *,
    artifacts_dir: str | None = None,
    agent_name: str | None = None,
    hijack_id: str | None = None,
) -> dict[str, Any] | None:
    """Load the active or settled hijack record for listing/show."""
    if artifacts_dir:
        record = load_record_by_artifacts_dir(artifacts_dir)
        if record is not None:
            return record
    if agent_name:
        record = load_record_by_agent_name(agent_name)
        if record is not None:
            return record
    if hijack_id:
        return load_record(hijack_id)
    return None


def recovery_is_user_parked(recovery: Any) -> bool:
    """Return whether a hijack recovery still parks waiters and bead owners."""
    if recovery is None:
        return True
    state = None
    if isinstance(recovery, dict):
        state = recovery.get("state")
    else:
        state = getattr(recovery, "state", None)
    if state is None or state == "":
        return True
    return str(state) in USER_PARKED_RECOVERY_STATES


def format_diff_summary(record: dict[str, Any]) -> str:
    """Return a compact ``N files +X −Y`` summary from ledger evidence."""
    diffs = record.get("repo_diffs")
    if not isinstance(diffs, list) or not diffs:
        return ""
    files = 0
    insertions = 0
    deletions = 0
    for entry in diffs:
        if not isinstance(entry, dict):
            continue
        try:
            files += int(entry.get("files_changed") or 0)
            insertions += int(entry.get("insertions") or 0)
            deletions += int(entry.get("deletions") or 0)
        except (TypeError, ValueError):
            continue
    if files == 0:
        return ""
    return f"{files} files +{insertions} \u2212{deletions}"


def _fingerprint_token(fingerprint: dict[str, str]) -> str:
    return json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))


def _snapshot_roots(record: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    workspace_dir = record.get("workspace_dir")
    if isinstance(workspace_dir, str) and workspace_dir:
        roots.append(workspace_dir)
    for entry in record.get("snapshots") or []:
        if not isinstance(entry, dict):
            continue
        repo = entry.get("repo")
        if isinstance(repo, str) and repo and repo not in roots:
            roots.append(repo)
    return roots


#: Ledger states whose workspace is still held from the CLI's view: the row
#: is dead but the claim, node, and evidence stay until a release resolution.
RELEASE_HELD_RECORD_STATES = frozenset({"held", "resolving", "expired"})


def held_record_for_agent(agent_name: str) -> dict[str, Any] | None:
    """Return the workspace-held hijack record for *agent_name*, if any.

    ``sase agent restart`` and ``sase agent kill`` consult this before their
    normal paths: a hijacked target routes through the release recovery
    resolutions instead of the live-agent flows.
    """
    try:
        record = record_for_agent(agent_name=agent_name)
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    if str(record.get("state") or "") in RELEASE_HELD_RECORD_STATES:
        return record
    return None


def _merge_record_fields(hijack_id: str, fields: dict[str, Any]) -> None:
    from sase.agent.hijack import ledger

    path = ledger.hijack_record_path(hijack_id)
    with file_lock(ledger.hijack_record_lock_path(hijack_id), timeout=10.0):
        current = ledger.read_hijack_record_payload(path)
        if current is None:
            raise RuntimeError(f"hijack record {hijack_id} disappeared")
        current.update(fields)
        atomic_write_json(path, current)


__all__ = [
    "ACTIVE_CUSTODY_STATES",
    "HIJACK_EVENT_EXPIRE",
    "RELEASE_HELD_RECORD_STATES",
    "USER_PARKED_RECOVERY_STATES",
    "expire_hijack_hold",
    "format_diff_summary",
    "held_record_for_agent",
    "hijack_retains_claim",
    "hijack_skips_claim_release",
    "hijacked_at_exceeds_ttl",
    "matching_active_record",
    "record_for_agent",
    "recovery_is_user_parked",
    "resolving_record_for_workspace",
]

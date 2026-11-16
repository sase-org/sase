"""Pre- and post-spawn hijack latch admission.

Ordinary successor launches carry the predecessor's target key and artifact
directory. PID or workspace number alone is not enough to identify the
latched turn. An authorized keep-work recovery successor is admitted even
when the matching latch has already applied, so Continue cannot deadlock.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import ledger
from ._stop_models import read_json_dict
from .locks import acquire_hijack_lock, record_lock_hold

_ACTIVE_LATCH_STATES = frozenset({"latched", "stopping", "held"})
_APPLIED_LATCH_STATES = frozenset({"stopping", "held"})


class HijackLatchedError(Exception):
    """A successor launch was refused because a hijack latch owns the predecessor.

    This is not a :class:`~sase.running_field.WorkspaceClaimError` and is not
    a :class:`RuntimeError`. Follow-up fallback chains must re-raise it
    instead of claiming a pool workspace or workspace ``#0``.
    """

    def __init__(
        self,
        message: str,
        *,
        hijack_id: str | None = None,
        target_key: str | None = None,
        verdict: str | None = None,
    ) -> None:
        super().__init__(message)
        self.hijack_id = hijack_id
        self.target_key = target_key
        self.verdict = verdict


@dataclass(frozen=True, slots=True)
class SpawnLatchGuard:
    """Predecessor identity a spawn funnel uses to observe a hijack latch."""

    target_key: str
    artifacts_dir: str
    member: str | None = None
    owner_pid: int | None = None
    owner_identity: str | None = None
    authorized_recovery_hijack_id: str | None = None


def _recovery_hijack_id(extra_env: Mapping[str, str] | None) -> str | None:
    if not extra_env:
        return None
    from sase.agent.hijack._recovery_successor_common import (
        RECOVERY_LINEAGE_ENV,
        RecoveryInheritanceError,
        decode_recovery_lineage,
    )

    raw = extra_env.get(RECOVERY_LINEAGE_ENV)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return decode_recovery_lineage(raw).hijack_id
    except RecoveryInheritanceError:
        return None


def latch_guard_from_predecessor(
    *,
    project_file: str | None = None,
    session_or_agent: str | None = None,
    artifacts_dir: str | None = None,
    member: str | None = None,
    owner_pid: int | None = None,
    owner_identity: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    authorized_recovery_hijack_id: str | None = None,
    is_home: bool = False,
) -> SpawnLatchGuard | None:
    """Build a spawn guard from explicit predecessor target and artifact identity."""
    artifacts = (artifacts_dir or "").strip()
    if not artifacts:
        return None
    meta = read_json_dict(Path(artifacts) / "agent_meta.json") or {}
    member_name = member
    if not member_name:
        raw_name = meta.get("name")
        member_name = raw_name.strip() if isinstance(raw_name, str) else None
    session = session_or_agent
    if not session:
        raw_session = meta.get("agent_session")
        session = (
            raw_session.strip()
            if isinstance(raw_session, str) and raw_session.strip()
            else member_name
        )
    if not session:
        return None
    pid = owner_pid
    if pid is None:
        raw_pid = meta.get("pid")
        if type(raw_pid) is int and not isinstance(raw_pid, bool) and raw_pid > 0:
            pid = raw_pid
    identity = owner_identity
    if not identity:
        raw_identity = meta.get("process_identity")
        if isinstance(raw_identity, str) and raw_identity.strip():
            identity = raw_identity.strip()
    recovery_id = authorized_recovery_hijack_id or _recovery_hijack_id(extra_env)
    project = project_file
    if not project:
        raw_project = meta.get("project_file")
        if isinstance(raw_project, str) and raw_project.strip():
            project = raw_project.strip()
    home = is_home or bool(meta.get("is_home_mode") or meta.get("is_home"))
    return SpawnLatchGuard(
        target_key=ledger.target_key_for(None if home else project, session),
        artifacts_dir=artifacts,
        member=member_name,
        owner_pid=pid,
        owner_identity=identity,
        authorized_recovery_hijack_id=recovery_id,
    )


def bind_recovery_identity(
    guard: SpawnLatchGuard | None,
    extra_env: Mapping[str, str] | None,
) -> SpawnLatchGuard | None:
    """Attach an authorized recovery hijack id from *extra_env* when missing."""
    if guard is None:
        return None
    if guard.authorized_recovery_hijack_id:
        return guard
    recovery_id = _recovery_hijack_id(extra_env)
    if not recovery_id:
        return guard
    return replace(guard, authorized_recovery_hijack_id=recovery_id)


def _same_predecessor(record: dict[str, Any], guard: SpawnLatchGuard) -> bool:
    recorded_artifacts = str(record.get("artifacts_dir") or "")
    if recorded_artifacts != guard.artifacts_dir:
        return False
    if guard.member:
        recorded_member = str(record.get("agent_name") or "")
        if recorded_member and recorded_member != guard.member:
            return False
    return True


def _authorized_recovery(record: dict[str, Any], guard: SpawnLatchGuard) -> bool:
    hijack_id = str(record.get("hijack_id") or "")
    if not guard.authorized_recovery_hijack_id or not hijack_id:
        return False
    if guard.authorized_recovery_hijack_id != hijack_id:
        return False
    state = str(record.get("state") or "")
    return state in _APPLIED_LATCH_STATES and record.get("latched_at") is not None


def refuse_if_latched(guard: SpawnLatchGuard, *, boundary: str) -> None:
    """Raise :class:`HijackLatchedError` when an active latch owns this predecessor."""
    del boundary  # observation boundary is recorded by callers; identity is the key.
    record = ledger.find_active_record_by_target_key(guard.target_key)
    if record is None:
        return
    if not _same_predecessor(record, guard):
        return
    state = str(record.get("state") or "")
    if state not in _ACTIVE_LATCH_STATES:
        return
    if state in _APPLIED_LATCH_STATES and record.get("latched_at") is None:
        return
    if _authorized_recovery(record, guard):
        return
    hijack_id = str(record.get("hijack_id") or "") or None
    verdict = "pending" if state == "latched" else "applied"
    raise HijackLatchedError(
        f"hijack latch {hijack_id or 'unknown'} is {verdict}; successor launch refused",
        hijack_id=hijack_id,
        target_key=guard.target_key,
        verdict=verdict,
    )


@contextmanager
def spawn_admission(guard: SpawnLatchGuard, *, boundary: str) -> Iterator[None]:
    """Hold the target-index lock, re-check the latch, then yield for the claim.

    The caller must take ``patch_lock`` (directly or through claim/transfer
    helpers) only after this context has entered, so target/ledger stays
    outside the claim lock.
    """
    with acquire_hijack_lock(
        "target_index", ledger.target_index_lock_path(), timeout=10.0
    ):
        refuse_if_latched(guard, boundary=boundary)
        with record_lock_hold("patch_lock"):
            yield


__all__ = [
    "HijackLatchedError",
    "SpawnLatchGuard",
    "bind_recovery_identity",
    "latch_guard_from_predecessor",
    "refuse_if_latched",
    "spawn_admission",
]

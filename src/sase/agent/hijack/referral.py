"""Local tracking of remote Agent Hijack referrals copied from the TUI.

When the TUI copies ``sase agent hijack NAME`` for a fleet row, this store
remembers the request until the owner host reports HIJACKED or a terminal
status, or the TTL lapses. The mirror row reads the store from the artifact
loader worker.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.hijack.ledger import LEDGER_DIRNAME
from sase.agent.status_buckets import status_bucket_for_values
from sase.core.paths import sase_subdir
from sase.notification_gates.durability import atomic_write_json, file_lock

REFERRAL_FILENAME = "remote_referrals.json"
REFERRAL_LOCKNAME = "remote_referrals.lock"
REFERRAL_SCHEMA_VERSION = 1
REFERRAL_TTL_SECONDS = 2 * 60 * 60

_SETTLED_STATUSES = frozenset(
    {
        "HIJACKED",
        "DONE",
        "FAILED",
        "STOPPED",
        "KILLED",
        "CONTINUED",
        "ESCALATED",
        "DISMISSED",
        "EXPIRED",
    }
)
_SETTLED_BUCKETS = frozenset({"Done", "Failed"})


@dataclass(frozen=True)
class _RemoteHijackReferral:
    """One copied remote hijack request still waiting for an owner outcome."""

    alias: str
    agent: str
    requested_at: float
    ttl_seconds: float

    @property
    def key(self) -> str:
        return _referral_key(self.alias, self.agent)


def record_remote_hijack_referral(
    alias: str,
    agent: str,
    *,
    now: float | None = None,
    ttl_seconds: float = REFERRAL_TTL_SECONDS,
) -> _RemoteHijackReferral | None:
    """Record or refresh a local referral for a copied remote hijack command."""
    host = _clean(alias)
    name = _clean(agent)
    if not host or not name:
        return None
    stamp = float(time.time() if now is None else now)
    ttl = float(ttl_seconds) if ttl_seconds > 0 else REFERRAL_TTL_SECONDS
    referral = _RemoteHijackReferral(
        alias=host, agent=name, requested_at=stamp, ttl_seconds=ttl
    )
    with file_lock(_lock_path(), timeout=10.0):
        payload = _read_payload()
        referrals = _referrals_map(payload)
        referrals[referral.key] = {
            "alias": referral.alias,
            "agent": referral.agent,
            "requested_at": referral.requested_at,
            "ttl_seconds": referral.ttl_seconds,
        }
        _write_payload(referrals)
    return referral


def _list_active_remote_hijack_referrals(
    *,
    now: float | None = None,
) -> list[_RemoteHijackReferral]:
    """Return live referrals, pruning those whose TTL has lapsed."""
    if not _store_path().exists():
        return []
    stamp = float(time.time() if now is None else now)
    with file_lock(_lock_path(), timeout=10.0):
        payload = _read_payload()
        referrals = _referrals_map(payload)
        live, changed = _prune_expired(referrals, now=stamp)
        if changed:
            _write_payload(live)
    items: list[_RemoteHijackReferral] = []
    for record in live.values():
        item = _from_record(record)
        if item is not None:
            items.append(item)
    return items


def _clear_remote_hijack_referral(alias: str, agent: str) -> None:
    """Drop the referral for *alias*/*agent* if one exists."""
    key = _referral_key(alias, agent)
    if not key:
        return
    with file_lock(_lock_path(), timeout=10.0):
        payload = _read_payload()
        referrals = _referrals_map(payload)
        if key not in referrals:
            return
        referrals.pop(key, None)
        _write_payload(referrals)


def apply_remote_hijack_referrals(
    agents: Iterable[Any],
    *,
    now: float | None = None,
) -> None:
    """Project live referrals onto fleet mirror rows.

    Call from the artifact-loader worker. A row already showing a local
    hijack overlay is left alone. Settled fleet facts drop the referral.
    """
    stamp = float(time.time() if now is None else now)
    rows = list(agents)
    active = {
        (item.alias, item.agent): item
        for item in _list_active_remote_hijack_referrals(now=stamp)
    }
    if not active:
        return
    settled: list[tuple[str, str]] = []
    for agent in rows:
        alias = _clean(getattr(agent, "fleet_origin_alias", None))
        name = _clean(getattr(agent, "agent_name", None))
        if not alias or not name:
            continue
        referral = active.get((alias, name))
        if referral is None:
            continue
        if _row_has_outcome(agent):
            settled.append((alias, name))
            continue
        if getattr(agent, "hijack_overlay", None):
            continue
        agent.hijack_overlay = "referred"
    for alias, name in settled:
        _clear_remote_hijack_referral(alias, name)


def _row_has_outcome(agent: Any) -> bool:
    status = getattr(agent, "status", None)
    if isinstance(status, str) and status.strip().upper() in _SETTLED_STATUSES:
        return True
    try:
        bucket = status_bucket_for_values(status if isinstance(status, str) else None)
    except Exception:
        return False
    return bucket in _SETTLED_BUCKETS


def _referral_key(alias: str | None, agent: str | None) -> str:
    host = _clean(alias)
    name = _clean(agent)
    if not host or not name:
        return ""
    return f"{host}::{name}"


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _from_record(record: Mapping[str, Any] | None) -> _RemoteHijackReferral | None:
    if not isinstance(record, Mapping):
        return None
    alias = _clean(record.get("alias"))
    agent = _clean(record.get("agent"))
    if not alias or not agent:
        return None
    raw_at = record.get("requested_at")
    if raw_at is None:
        return None
    try:
        requested_at = float(raw_at)
        ttl_seconds = float(record.get("ttl_seconds") or REFERRAL_TTL_SECONDS)
    except (TypeError, ValueError):
        return None
    return _RemoteHijackReferral(
        alias=alias,
        agent=agent,
        requested_at=requested_at,
        ttl_seconds=ttl_seconds,
    )


def _prune_expired(
    referrals: dict[str, Any], *, now: float
) -> tuple[dict[str, Any], bool]:
    live: dict[str, Any] = {}
    changed = False
    for key, raw in referrals.items():
        item = _from_record(raw if isinstance(raw, Mapping) else None)
        if item is None:
            changed = True
            continue
        if now - item.requested_at >= item.ttl_seconds:
            changed = True
            continue
        live[key] = {
            "alias": item.alias,
            "agent": item.agent,
            "requested_at": item.requested_at,
            "ttl_seconds": item.ttl_seconds,
        }
    if len(live) != len(referrals):
        changed = True
    return live, changed


def _referrals_map(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("referrals")
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): dict(value)
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _read_payload() -> dict[str, Any]:
    path = _store_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": REFERRAL_SCHEMA_VERSION, "referrals": {}}
    except (OSError, json.JSONDecodeError):
        return {"schema_version": REFERRAL_SCHEMA_VERSION, "referrals": {}}
    return raw if isinstance(raw, dict) else {}


def _write_payload(referrals: Mapping[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "schema_version": REFERRAL_SCHEMA_VERSION,
            "referrals": dict(referrals),
        },
    )


def _store_path() -> Path:
    return sase_subdir(LEDGER_DIRNAME) / REFERRAL_FILENAME


def _lock_path() -> Path:
    return sase_subdir(LEDGER_DIRNAME) / REFERRAL_LOCKNAME


__all__ = [
    "REFERRAL_TTL_SECONDS",
    "apply_remote_hijack_referrals",
    "record_remote_hijack_referral",
]

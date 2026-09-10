"""Follow-store helpers for dispatch-followed remote rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.dispatch.follow_store import (
    FollowStoreSnapshot,
    load_follow_snapshot,
    promote_family_follow,
)

from ...models.fleet_agents import followed_batch_family_promotions
from ._fleet_common import fleet_public_override


def load_reconciled_follow_snapshot() -> FollowStoreSnapshot:
    """Load the follow store without creating zero-machine state."""
    load_snapshot = fleet_public_override("load_follow_snapshot", load_follow_snapshot)
    return load_snapshot()


def followed_logical_keys(
    snapshot: FollowStoreSnapshot | None,
) -> tuple[str, ...]:
    """Return active logical keys for bounded attention hydration."""
    if snapshot is None:
        return ()
    keys: list[str] = []
    for record in snapshot.active_records:
        key = record.get("logical_key")
        if isinstance(key, str) and key:
            keys.append(key)
    return tuple(keys)


def reconcile_followed_batch_family_promotions(
    snapshot: FollowStoreSnapshot,
    followed_response: Mapping[str, Any] | None,
) -> FollowStoreSnapshot:
    """Persist safe singleton-to-family promotions discovered during hydration."""
    promotions = followed_batch_family_promotions(snapshot, followed_response)
    if not promotions:
        return snapshot
    promote = fleet_public_override("promote_family_follow", promote_family_follow)
    current = snapshot
    for promotion in promotions:
        source = promotion.get("from")
        target = promotion.get("to")
        if not isinstance(source, Mapping) or not isinstance(target, Mapping):
            continue
        current = promote(source, target).snapshot
    return current


__all__ = [
    "followed_logical_keys",
    "load_reconciled_follow_snapshot",
    "reconcile_followed_batch_family_promotions",
]

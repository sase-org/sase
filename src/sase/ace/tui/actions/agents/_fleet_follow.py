"""Follow-store actions and helpers for Agents fleet rows."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from sase.dispatch.follow_store import (
    FollowStoreError,
    FollowStoreMutationOutcome,
    FollowStoreSnapshot,
    load_follow_snapshot,
    reconcile_follow_store,
    record_follow,
    unfollow,
)

from ...models.fleet_agents import followed_batch_family_promotions
from ...util.pump_tasks import spawn_pump_free_task
from ._fleet_common import fleet_public_override


class AgentFleetFollowMixin:
    """Follow and unfollow remote fleet rows."""

    def action_toggle_agent_follow(self) -> None:
        """Follow or unfollow the selected remote fleet row."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        logical_locator = getattr(agent, "fleet_logical_locator", None)
        if agent is None or not isinstance(logical_locator, Mapping):
            self.notify("Select a remote fleet agent to follow")  # type: ignore[attr-defined]
            return
        followed = bool(getattr(agent, "fleet_followed", False))
        task = spawn_pump_free_task(
            self,
            self._toggle_agent_follow_async(
                dict(logical_locator),
                currently_followed=followed,
            ),
            name="sase-agents-fleet-follow",
            registry_attr="_agents_fleet_async_tasks",
        )
        if task is None:
            self.notify("Unable to update fleet follow state", severity="error")  # type: ignore[attr-defined]

    async def _toggle_agent_follow_async(
        self,
        logical_locator: dict[str, Any],
        *,
        currently_followed: bool,
    ) -> None:
        outcome: FollowStoreMutationOutcome
        follow = fleet_public_override("record_follow", record_follow)
        stop_following = fleet_public_override("unfollow", unfollow)
        try:
            if currently_followed:
                outcome = await asyncio.to_thread(stop_following, logical_locator)
                followed = False
            else:
                outcome = await asyncio.to_thread(follow, logical_locator)
                followed = True
        except FollowStoreError as exc:
            self.notify(f"Fleet follow update failed: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        self._set_cached_follow_state(logical_locator, followed)
        changed = "updated" if outcome.changed else "unchanged"
        self.notify(f"Fleet follow {changed}")  # type: ignore[attr-defined]
        self._reproject_agents_from_current_mode(source="fleet_follow")  # type: ignore[attr-defined]
        self._schedule_agents_fleet_refresh(source="fleet_follow", force=True)  # type: ignore[attr-defined]

    def _set_cached_follow_state(
        self,
        logical_locator: Mapping[str, Any],
        followed: bool,
    ) -> None:
        locator_id = self._fleet_locator_id(logical_locator)
        for row in [
            *getattr(self, "_agents_fleet_rows", []),
            *getattr(self, "_agents_fleet_focus_rows", []),
            *getattr(self, "_agents", []),
            *getattr(self, "_agents_with_children", []),
        ]:
            row_locator = getattr(row, "fleet_logical_locator", None)
            if isinstance(row_locator, Mapping) and (
                self._fleet_locator_id(row_locator) == locator_id
            ):
                row.fleet_followed = followed

    @staticmethod
    def _fleet_locator_id(locator: Mapping[str, Any]) -> str:
        import json

        try:
            return json.dumps(dict(locator), sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return repr(
                sorted((str(key), repr(value)) for key, value in locator.items())
            )


def load_reconciled_follow_snapshot() -> FollowStoreSnapshot:
    """Load the follow store, persisting reconciliation when state exists.

    A store with no records or tombstones is left untouched so the
    zero-machine, zero-follow path never writes under the sase home.
    """
    load_snapshot = fleet_public_override("load_follow_snapshot", load_follow_snapshot)
    reconcile = fleet_public_override("reconcile_follow_store", reconcile_follow_store)
    snapshot = load_snapshot()
    if not snapshot.records and not snapshot.tombstones:
        return snapshot
    return reconcile().snapshot


def reconcile_followed_batch_family_promotions(
    snapshot: FollowStoreSnapshot,
    followed_response: Mapping[str, Any] | None,
) -> FollowStoreSnapshot:
    """Persist safe family promotions discovered during followed hydration."""
    promotions = followed_batch_family_promotions(snapshot, followed_response)
    if not promotions:
        return snapshot
    reconcile = fleet_public_override("reconcile_follow_store", reconcile_follow_store)
    return reconcile(promotions=promotions).snapshot


__all__ = [
    "AgentFleetFollowMixin",
    "load_reconciled_follow_snapshot",
    "reconcile_followed_batch_family_promotions",
]

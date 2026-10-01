"""Session-sticky reconcile, prune, and bridge-expiry helpers.

Session-sticky tribe panels bridge unexplained disappearances for at most
``STICKY_PANEL_BRIDGE_S`` seconds. Positive evidence of where a row is
(placed under another key, in another tab, or under a re-keyed container)
retires the old key in the same sync; unexplained absence only bridges
briefly so transient zero-row publications never flicker.
"""

from __future__ import annotations

import time
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from ...util.trace import trace_event
from ._display_panel_state import PanelRefreshStateMixin
from ._tab_scope import scoped_sticky_key, sticky_key_in_scope, unstick_panel_key

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey

#: How long an unaccounted identity keeps an empty tribe panel mounted.
STICKY_PANEL_BRIDGE_S = 5.0

_sticky_now = time.monotonic


class SessionStickyReconcileMixin(PanelRefreshStateMixin):
    """Reconcile the session-sticky store against rendered rosters."""

    def _remember_session_mounted_occupancy(self) -> set[PanelKey]:
        """Reconcile the session-sticky store against the rendered roster.

        Records every rendered row under its current key, moves identities
        rendered under a new key out of their old keys, then reconciles keys
        with no rendered rows: an identity placed under another key or
        outside the active scope retires immediately, as does a synthetic
        container whose backing members are all placed elsewhere or
        dismissed. Any other unaccounted identity (absent from the roster, or
        present and placed here but not rendered) only bridges for
        ``STICKY_PANEL_BRIDGE_S`` seconds before it stops pinning the key, so
        transient zero-row publications never flicker but never linger.
        Returns the keys the reconcile retired.
        """
        from ...models.agent_panels import (
            agent_is_rendered_in_agents_panel,
            normalize_panel_key,
            panel_key_per_agent,
        )

        mounted = self._session_mounted_identity_map()
        backing = self._session_mounted_backing_map()
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        keys = panel_key_per_agent(self._agents, merge_tribe_panels=merge_tribe_panels)
        # The backing map stays keyed by container identity (scope-neutral):
        # identities are global, and scoped mounted keys already gate which
        # backing entries each tab's prune can retire.
        rendered_now: dict[tuple[AgentType, str, str | None], Any] = {}
        for agent, key in zip(self._agents, keys, strict=True):
            if agent_is_rendered_in_agents_panel(agent):
                norm = normalize_panel_key(key)
                scoped = scoped_sticky_key(self, norm)
                rendered_now[agent.identity] = scoped
                mounted.setdefault(scoped, set()).add(agent.identity)
        # A row rendered under a new key proves it left the old panel.
        for identity, key in rendered_now.items():
            for other in list(mounted):
                if other != key:
                    mounted[other].discard(identity)
        self._record_session_mounted_backing(backing, set(rendered_now))
        unaccounted = self._session_sticky_unaccounted_since_map()
        for identity in rendered_now:
            unaccounted.pop(identity, None)
        dismissed = set(getattr(self, "_dismissed_agents", ()))
        skip_keys = set(rendered_now.values())
        empty_keys = [
            key
            for key in mounted
            if key not in skip_keys and sticky_key_in_scope(self, key)
        ]
        extra_reasons: dict[tuple[AgentType, str, str | None], str] = {}
        if empty_keys:
            placement = self._sticky_placement_map()
            now = _sticky_now()
            for key in empty_keys:
                bare = unstick_panel_key(key)
                for identity in list(mounted.get(key, ())):
                    if identity in dismissed:
                        continue
                    placed = placement.get(identity)
                    if placed is not None and (placed[0] != bare or not placed[1]):
                        extra_reasons[identity] = "placed_elsewhere"
                        unaccounted.pop(identity, None)
                        continue
                    members = backing.get(identity)
                    if placed is None and members:
                        accounted = True
                        for member in members:
                            if member in dismissed:
                                continue
                            member_placed = placement.get(member)
                            if member_placed is None:
                                accounted = False
                                break
                            member_key, member_in_scope = member_placed
                            if member_key == bare and member_in_scope:
                                accounted = False
                                break
                        if accounted:
                            extra_reasons[identity] = "container_members_accounted"
                            unaccounted.pop(identity, None)
                            continue
                    if identity in extra_reasons:
                        continue
                    since = unaccounted.get(identity)
                    if since is None:
                        unaccounted[identity] = now
                    elif now - since >= STICKY_PANEL_BRIDGE_S:
                        extra_reasons[identity] = "bridge_expired"
                        unaccounted.pop(identity, None)
        gone = dismissed | set(extra_reasons)
        # Keys with rendered rows keep their mount regardless of the store.
        retired = self._prune_session_mounted_gone(
            gone,
            skip_keys=skip_keys,
            reasons=extra_reasons,
            default_reason="dismissed",
        )
        if mounted:
            recorded = set()
            for remaining in mounted.values():
                recorded.update(remaining)
            for identity in list(unaccounted):
                if identity not in recorded:
                    unaccounted.pop(identity, None)
        else:
            unaccounted.clear()
        return retired

    def _record_session_mounted_backing(
        self,
        backing: dict[
            tuple[AgentType, str, str | None], set[tuple[AgentType, str, str | None]]
        ],
        rendered: set[tuple[AgentType, str, str | None]],
    ) -> None:
        """Union loaded clan members under their rendered containers.

        Builds the member index in one pass over the loaded roster, grouped
        by parent fold key and clan name, so a sync never scans the roster
        once per container. Only rendered containers gain backing: an
        expanded clan's members keep their own key alive directly.
        """
        from ...models._agent_tree import agent_fold_key

        roster = getattr(self, "_agents_with_children", None)
        if roster is None:
            roster = self._agents
        by_parent: dict[str, set[tuple[AgentType, str, str | None]]] = {}
        by_clan: dict[
            str, set[tuple[tuple[AgentType, str, str | None], str | None]]
        ] = {}
        containers: list[Agent] = []
        for agent in roster:
            if agent.is_clan_container:
                if agent.agent_clan and agent.identity in rendered:
                    containers.append(agent)
                continue
            if agent.tree_parent_key:
                by_parent.setdefault(agent.tree_parent_key, set()).add(agent.identity)
            if agent.agent_clan:
                by_clan.setdefault(agent.agent_clan, set()).add(
                    (agent.identity, agent.agent_clan_generation)
                )
        for container in containers:
            members: set[tuple[AgentType, str, str | None]] = set()
            fold_key = agent_fold_key(container)
            if fold_key is not None:
                members.update(by_parent.get(fold_key, ()))
            clan = container.agent_clan
            generation = container.agent_clan_generation
            if clan is not None:
                for identity, candidate_generation in by_clan.get(clan, ()):
                    if (
                        generation is None
                        or candidate_generation is None
                        or candidate_generation == generation
                    ):
                        members.add(identity)
            if members:
                backing.setdefault(container.identity, set()).update(members)

    def _prune_session_mounted_gone(
        self,
        gone: set[tuple[AgentType, str, str | None]],
        *,
        skip_keys: set[PanelKey] | None = None,
        reasons: dict[tuple[AgentType, str, str | None], str] | None = None,
        default_reason: str = "dismissed",
    ) -> set[PanelKey]:
        """Drop *gone* identities and fully-gone-backed containers.

        A recorded clan container retires with its key once every backing
        member is in *gone*, even though the container itself is never
        dismissed. Keys in *skip_keys* keep their mount regardless of the
        store. Each retired key emits one ``agents.sticky_panel_retired``
        trace event naming the reason. Returns the keys left empty.
        """
        mounted = self._session_mounted_identity_map()
        backing = self._session_mounted_backing_map()
        skipped = skip_keys or set()
        reason_for = reasons or {}
        priority = {
            "placed_elsewhere": 0,
            "container_members_accounted": 1,
            "bridge_expired": 2,
        }
        retired: set[PanelKey] = set()
        for key in list(mounted):
            if key in skipped or not sticky_key_in_scope(self, key):
                continue
            remaining = mounted[key]
            before = set(remaining)
            discarded_reasons: list[str] = []
            for identity in list(before):
                if identity in gone:
                    discarded_reasons.append(reason_for.get(identity, default_reason))
            remaining.difference_update(gone)
            for identity in list(remaining):
                members = backing.get(identity)
                if members and members <= gone:
                    remaining.discard(identity)
                    discarded_reasons.append(default_reason)
            for identity in before - set(remaining):
                backing.pop(identity, None)
            if not remaining:
                del mounted[key]
                bare = unstick_panel_key(key)
                retired.add(bare)
                reason = default_reason
                best = None
                for candidate in discarded_reasons:
                    rank = priority.get(candidate, 3)
                    if best is None or rank < best[0]:
                        best = (rank, candidate)
                if best is not None:
                    reason = best[1]
                trace_event(
                    "agents.sticky_panel_retired",
                    panel="" if bare is None else str(bare),
                    reason=reason,
                )
        unaccounted = getattr(self, "_session_sticky_unaccounted_since", None)
        if unaccounted:
            for identity in gone:
                unaccounted.pop(identity, None)
        return retired

    def _reconcile_session_mounted_for_apply(self, load_state: object) -> set[PanelKey]:
        """Prune the sticky store against one authoritative complete roster.

        Only a ``complete_history`` apply under the currently committed
        query carries removal authority: bounded, delta, revalidate, and
        other incomplete applies — including bounded ``has_more=False``
        zeros — never prune, and neither does a complete roster published
        for a query the user has already left. Rows from the fleet
        projection stay in the mixed roster, so a local complete apply
        never prunes them. Returns the keys that were retired.
        """
        if not getattr(load_state, "complete_history", False):
            return set()
        from ._loading_apply_history import history_query_key_for_load
        from ...models.agent_live_query_engine import agents_history_query_key

        if history_query_key_for_load(
            self,
            load_state,  # type: ignore[arg-type]
        ) != agents_history_query_key(self._session_sticky_query_value()):
            return set()
        roster = getattr(self, "_agents_with_children", None)
        if roster is None:
            roster = self._agents
        present = {agent.identity for agent in roster}
        mounted = self._session_mounted_identity_map()
        backing = self._session_mounted_backing_map()
        gone = {
            identity
            for remaining in mounted.values()
            for identity in remaining
            if identity not in present
        }
        gone.update(
            identity
            for members in backing.values()
            for identity in members
            if identity not in present
        )
        gone.update(getattr(self, "_dismissed_agents", ()))
        retired = self._prune_session_mounted_gone(
            gone, default_reason="complete_history"
        )
        if retired:
            self._session_sticky_pending_retired_set().update(retired)
        return retired

    def _retire_session_mounted_identities(
        self, identities: Collection[tuple[AgentType, str, str | None]]
    ) -> set[PanelKey]:
        """Drop explicitly removed identities and retire keys left with none.

        Only user-driven removals (dismiss, kill, named-proc dismiss) call this.
        Merely being absent from the roster only bridges briefly: placed
        elsewhere retires at the next sync and unexplained absence expires
        after ``STICKY_PANEL_BRIDGE_S`` seconds.
        Clan containers retire through their backing: removing a clan's last
        members retires the container identity in the same call. Returns the
        keys that were retired.
        """
        removed = set(identities)
        if removed:
            mounted = self._session_mounted_identity_map()
            # Seed backing for containers the store already tracks so an
            # explicit member removal retires them without waiting for a sync.
            self._record_session_mounted_backing(
                self._session_mounted_backing_map(),
                {identity for remaining in mounted.values() for identity in remaining},
            )
        return self._prune_session_mounted_gone(
            removed, default_reason="explicit_removal"
        )

    def _maybe_expire_sticky_panel_bridges(
        self, *, now_mono: float | None = None
    ) -> None:
        """Expire sticky-panel bridges on a quiet host.

        Returns immediately when no unaccounted timestamps are pending or
        none has reached ``STICKY_PANEL_BRIDGE_S``. Otherwise requests the
        established incremental refresh so the next sync retires the key
        and unmounts its widget. No new timer or refresh path.
        """
        unaccounted = getattr(self, "_session_sticky_unaccounted_since", None)
        if not unaccounted:
            return
        now = now_mono if now_mono is not None else _sticky_now()
        expired = False
        for since in list(unaccounted.values()):
            if now - since >= STICKY_PANEL_BRIDGE_S:
                expired = True
                break
        if not expired:
            return
        refresh = getattr(self, "_refresh_agents_display_after_finalize", None)
        if not callable(refresh):
            return
        refresh(previous_agents=list(self._agents), defer_detail=True)

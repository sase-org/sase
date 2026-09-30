"""Unified Agents row projection."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Host-level per-refresh fields that never join the structural signature.
# They are display-soft (observed time, cache age, host counts,
# freshness/health, feed diagnostics) and change between polls without any
# content change, so an unchanged refresh patches them onto the live rows
# (header/banner repaint through the render cache) instead of reprojecting.
# Audit (epic sase-1d7, phase fleet-signature-cheap): rows render
# fleet_freshness / fleet_connection_health / feed-error fields in the row
# summary line, fleet_observed_at_unix only in the gone-row "last seen"
# label (deliberately stable between polls), host counts and cache age in
# group-banner keys, and fleet_diagnostic in the detail header. All of them
# stay fresh through the skip-path patch below; the header problem text
# additionally reads the new projection's diagnostics and feed issues.
_FLEET_VOLATILE_ROW_FIELDS = (
    "fleet_freshness",
    "fleet_connection_health",
    "fleet_observed_at_unix",
    "fleet_host_status",
    "fleet_host_feed_error",
    "fleet_host_cache_age_seconds",
    "fleet_host_running_count",
    "fleet_host_total_count",
    "fleet_host_waiting_count",
    "fleet_host_failed_count",
    "fleet_host_done_count",
    "fleet_host_unknown_count",
    "fleet_diagnostic",
)


def _freeze_signature_value(value: Any) -> Any:
    """Freeze a small signature value into a comparable structural form."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (
                    (str(key), _freeze_signature_value(item))
                    for key, item in value.items()
                ),
                key=repr,
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_signature_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(
            sorted((_freeze_signature_value(item) for item in value), key=repr)
        )
    return value


def _fleet_row_signature(agent: Agent) -> tuple[Any, ...]:
    """Return the structural signature of one fleet input row.

    Only hard structural facts join: identity and wire keys (membership and
    order), rendered status, the owner-stamped ``fleet_revision`` /
    ``fleet_row_revision``, local follow state, pending attention, clan and
    tab placement, and dispatch-provisional status. Everything host-soft
    (freshness, observed time, cache age, counts, health, diagnostics) is
    patched onto live rows on the skip path instead.
    """
    return (
        _freeze_signature_value(agent.identity),
        getattr(agent, "fleet_logical_key", None),
        getattr(agent, "fleet_exact_key", None),
        getattr(agent, "status", None),
        getattr(agent, "status_bucket", None),
        getattr(agent, "fleet_revision", None),
        _freeze_signature_value(getattr(agent, "fleet_row_revision", None)),
        bool(getattr(agent, "fleet_followed", False)),
        _freeze_signature_value(getattr(agent, "fleet_attention", None)),
        getattr(agent, "agent_clan", None),
        getattr(agent, "agent_clan_generation", None),
        getattr(agent, "clan_tribe", None),
        getattr(agent, "tribe", None),
        getattr(agent, "agent_tab", None),
        getattr(agent, "fleet_dispatch_status", None),
    )


def _fleet_refresh_signature(
    app: Any,
    fleet_rows: list[Agent],
    snapshot_identities: tuple[tuple[str, str], ...],
) -> tuple[Any, ...]:
    """Return the cheap pre-projection signature for a fleet refresh."""
    from ._roster_generation import get_roster_generation

    return (
        get_roster_generation(app),
        int(getattr(app, "_agents_removal_generation", 0) or 0),
        tuple(_fleet_row_signature(agent) for agent in fleet_rows),
        tuple(snapshot_identities),
    )


def _patch_fleet_volatile_row_fields(
    live_agents: list[Agent],
    fresh_by_identity: dict[Any, Agent],
) -> int:
    """Patch host-soft fields from fresh rows onto live rows by identity.

    Returns the number of fields updated. Clan containers are synthetic and
    local rows never match the fleet map, so only live fleet rows change,
    and only in scalar display fields: tree links are untouched.
    """
    patched = 0
    for live in live_agents:
        if getattr(live, "is_clan_container", False):
            continue
        try:
            identity = live.identity
        except Exception:
            continue
        fresh = fresh_by_identity.get(identity)
        if fresh is None:
            continue
        for field_name in _FLEET_VOLATILE_ROW_FIELDS:
            try:
                new_value = getattr(fresh, field_name)
            except Exception:
                continue
            try:
                if getattr(live, field_name) != new_value:
                    setattr(live, field_name, new_value)
                    patched += 1
            except Exception:
                continue
    return patched


class AgentFleetProjectionMixin:
    """Unified Agents row reprojection."""

    if TYPE_CHECKING:
        current_tab: str
        current_idx: int
        _agents: list[Agent]
        _agents_with_children: list[Agent]
        _agents_local_with_children: list[Agent]
        _agents_local_visible: list[Agent]
        _agents_fleet_rows: list[Agent]
        _agents_fleet_focus_rows: list[Agent]
        _agents_fleet_applied_projection_signature: object | None
        _agents_refresh_active_source: str

    def action_connect_agent_machine(self) -> None:
        """Open the persistent Machines administration pane."""
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")

    def action_setup_agent_machine(self) -> None:
        """Open enrollment guidance while no remote machine is configured."""
        fleet_mode_available = getattr(self, "_fleet_mode_available", None)
        if callable(fleet_mode_available) and fleet_mode_available():
            self.notify(  # type: ignore[attr-defined]
                "Remote machines are already enrolled; run 'sase machine init' "
                "to rescan, or 'sase machine list' / 'sase machine status' "
                "from a turn for details"
            )
            return
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")
            return
        visible_after_enrollment = (
            "The Agents list includes it once a machine is enrolled."
        )
        self.notify(  # type: ignore[attr-defined]
            "No remote machines are enrolled. On the target, run "
            "'sase machine bootstrap --json' into a protected file. On this "
            "controller, run 'sase machine init -B <file>' to discover, enroll, "
            f"and verify. {visible_after_enrollment}",
            timeout=12,
        )

    def _sync_agents_local_source_from_current(self) -> None:
        """Mirror local-only rows after existing in-memory mutations."""
        self._agents_local_with_children = self._local_agents_from_mixed(
            getattr(self, "_agents_with_children", [])
        )
        self._agents_local_visible = self._local_agents_from_mixed(
            getattr(self, "_agents", [])
        )

    def _agents_source_for_current_mode(self, local_agents: list[Agent]) -> list[Agent]:
        from ...models._agent_tree import project_mixed_agent_tree

        fleet_rows = self._fleet_rows_with_dispatch_provisionals(  # type: ignore[attr-defined]
            list(getattr(self, "_agents_fleet_rows", []))
        )
        return project_mixed_agent_tree(local_agents, fleet_rows)

    @staticmethod
    def _local_agents_from_mixed(agents: list[Agent]) -> list[Agent]:
        return [
            agent for agent in agents if not getattr(agent, "fleet_origin_alias", None)
        ]

    def _local_base_for_current_projection(self) -> list[Agent]:
        local_cache = getattr(self, "_agents_local_with_children", None)
        if local_cache is not None:
            return list(local_cache)
        return self._local_agents_from_mixed(
            list(getattr(self, "_agents_with_children", []))
        )

    def _fleet_refresh_incoming_signature(
        self,
    ) -> tuple[tuple[Any, ...], list[Agent]] | None:
        """Return the incoming refresh signature and merged fleet rows.

        Returns ``None`` when the inputs cannot be read, which fails open to
        a full reprojection. The merge drops settled dispatch provisionals as
        a side effect; re-running it on the miss path is idempotent.
        """
        try:
            fleet_rows = self._fleet_rows_with_dispatch_provisionals(  # type: ignore[attr-defined]
                list(getattr(self, "_agents_fleet_rows", []))
            )
            projection = getattr(self, "_agents_fleet_projection", None)
            snapshot_identities = tuple(
                getattr(projection, "snapshot_identities", None) or ()
            )
            return (
                _fleet_refresh_signature(self, list(fleet_rows), snapshot_identities),
                list(fleet_rows),
            )
        except Exception:
            return None

    def _try_skip_unchanged_fleet_refresh(
        self,
        incoming: tuple[tuple[Any, ...], list[Agent]],
    ) -> bool:
        """Skip the projection when the incoming fleet state is unchanged.

        Host-soft fields are patched onto the live rows so the header and
        group banners repaint through the render cache without running
        ``project_clan_tree``.
        """
        signature, fleet_rows = incoming
        stored = getattr(self, "_agents_fleet_applied_projection_signature", None)
        if stored is None or signature != stored:
            return False
        fresh_by_identity: dict[Any, Agent] = {}
        for row in fleet_rows:
            try:
                fresh_by_identity.setdefault(row.identity, row)
            except Exception:
                continue
        _patch_fleet_volatile_row_fields(
            list(getattr(self, "_agents", [])),
            fresh_by_identity,
        )
        self._update_agents_header()  # type: ignore[attr-defined]
        return True

    def _reproject_agents_from_current_mode(
        self,
        *,
        source: str,
        force: bool = False,
        selected_identity: tuple[AgentType, str, str | None] | None = None,
    ) -> None:
        if selected_identity is None and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        previous_agents = list(getattr(self, "_agents", []))
        # Cheap pre-projection check: the stored signature always reflects the
        # inputs of the last completed reprojection (it starts as None, so the
        # first refresh for any content still runs the full pipeline, which
        # subsumes the old previous-agents/empty-projection guard).
        if source == "fleet_refresh" and not force and self.current_tab == "agents":
            incoming = self._fleet_refresh_incoming_signature()
            if incoming is not None and self._try_skip_unchanged_fleet_refresh(
                incoming
            ):
                return
        local_base = self._local_base_for_current_projection()
        filter_removed = getattr(self, "filter_explicitly_removed", None)
        if callable(filter_removed):
            local_base = filter_removed(local_base)
            # Keep the local cache authoritative for a later fleet refresh;
            # otherwise that reprojection can rebuild a removed row.
            self._agents_local_with_children = list(local_base)
        projected_agents = self._agents_source_for_current_mode(local_base)
        from ._roster_generation import set_agents_roster

        set_agents_roster(
            self,
            agents_with_children=projected_agents,
            agents=list(projected_agents),
        )
        self._agents_refresh_active_source = source  # type: ignore[attr-defined]
        try:
            self._finalize_agent_list(  # type: ignore[attr-defined]
                self.current_tab == "agents",
                selected_identity,
                save_unfiltered=False,
                previous_agents=previous_agents,
            )
        finally:
            self._agents_refresh_active_source = "unknown"  # type: ignore[attr-defined]
        incoming = self._fleet_refresh_incoming_signature()
        if incoming is not None:
            self._agents_fleet_applied_projection_signature = incoming[0]
        self._update_agents_header()  # type: ignore[attr-defined]

    def _fleet_mode_available(self) -> bool:
        return bool(
            getattr(self, "_agents_fleet_available", False)
            or getattr(self, "_agents_fleet_rows", ())
            or getattr(self, "_agents_fleet_focus_rows", ())
            or getattr(self, "_agents_dispatch_provisional_rows", {})
        )


__all__ = ["AgentFleetProjectionMixin"]

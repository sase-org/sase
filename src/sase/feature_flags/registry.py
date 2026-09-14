"""Code-owned SASE feature flag registry.

Definition authors must follow two rules:

- ``remove_by`` never appears here; it lives on the flag bead.
- Definitions are added only through ``sase flag new``, never by hand.

``default`` is derived from ``kind`` (``FeatureFlagDefinition.default``) and is never
passed explicitly: a ``beta`` flag defaults off, a ``sunset`` flag defaults on.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from sase.feature_flags.models import FeatureFlagDefinition, FeatureFlagError


class FeatureFlag(StrEnum):
    """Every SASE feature flag key. Add members through ``sase flag new``."""

    ace_refresh_tokens = "ace_refresh_tokens"
    admin_center_flags = "admin_center_flags"
    agents_unified_query = "agents_unified_query"
    agent_sudo_requests = "agent_sudo_requests"
    monitor_continuation_records = "monitor_continuation_records"
    provider_drain = "provider_drain"
    queue_capacity_budget = "queue_capacity_budget"
    ref_sync_gesture = "ref_sync_gesture"
    refresh_panel = "refresh_panel"
    typed_launch_units = "typed_launch_units"


_FEATURE_FLAG_DEFINITIONS: dict[FeatureFlag, FeatureFlagDefinition] = {
    FeatureFlag.ace_refresh_tokens: FeatureFlagDefinition(
        key=FeatureFlag.ace_refresh_tokens,
        kind="sunset",
        description=(
            "Gate ACE and proc refreshes on per-surface stat-only change tokens."
        ),
        bead="sase-wr",
    ),
    FeatureFlag.admin_center_flags: FeatureFlagDefinition(
        key=FeatureFlag.admin_center_flags,
        kind="sunset",
        description=(
            "The Config catalog exposes the Flags pane for persistent "
            "feature-flag control."
        ),
        bead="sase-rx",
    ),
    FeatureFlag.agents_unified_query: FeatureFlagDefinition(
        key=FeatureFlag.agents_unified_query,
        kind="sunset",
        description=(
            "The Agents tab parses, evaluates, and edits its filter with the "
            "shared agents-live boolean query profile through the Rust corpus "
            "engine and the FilterBar chrome."
        ),
        bead="sase-zg",
    ),
    FeatureFlag.agent_sudo_requests: FeatureFlagDefinition(
        key=FeatureFlag.agent_sudo_requests,
        kind="beta",
        description=(
            "Gate the typed sudo request workflow while the runner, ACE modal, "
            "skill guard, and SSH relay phases land."
        ),
        bead="sase-111",
    ),
    FeatureFlag.monitor_continuation_records: FeatureFlagDefinition(
        key=FeatureFlag.monitor_continuation_records,
        kind="sunset",
        description=(
            "New monitor starts persist versioned continuation records, frozen "
            "outcome policy, checkpoints, and durable delivery/adoption state "
            "for production continuation routing."
        ),
        bead="sase-102",
    ),
    FeatureFlag.provider_drain: FeatureFlagDefinition(
        key=FeatureFlag.provider_drain,
        kind="beta",
        description=(
            "Hard-disabling an LLM provider drains it: a usage-limit disable "
            "submits a durable 'sase agent drain' proc that relaunches the "
            "agents that provider stranded and sends one enriched usage-limit "
            "notification naming what moved and what did not, and a manual "
            "disable in Launch Control offers the same relaunch."
        ),
        bead="sase-sx",
    ),
    FeatureFlag.queue_capacity_budget: FeatureFlagDefinition(
        key=FeatureFlag.queue_capacity_budget,
        kind="sunset",
        description=(
            "A %queue capacity value is this launch's runner-capacity "
            "budget and replaces max_running_agents for its own "
            "admission decision."
        ),
        bead="sase-zv",
    ),
    FeatureFlag.ref_sync_gesture: FeatureFlagDefinition(
        key=FeatureFlag.ref_sync_gesture,
        kind="sunset",
        description=(
            "A second ':' typed immediately after '@<kind>:' with an empty "
            "payload is consumed and refreshes that kind's backing sidecar "
            "(clone-if-missing or force-pull past the freshness TTL, else a "
            "catalog rescan), then reopens the '@' payload menu with "
            "newly-arrived rows badged."
        ),
        bead="sase-qu",
    ),
    FeatureFlag.refresh_panel: FeatureFlagDefinition(
        key=FeatureFlag.refresh_panel,
        kind="sunset",
        description=(
            "R opens the Refresh panel, whose single-key options run the "
            "current tab refresh, the Agents full-history rescan, a provider "
            "usage-window refresh, or all three, and ,y opens that panel with "
            "the cursor on Full history."
        ),
        bead="sase-105",
    ),
    FeatureFlag.typed_launch_units: FeatureFlagDefinition(
        key=FeatureFlag.typed_launch_units,
        kind="beta",
        description="Beta gate for typed launch units, %if, and %proc.",
        bead="sase-s7",
    ),
}

FEATURE_FLAG_DEFINITIONS: Mapping[FeatureFlag, FeatureFlagDefinition] = (
    MappingProxyType(_FEATURE_FLAG_DEFINITIONS)
)


def _validate_registry() -> None:
    """Fail fast if a hand-edited registry entry is inconsistent."""
    for key, definition in FEATURE_FLAG_DEFINITIONS.items():
        if definition.key != key:
            raise FeatureFlagError(
                f"feature flag definition key {definition.key!r} "
                f"does not match registry key {key!r}"
            )
        definition.validate()


def feature_flag_definitions() -> Mapping[str, FeatureFlagDefinition]:
    """Return registry definitions keyed by their string flag key."""
    return MappingProxyType(
        {str(key): definition for key, definition in FEATURE_FLAG_DEFINITIONS.items()}
    )


_validate_registry()

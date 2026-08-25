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

    admin_center_flags = "admin_center_flags"
    artifacts_agents_pane = "artifacts_agents_pane"
    provider_drain = "provider_drain"
    ref_sync_gesture = "ref_sync_gesture"
    typed_launch_units = "typed_launch_units"


_FEATURE_FLAG_DEFINITIONS: dict[FeatureFlag, FeatureFlagDefinition] = {
    FeatureFlag.admin_center_flags: FeatureFlagDefinition(
        key=FeatureFlag.admin_center_flags,
        kind="sunset",
        description=(
            "The Config catalog exposes the Flags pane for persistent "
            "feature-flag control."
        ),
        bead="sase-rx",
    ),
    FeatureFlag.artifacts_agents_pane: FeatureFlagDefinition(
        key=FeatureFlag.artifacts_agents_pane,
        kind="beta",
        description=(
            "The Artifacts tab shows a new 'Agent' pane immediately before "
            "Files, backed by the Textual-free agent catalog snapshot and "
            "the agents query profile."
        ),
        bead="sase-tm",
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

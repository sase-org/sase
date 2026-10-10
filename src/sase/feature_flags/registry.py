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

    agent_sudo_requests = "agent_sudo_requests"
    provider_drain = "provider_drain"
    autonomy_record_only = "autonomy_record_only"


_FEATURE_FLAG_DEFINITIONS: dict[FeatureFlag, FeatureFlagDefinition] = {
    FeatureFlag.agent_sudo_requests: FeatureFlagDefinition(
        key=FeatureFlag.agent_sudo_requests,
        kind="beta",
        description=(
            "Gate the typed sudo request workflow while the runner, TUI modal, "
            "skill guard, and SSH relay phases land."
        ),
        bead="sase-111",
    ),
    FeatureFlag.provider_drain: FeatureFlagDefinition(
        key=FeatureFlag.provider_drain,
        kind="beta",
        description=(
            "Hard-disabling an LLM provider drains it: a usage-limit disable "
            "submits a durable 'sase agent drain' proc that relaunches the "
            "agents that provider stranded and sends one enriched usage-limit "
            "notification naming what moved and what did not, and a manual "
            "hard disable in Launch Control submits the same drain "
            "automatically, toasting when it starts and when it finishes."
        ),
        bead="sase-sx",
    ),
    FeatureFlag.autonomy_record_only: FeatureFlagDefinition(
        key=FeatureFlag.autonomy_record_only,
        kind="sunset",
        description=(
            "Only agent_meta.autonomy carries %auto state: launches and "
            "autonomy mutations write no legacy approve/auto_approve_plan_action/"
            "auto_approve_argument/plan meta keys and the runner exports no "
            "SASE_AGENT_AUTO_APPROVE."
        ),
        bead="sase-1j0",
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

"""Code-owned SASE feature flag registry.

Definition authors must follow two rules:

- ``remove_by`` never appears here; it lives on the flag bead.
- Definitions are added only through ``sase flag new``, never by hand.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from sase.feature_flags.models import FeatureFlagDefinition, FeatureFlagError


class FeatureFlag(StrEnum):
    """Every SASE feature flag key. Add members through ``sase flag new``."""

    coder_inherits_planner_chat = "coder_inherits_planner_chat"
    prettier_enabled = "prettier_enabled"


_FEATURE_FLAG_DEFINITIONS: dict[FeatureFlag, FeatureFlagDefinition] = {
    FeatureFlag.coder_inherits_planner_chat: FeatureFlagDefinition(
        key=FeatureFlag.coder_inherits_planner_chat,
        kind="beta",
        description=(
            "Opt-in beta: the follow-up coder inherits the planner's chat "
            "via #fork instead of starting from the approved plan file alone."
        ),
        default=False,
        scope="global",
        bead="sase-nw",
    ),
    FeatureFlag.prettier_enabled: FeatureFlagDefinition(
        key=FeatureFlag.prettier_enabled,
        kind="sunset",
        description=(
            "Format markdown with prettier when it is installed. "
            "SASE_DISABLE_PRETTIER remains a deprecated alias."
        ),
        default=True,
        scope="global",
        bead="sase-nx",
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

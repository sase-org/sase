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

    artifacts_agent_pane_retired = "artifacts_agent_pane_retired"
    codex_explicit_instructions = "codex_explicit_instructions"
    grok_explicit_instructions = "grok_explicit_instructions"
    muse_explicit_instructions = "muse_explicit_instructions"


_FEATURE_FLAG_DEFINITIONS: dict[FeatureFlag, FeatureFlagDefinition] = {
    FeatureFlag.artifacts_agent_pane_retired: FeatureFlagDefinition(
        key=FeatureFlag.artifacts_agent_pane_retired,
        kind="sunset",
        description=(
            "Artifacts has no Agent sub-tab: Stitch becomes digit 1 and "
            "agent history lives in the Agents tab Archive."
        ),
        bead="sase-1kb",
    ),
    FeatureFlag.codex_explicit_instructions: FeatureFlagDefinition(
        key=FeatureFlag.codex_explicit_instructions,
        kind="sunset",
        description=(
            "Deliver the Codex root bundle through developer_instructions and "
            "suppress SASE native instruction duplicates."
        ),
        bead="sase-1ks",
    ),
    FeatureFlag.grok_explicit_instructions: FeatureFlagDefinition(
        key=FeatureFlag.grok_explicit_instructions,
        kind="sunset",
        description="Deliver Grok instruction bundles through --rules",
        bead="sase-1kt",
    ),
    FeatureFlag.muse_explicit_instructions: FeatureFlagDefinition(
        key=FeatureFlag.muse_explicit_instructions,
        kind="sunset",
        description="Deliver Muse instruction bundles as a prompt prefix",
        bead="sase-1ku",
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

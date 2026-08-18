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
    commit_finalizer_shared_clone_exempt = "commit_finalizer_shared_clone_exempt"
    completion_refresh_on_update = "completion_refresh_on_update"
    epic_resume_gate = "epic_resume_gate"
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
    FeatureFlag.commit_finalizer_shared_clone_exempt: FeatureFlagDefinition(
        key=FeatureFlag.commit_finalizer_shared_clone_exempt,
        kind="sunset",
        description=(
            "Classify foreign-agent commits and already-published/"
            "pending-publication transitions in machine-wide shared clones "
            "(opened-external and sdd-kind repos) as races rather than "
            "discards in the commit finalizer's dirty-work guard. Disable to "
            "fall back to strict single-owner classification."
        ),
        default=True,
        scope="global",
        bead="sase-pk",
    ),
    FeatureFlag.completion_refresh_on_update: FeatureFlagDefinition(
        key=FeatureFlag.completion_refresh_on_update,
        kind="beta",
        description=(
            "After a successful sase update, regenerate, zcompile, and "
            "restamp installed shell completion scripts. Off by default "
            "while the generator soaks."
        ),
        default=False,
        scope="global",
        bead="sase-om",
    ),
    FeatureFlag.epic_resume_gate: FeatureFlagDefinition(
        key=FeatureFlag.epic_resume_gate,
        kind="beta",
        description=(
            "Opt-in beta: the epic_resume chop raises an EpicResume gate "
            "when a failed phase agent stalls an epic."
        ),
        default=False,
        scope="global",
        bead="sase-pa",
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

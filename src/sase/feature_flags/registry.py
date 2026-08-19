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

    coder_inherits_planner_chat = "coder_inherits_planner_chat"
    commit_finalizer_shared_clone_exempt = "commit_finalizer_shared_clone_exempt"
    completion_refresh_on_update = "completion_refresh_on_update"
    epic_resume_gate = "epic_resume_gate"
    plugin_catalog_scoped_latest = "plugin_catalog_scoped_latest"
    prettier_enabled = "prettier_enabled"
    ref_sync_gesture = "ref_sync_gesture"


_FEATURE_FLAG_DEFINITIONS: dict[FeatureFlag, FeatureFlagDefinition] = {
    FeatureFlag.coder_inherits_planner_chat: FeatureFlagDefinition(
        key=FeatureFlag.coder_inherits_planner_chat,
        kind="beta",
        description=(
            "Opt-in beta: the follow-up coder inherits the planner's chat "
            "via #fork instead of starting from the approved plan file alone."
        ),
        bead="sase-qe",
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
        bead="sase-qi",
    ),
    FeatureFlag.completion_refresh_on_update: FeatureFlagDefinition(
        key=FeatureFlag.completion_refresh_on_update,
        kind="beta",
        description=(
            "After a successful sase update, regenerate, zcompile, and "
            "restamp installed shell completion scripts. Off by default "
            "while the generator soaks."
        ),
        bead="sase-qg",
    ),
    FeatureFlag.epic_resume_gate: FeatureFlagDefinition(
        key=FeatureFlag.epic_resume_gate,
        kind="beta",
        description=(
            "Opt-in beta: the epic_resume chop raises an EpicResume gate "
            "when a failed phase agent stalls an epic."
        ),
        bead="sase-qh",
    ),
    FeatureFlag.plugin_catalog_scoped_latest: FeatureFlagDefinition(
        key=FeatureFlag.plugin_catalog_scoped_latest,
        kind="beta",
        description=(
            "Eager PyPI latest-version enrichment is limited to installed "
            "plugins. The Updates > Plugins highlighted row lazily fetches "
            "latest for the current uninstalled entry through the detail "
            "debouncer. sase plugin show still fetches the requested plugin. "
            "sase plugin list stays installed-only unless -A|--all-latest."
        ),
        bead="sase-qq",
    ),
    FeatureFlag.prettier_enabled: FeatureFlagDefinition(
        key=FeatureFlag.prettier_enabled,
        kind="sunset",
        description=(
            "Format markdown with prettier when it is installed. "
            "SASE_DISABLE_PRETTIER remains a deprecated alias."
        ),
        bead="sase-qf",
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

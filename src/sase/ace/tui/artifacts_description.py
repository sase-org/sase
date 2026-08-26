"""Widget-free mode helpers for the Artifacts pane description brief."""

from __future__ import annotations

from typing import Literal


ArtifactsDescriptionMode = Literal["off", "summary", "full"]

ARTIFACTS_DESCRIPTION_MODE_ORDER: tuple[ArtifactsDescriptionMode, ...] = (
    "off",
    "summary",
    "full",
)
DEFAULT_ARTIFACTS_DESCRIPTION_MODE: ArtifactsDescriptionMode = "summary"
ARTIFACTS_BRIEF_MAX_LINES = 6


def normalize_artifacts_description_mode(value: object) -> ArtifactsDescriptionMode:
    """Return a supported description mode, falling back to the session default."""

    if value in ARTIFACTS_DESCRIPTION_MODE_ORDER:
        return value  # type: ignore[return-value]
    return DEFAULT_ARTIFACTS_DESCRIPTION_MODE


def cycle_artifacts_description_mode(
    mode: object,
    direction: int,
) -> ArtifactsDescriptionMode:
    """Cycle *mode* with wraparound in the sign of *direction*.

    Cycling is forward-only in the current UI (one key, three modes);
    *direction* exists so this helper matches its split-mode sibling and
    stays symmetric for tests.
    """

    normalized = normalize_artifacts_description_mode(mode)
    index = ARTIFACTS_DESCRIPTION_MODE_ORDER.index(normalized)
    step = 1 if direction >= 0 else -1
    return ARTIFACTS_DESCRIPTION_MODE_ORDER[
        (index + step) % len(ARTIFACTS_DESCRIPTION_MODE_ORDER)
    ]


def unconfigured_pane_description_hint(pane_id: str) -> str:
    """Return the developer-facing hint for an undescribed provider pane."""

    return (
        "Describe this pane with ref.pane.description in its sidecar ref "
        f'config, or ace.artifacts.panes."{pane_id}".description in sase.yml.'
    )


__all__ = [
    "ARTIFACTS_BRIEF_MAX_LINES",
    "ARTIFACTS_DESCRIPTION_MODE_ORDER",
    "DEFAULT_ARTIFACTS_DESCRIPTION_MODE",
    "ArtifactsDescriptionMode",
    "cycle_artifacts_description_mode",
    "normalize_artifacts_description_mode",
    "unconfigured_pane_description_hint",
]

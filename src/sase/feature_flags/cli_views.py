"""Shared view model behind ``sase flag list`` and ``sase flag show``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import sase
from sase.bead.flag_due import FlagRemovalState
from sase.bead_flag_presentation import flag_due_presentation
from sase.core import time as core_time
from sase.feature_flags.beads import (
    FlagBeadSnapshot,
    flag_bead_for_id,
    flag_bead_for_key,
    flag_record_from_snapshot,
    load_flag_bead_snapshots,
)
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDefinition,
    FeatureFlagError,
    FeatureFlagSnapshot,
)
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.snapshot import current_flags


@dataclass(frozen=True)
class FlagView:
    """One flag as the CLI renders it."""

    definition: FeatureFlagDefinition
    decision: FeatureFlagDecision
    bead: FlagBeadSnapshot | None
    due_state: FlagRemovalState | None


def flag_views(
    *,
    definitions: Mapping[str, FeatureFlagDefinition] | None,
    snapshot: FeatureFlagSnapshot | None,
    beads: tuple[FlagBeadSnapshot, ...] | None,
    today: date | None,
    release: str | None,
) -> tuple[FlagView, ...]:
    """Join registry definitions with resolved values and their flag beads."""
    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    resolved_snapshot = current_flags() if snapshot is None else snapshot
    resolved_beads = load_flag_bead_snapshots() if beads is None else beads
    resolved_today = core_time.local_now().date() if today is None else today
    resolved_release = sase.__version__ if release is None else release
    views: list[FlagView] = []
    for key, definition in sorted(resolved_definitions.items()):
        try:
            decision = resolved_snapshot.decision(key)
        except FeatureFlagError:
            decision = FeatureFlagDecision(
                key=key,
                enabled=definition.default,
                default=definition.default,
                source="default",
                source_detail="",
                overridden=False,
            )
        bead = None
        if definition.bead:
            bead = flag_bead_for_id(resolved_beads, definition.bead)
        if bead is None:
            bead = flag_bead_for_key(resolved_beads, key)
        due_state: FlagRemovalState | None = None
        record = None if bead is None else flag_record_from_snapshot(bead)
        if record is not None:
            due_state = flag_due_presentation(
                record, today=resolved_today, release=resolved_release
            ).state
        views.append(
            FlagView(
                definition=definition,
                decision=decision,
                bead=bead,
                due_state=due_state,
            )
        )
    return tuple(views)


__all__ = [
    "FlagView",
    "flag_views",
]

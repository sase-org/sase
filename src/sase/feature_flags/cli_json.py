"""JSON payload fragments shared by the ``sase flag`` subcommands."""

from __future__ import annotations

from typing import Any

from sase.feature_flags.beads import flag_record_from_snapshot
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import FeatureFlagDiagnostic


def diagnostic_json(diagnostic: FeatureFlagDiagnostic) -> dict[str, Any]:
    """Serialize one resolver diagnostic."""
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "severity": diagnostic.severity,
        "source": diagnostic.source,
    }


def flag_view_json(view: FlagView) -> dict[str, Any]:
    """Serialize the fields both ``list --json`` and ``show --json`` emit."""
    record = None if view.bead is None else flag_record_from_snapshot(view.bead)
    return {
        "bead": None if view.bead is None else view.bead.id,
        "bead_status": None if view.bead is None else view.bead.status,
        "default": view.definition.default,
        "description": view.definition.description,
        "due_state": view.due_state,
        "enabled": view.decision.enabled,
        "key": str(view.definition.key),
        "kind": view.definition.kind,
        "overridden": view.decision.overridden,
        "remove_by_date": None if record is None else record.remove_by_date,
        "remove_by_release": None if record is None else record.remove_by_release,
        "source": view.decision.source,
        "source_detail": view.decision.source_detail,
    }


__all__ = [
    "diagnostic_json",
    "flag_view_json",
]

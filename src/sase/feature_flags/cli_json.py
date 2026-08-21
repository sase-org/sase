"""JSON payload fragments shared by the ``sase flag`` subcommands."""

from __future__ import annotations

from typing import Any

from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDiagnostic,
    FeatureFlagMutationOutcome,
)


def diagnostic_json(diagnostic: FeatureFlagDiagnostic) -> dict[str, Any]:
    """Serialize one resolver diagnostic."""
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "severity": diagnostic.severity,
        "source": diagnostic.source,
    }


def decision_json(decision: FeatureFlagDecision) -> dict[str, Any]:
    """Serialize one resolved feature-flag decision."""
    return {
        "default": decision.default,
        "enabled": decision.enabled,
        "key": decision.key,
        "overridden": decision.overridden,
        "source": decision.source,
        "source_detail": decision.source_detail,
    }


def mutation_json(outcome: FeatureFlagMutationOutcome) -> dict[str, Any]:
    """Serialize the shared mutation facade outcome."""
    return {
        "after": decision_json(outcome.after),
        "before": decision_json(outcome.before),
        "changed": outcome.changed,
        "diagnostics": [diagnostic_json(item) for item in outcome.diagnostics],
        "enabled": outcome.enabled,
        "key": outcome.key,
        "previous_saved": outcome.previous_saved,
        "shadowed": outcome.shadowed,
        "shadowing_source": outcome.shadowing_source,
        "state_path": outcome.state_path,
    }


def flag_view_json(view: FlagView) -> dict[str, Any]:
    """Serialize the fields both ``list --json`` and ``show --json`` emit."""
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
        "remove_by_date": None if view.bead is None else view.bead.remove_by_date,
        "remove_by_release": (
            None if view.bead is None else view.bead.remove_by_release
        ),
        "saved": view.saved,
        "source": view.decision.source,
        "source_detail": view.decision.source_detail,
    }


__all__ = [
    "decision_json",
    "diagnostic_json",
    "flag_view_json",
    "mutation_json",
]

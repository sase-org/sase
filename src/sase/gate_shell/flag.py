"""Feature-flag gate for gate-shell handoff of blocking wait consumers."""

from __future__ import annotations

from sase.feature_flags.registry import FeatureFlag
from sase.feature_flags.snapshot import current_flags


def gate_shell_handoff_enabled() -> bool:
    """Return the process-local `gate_shell_handoff` flag decision."""
    return current_flags().enabled(FeatureFlag.gate_shell_handoff)

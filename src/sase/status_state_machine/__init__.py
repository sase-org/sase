"""
State machine for managing ChangeSpec STATUS field transitions.

This package provides centralized logic for validating and performing
STATUS field transitions across all sase workflows.
"""

from .constants import (
    VALID_STATUSES,
    VALID_TRANSITIONS,
    is_valid_transition,
    remove_workspace_suffix,
)
from .transitions import (
    SiblingRevertResult,
    transition_changespec_status,
)

__all__ = [
    # Constants
    "VALID_STATUSES",
    "VALID_TRANSITIONS",
    # Validation
    "is_valid_transition",
    "remove_workspace_suffix",
    # Transitions
    "SiblingRevertResult",
    "transition_changespec_status",
]

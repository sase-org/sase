"""DELTAS field operations for ChangeSpec project files."""

from .persistence import (
    CHANGESPEC_SECTION_ORDER,
    apply_deltas_update,
    update_changespec_deltas_field,
)

__all__ = [
    "CHANGESPEC_SECTION_ORDER",
    "apply_deltas_update",
    "update_changespec_deltas_field",
]

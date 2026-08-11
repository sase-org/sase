"""
State machine for managing Patch STATUS field transitions.

This package provides centralized logic for validating and performing
STATUS field transitions across all sase workflows.
"""

from .constants import (
    ARCHIVE_STATUSES,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    is_valid_transition,
    remove_workspace_suffix,
)
from .field_updates import (
    reset_patch_pr_url,
    update_patch_bug_atomic,
    update_patch_description_atomic,
    update_patch_parent_atomic,
    update_patch_pr_origin_atomic,
    update_patch_pr_url_atomic,
    update_parent_references_atomic,
)
from .siblings import SiblingRevertResult
from .transitions import transition_patch_status

reset_changespec_pr_url = reset_patch_pr_url  # legacy compatibility alias
update_changespec_bug_atomic = update_patch_bug_atomic  # legacy compatibility alias
update_changespec_pr_url_atomic = (
    update_patch_pr_url_atomic  # legacy compatibility alias
)
update_changespec_description_atomic = (  # legacy compatibility alias
    update_patch_description_atomic
)
update_changespec_parent_atomic = (
    update_patch_parent_atomic  # legacy compatibility alias
)
transition_changespec_status = transition_patch_status  # legacy compatibility alias

__all__ = [
    # Constants
    "ARCHIVE_STATUSES",
    "VALID_STATUSES",
    "VALID_TRANSITIONS",
    # Validation
    "is_valid_transition",
    "remove_workspace_suffix",
    # Field updates
    "reset_changespec_pr_url",  # legacy compatibility alias
    "reset_patch_pr_url",
    "update_changespec_bug_atomic",  # legacy compatibility alias
    "update_changespec_pr_url_atomic",  # legacy compatibility alias
    "update_changespec_description_atomic",  # legacy compatibility alias
    "update_changespec_parent_atomic",  # legacy compatibility alias
    "update_patch_bug_atomic",
    "update_patch_description_atomic",
    "update_patch_parent_atomic",
    "update_patch_pr_origin_atomic",
    "update_patch_pr_url_atomic",
    "update_parent_references_atomic",
    # Transitions
    "SiblingRevertResult",
    "transition_changespec_status",  # legacy compatibility alias
    "transition_patch_status",
]

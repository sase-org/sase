"""PR submission and comment status checking for Patches."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from .patch import Patch, find_all_patches

find_all_changespecs = find_all_patches  # legacy compatibility alias

# Statuses that should be checked for submission/comments
# Note: "Changes Requested" has been replaced by the COMMENTS field
SYNCABLE_STATUSES = ["Mailed"]


def is_parent_submitted(patch: Patch) -> bool:
    """Check if a Patch's parent has been submitted.

    Args:
        patch: The Patch to check the parent of.

    Returns:
        True if the parent is submitted or if there is no parent, False otherwise.
    """
    # No parent means we can proceed
    if patch.parent is None:
        return True

    # Find all patches to locate the parent
    all_patches = find_all_changespecs()  # legacy compatibility alias

    # Look for the parent by name
    for cs in all_patches:
        if cs.name == patch.parent:
            return cs.status == "Submitted"

    # Parent not found - assume it's okay to proceed (might have been deleted)
    return True

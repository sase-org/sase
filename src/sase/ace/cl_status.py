"""CL submission and comment status checking for ChangeSpecs."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from .changespec import ChangeSpec, find_all_changespecs

# Statuses that should be checked for submission/comments
# Note: "Changes Requested" has been replaced by the COMMENTS field
SYNCABLE_STATUSES = ["Mailed"]


def is_parent_submitted(changespec: ChangeSpec) -> bool:
    """Check if a ChangeSpec's parent has been submitted.

    Args:
        changespec: The ChangeSpec to check the parent of.

    Returns:
        True if the parent is submitted or if there is no parent, False otherwise.
    """
    # No parent means we can proceed
    if changespec.parent is None:
        return True

    # Find all changespecs to locate the parent
    all_changespecs = find_all_changespecs()

    # Look for the parent by name
    for cs in all_changespecs:
        if cs.name == changespec.parent:
            return cs.status == "Submitted"

    # Parent not found - assume it's okay to proceed (might have been deleted)
    return True


def is_cl_submitted(changespec: ChangeSpec) -> bool:
    """Check if the CL itself is submitted (not just the parent).

    Runs the is_cl_submitted shell command synchronously.
    """
    import re
    import subprocess

    if not changespec.cl:
        return False

    # Extract CL number from URL
    match = re.match(r"https?://cl/(\d+)", changespec.cl)
    if not match:
        return False

    cl_number = match.group(1)
    try:
        result = subprocess.run(
            ["is_cl_submitted", cl_number],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

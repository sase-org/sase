"""Functions for modifying existing COMMITS entries in ChangeSpecs."""

from sase.spec_writer.client import make_request, submit_spec_write_and_wait
from sase.spec_writer.models import OperationType


def reject_proposals_and_set_status_atomic(
    project_file: str,
    cl_name: str,
    final_status: str,
) -> bool:
    """Reject all new proposals and optionally set STATUS in a single atomic write.

    Args:
        project_file: Path to the project file.
        cl_name: The CL name to update.
        final_status: The final status to set. Should be either:
            - "Mailed" to set status directly to Mailed
            - Empty string to keep current status unchanged

    Returns:
        True if successful, False otherwise.
    """
    try:
        request = make_request(
            project_file,
            OperationType.REJECT_PROPOSALS_AND_SET_STATUS,
            {
                "cl_name": cl_name,
                "final_status": final_status,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False


def reject_all_new_proposals(
    project_file: str,
    cl_name: str,
) -> int:
    """Reject all new proposals by changing (!: NEW PROPOSAL) to (~!: NEW PROPOSAL).

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the project file.
        cl_name: The CL name to update.

    Returns:
        Number of proposals rejected, or -1 on error.
    """
    try:
        request = make_request(
            project_file,
            OperationType.REJECT_ALL_NEW_PROPOSALS,
            {
                "cl_name": cl_name,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        if response.success and response.result:
            return response.result.get("rejected_count", 0)
        return -1
    except Exception:
        return -1


def update_commit_entry_suffix(
    project_file: str,
    cl_name: str,
    entry_id: str,
    new_suffix_type: str,
) -> bool:
    """Update or remove the suffix of a COMMITS entry.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the project file.
        cl_name: The CL name to update.
        entry_id: The entry ID to update (e.g., "2a").
        new_suffix_type: The action - "remove" to remove suffix, "reject" to change
            (!: MSG) to (~!: MSG).

    Returns:
        True if successful, False otherwise.
    """
    if new_suffix_type not in ("remove", "reject"):
        return False

    try:
        request = make_request(
            project_file,
            OperationType.UPDATE_COMMIT_ENTRY_SUFFIX,
            {
                "cl_name": cl_name,
                "entry_id": entry_id,
                "new_suffix_type": new_suffix_type,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False


def mark_proposal_broken(
    project_file: str,
    cl_name: str,
    entry_id: str,
) -> bool:
    """Mark a proposal as broken by setting its suffix to (~!: BROKEN PROPOSAL).

    This is called when a proposal's diff fails to apply to a workspace.
    Broken proposals are skipped in future hook runs.
    Works regardless of the current suffix (NEW PROPOSAL, no suffix, etc.).

    Args:
        project_file: Path to the project file.
        cl_name: The CL name to update.
        entry_id: The proposal entry ID (e.g., "2a").

    Returns:
        True if successful, False otherwise.
    """
    try:
        request = make_request(
            project_file,
            OperationType.MARK_PROPOSAL_BROKEN,
            {
                "cl_name": cl_name,
                "entry_id": entry_id,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False

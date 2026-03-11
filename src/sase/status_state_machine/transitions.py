"""
Main status transition logic for ChangeSpecs.

This module contains the core transition_changespec_status function and related helpers.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.spec_writer.client import make_request, submit_spec_write_and_wait
from sase.spec_writer.models import OperationType
from sase.vcs_provider import get_vcs_provider

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


@dataclass
class SiblingRevertResult:
    """Result of reverting a sibling Draft ChangeSpec."""

    name: str
    success: bool
    error: str | None = None


def check_siblings_for_unreverted_children(
    project_file: str,
    base_name: str,
    excluded_name: str,
) -> str | None:
    """Check if any sibling WIP/Draft ChangeSpec has unreverted children.

    When transitioning a WIP/Draft ChangeSpec to Ready, sibling WIP/Draft
    ChangeSpecs will be auto-reverted. This function checks if any of those
    siblings have unreverted children, which would block the revert operation.

    Args:
        project_file: Path to the project file.
        base_name: The base name without suffix (e.g., "foo_bar").
        excluded_name: The original suffixed name that is being transitioned
            (don't check this one).

    Returns:
        Error message if any sibling has unreverted children, None otherwise.
    """
    from sase.ace.changespec import find_all_changespecs, parse_project_file
    from sase.ace.revert import has_children
    from sase.sase_utils import strip_reverted_suffix

    changespecs = parse_project_file(project_file)
    all_changespecs = find_all_changespecs()

    for cs in changespecs:
        # Skip the one being transitioned
        if cs.name == excluded_name:
            continue

        # Check if same basename and is WIP or Draft
        cs_base = strip_reverted_suffix(cs.name)
        if cs_base == base_name and cs.status in ("WIP", "Draft"):
            # Check if this sibling has unreverted children
            if has_children(cs, all_changespecs):
                return (
                    f"Cannot transition '{excluded_name}' to Ready: "
                    f"sibling ChangeSpec '{cs.name}' ({cs.status}) has unreverted children."
                )

    return None


def _revert_sibling_draft_changespecs(
    project_file: str,
    base_name: str,
    excluded_name: str,
    console: "Console | None" = None,
) -> list[SiblingRevertResult]:
    """Revert all WIP/Draft ChangeSpecs with the same basename.

    When a WIP/Draft ChangeSpec transitions to Ready and has its suffix stripped,
    any other WIP/Draft ChangeSpecs with the same base name are automatically
    reverted since they are now obsolete.

    Args:
        project_file: Path to the project file.
        base_name: The base name without suffix (e.g., "foo_bar").
        excluded_name: The original suffixed name that was just transitioned
            (don't revert this one).
        console: Optional Rich console for output.

    Returns:
        List of SiblingRevertResult for each sibling that was attempted to be
        reverted.
    """
    from sase.ace.changespec import parse_project_file
    from sase.ace.revert import revert_changespec
    from sase.sase_utils import strip_reverted_suffix

    changespecs = parse_project_file(project_file)
    results: list[SiblingRevertResult] = []

    for cs in changespecs:
        # Skip the one we just transitioned
        if cs.name == excluded_name:
            continue

        # Check if same basename and is WIP or Draft
        cs_base = strip_reverted_suffix(cs.name)
        if cs_base == base_name and cs.status in ("WIP", "Draft"):
            logger.info(f"Auto-reverting sibling ChangeSpec: {cs.name} ({cs.status})")
            if console:
                console.print(
                    f"[yellow]Auto-reverting sibling {cs.status}:[/] {cs.name}"
                )
            success, error = revert_changespec(cs, console=console)
            if not success:
                logger.warning(f"Failed to revert {cs.name}: {error}")
            results.append(
                SiblingRevertResult(name=cs.name, success=success, error=error)
            )

    return results


def _handle_suffix_strip(
    project_file: str,
    suffixed_name: str,
    base_name: str,
    console: "Console | None" = None,
) -> list[SiblingRevertResult]:
    """Handle stripping __<N> suffix when transitioning to Ready.

    Args:
        project_file: Path to the project file.
        suffixed_name: The current name with suffix (e.g., "foo_bar__1").
        base_name: The base name without suffix (e.g., "foo_bar").
        console: Optional Rich console for output.

    Returns:
        List of SiblingRevertResult for reverted siblings.
    """
    from sase.ace.revert import update_changespec_name_atomic
    from sase.running_field import get_workspace_directory, update_running_field_cl_name

    # Update NAME field
    update_changespec_name_atomic(project_file, suffixed_name, base_name)

    # Rename the CL in Mercurial to match the new name
    project_basename = Path(project_file).stem
    try:
        workspace_dir = get_workspace_directory(project_basename)

        provider = get_vcs_provider(workspace_dir)

        # First checkout the CL we want to rename
        resolved = provider.resolve_revision(
            suffixed_name, project_basename, workspace_dir
        )
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            logger.warning(f"Failed to checkout CL {suffixed_name}: {checkout_err}")
        else:
            # Now rename the CL
            rename_ok, rename_err = provider.rename_branch(base_name, workspace_dir)
            if not rename_ok:
                logger.warning(f"Failed to rename CL: {rename_err}")
    except RuntimeError as e:
        logger.warning(f"Could not get workspace directory: {e}")

    # Update PARENT references in other ChangeSpecs
    request = make_request(
        project_file,
        OperationType.UPDATE_PARENT_REFERENCES,
        {"old_name": suffixed_name, "new_name": base_name},
    )
    submit_spec_write_and_wait(request, timeout=10.0)

    # Update RUNNING field entries
    update_running_field_cl_name(project_file, suffixed_name, base_name)

    # Auto-revert sibling WIP/Draft ChangeSpecs with the same basename
    return _revert_sibling_draft_changespecs(
        project_file, base_name, suffixed_name, console
    )


def _handle_suffix_append(
    project_file: str,
    base_name: str,
    suffixed_name: str,
) -> None:
    """Handle appending __<N> suffix when transitioning from Ready to Draft.

    Args:
        project_file: Path to the project file.
        base_name: The base name without suffix (e.g., "foo_bar").
        suffixed_name: The new name with suffix (e.g., "foo_bar__1").
    """
    from sase.ace.revert import update_changespec_name_atomic
    from sase.running_field import get_workspace_directory, update_running_field_cl_name

    # Update NAME field
    update_changespec_name_atomic(project_file, base_name, suffixed_name)

    # Rename the CL in Mercurial to match the new name
    project_basename = Path(project_file).stem
    try:
        workspace_dir = get_workspace_directory(project_basename)

        provider = get_vcs_provider(workspace_dir)

        # First checkout the CL we want to rename
        resolved = provider.resolve_revision(base_name, project_basename, workspace_dir)
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            logger.warning(f"Failed to checkout CL {base_name}: {checkout_err}")
        else:
            # Now rename the CL
            rename_ok, rename_err = provider.rename_branch(suffixed_name, workspace_dir)
            if not rename_ok:
                logger.warning(f"Failed to rename CL: {rename_err}")
    except RuntimeError as e:
        logger.warning(f"Could not get workspace directory: {e}")

    # Update PARENT references in other ChangeSpecs
    request = make_request(
        project_file,
        OperationType.UPDATE_PARENT_REFERENCES,
        {"old_name": base_name, "new_name": suffixed_name},
    )
    submit_spec_write_and_wait(request, timeout=10.0)

    # Update RUNNING field entries
    update_running_field_cl_name(project_file, base_name, suffixed_name)


def transition_changespec_status(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: "Console | None" = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """
    Transition a ChangeSpec to a new STATUS with optional validation.

    Submits a TRANSITION_STATUS request to the spec_writer, then orchestrates
    post-lock operations (mentor flags, suffix strip/append, sibling reverts).

    Args:
        project_file: Path to the ProjectSpec file
        changespec_name: NAME of the ChangeSpec to update
        new_status: New STATUS value
        validate: If True, validate the transition is allowed
        console: Optional Rich console for output during sibling reverts

    Returns:
        Tuple of (success, old_status, error_msg, sibling_revert_results)
        - success: True if transition succeeded
        - old_status: Previous status value (None if not found)
        - error_msg: Error message if failed (None if succeeded)
        - sibling_revert_results: List of SiblingRevertResult for reverted siblings
    """
    request = make_request(
        project_file,
        OperationType.TRANSITION_STATUS,
        {
            "changespec_name": changespec_name,
            "new_status": new_status,
            "validate": validate,
        },
    )
    response = submit_spec_write_and_wait(request, timeout=10.0)

    if not response.success:
        old_status = response.result.get("old_status") if response.result else None
        return (False, old_status, response.error, [])

    result = response.result
    assert result is not None
    old_status = result["old_status"]
    suffix_strip_info = result.get("suffix_strip_info")
    suffix_append_info = result.get("suffix_append_info")
    mentor_op = result.get("mentor_op")

    # Execute mentor ops post-lock (no deadlock risk)
    if mentor_op == "set_draft":
        from sase.ace.mentors import set_mentor_draft_flags

        set_mentor_draft_flags(project_file, changespec_name)
    elif mentor_op == "clear_draft":
        from sase.ace.mentors import clear_mentor_draft_flags

        clear_mentor_draft_flags(project_file, changespec_name)

    sibling_results: list[SiblingRevertResult] = []

    # Strip __<N> suffix when transitioning to Ready (outside lock)
    if suffix_strip_info is not None:
        suffixed_name, base_name = suffix_strip_info
        sibling_results = _handle_suffix_strip(
            project_file, suffixed_name, base_name, console
        )

    # Append __<N> suffix when transitioning from Ready to Draft (outside lock)
    if suffix_append_info is not None:
        base_name, suffixed_name = suffix_append_info
        _handle_suffix_append(project_file, base_name, suffixed_name)

    return (True, old_status, None, sibling_results)

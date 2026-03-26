"""Individual status transition handlers."""

import logging
from datetime import datetime

from sase.ace.changespec import write_changespec_atomic

from .constants import VALID_TRANSITIONS, is_valid_transition
from .field_updates import apply_status_update
from .siblings import check_siblings_for_unreverted_children

logger = logging.getLogger(__name__)


def handle_draft_transition(
    project_file: str,
    changespec_name: str,
    old_status: str,
    new_status: str,
    lines: list[str],
    validate: bool,
) -> tuple[bool, str | None, str | None, tuple[str, str] | None]:
    """Handle transition to Draft status (from Ready).

    Returns:
        Tuple of (success, old_status, error_msg, suffix_append_info)
    """
    from sase.ace.changespec import find_all_changespecs
    from sase.ace.mentors import set_mentor_draft_flags
    from sase.core.changespec import get_next_suffix_number

    all_changespecs = find_all_changespecs()
    invalid_children = [
        cs
        for cs in all_changespecs
        if cs.parent == changespec_name
        and cs.status not in ("WIP", "Draft", "Reverted")
    ]
    if invalid_children:
        child_info = ", ".join(f"{cs.name} ({cs.status})" for cs in invalid_children)
        error_msg = (
            f"Cannot transition '{changespec_name}' to Draft: "
            f"children must be WIP, Draft, or Reverted. "
            f"Invalid children: {child_info}"
        )
        logger.error(error_msg)
        return (False, old_status, error_msg, None)

    if validate and not is_valid_transition(old_status, new_status):
        error_msg = (
            f"Invalid status transition for '{changespec_name}': "
            f"'{old_status}' -> '{new_status}'. "
            f"Allowed transitions from '{old_status}': "
            f"{VALID_TRANSITIONS.get(old_status, [])}"
        )
        logger.error(error_msg)
        return (False, old_status, error_msg, None)

    # Valid transition to Draft
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = (
        f"[{timestamp}] Transitioning {changespec_name}: "
        f"'{old_status}' -> '{new_status}'"
    )
    if not validate:
        log_msg += " (validation skipped)"
    logger.info(log_msg)

    updated_content = apply_status_update(lines, changespec_name, new_status)
    write_changespec_atomic(
        project_file,
        updated_content,
        f"Update STATUS to {new_status} for {changespec_name}",
    )

    # Add _<N> suffix when transitioning to Draft
    existing_names = {cs.name for cs in all_changespecs}
    suffix_num = get_next_suffix_number(changespec_name, existing_names)
    suffix_append_info = (
        changespec_name,
        f"{changespec_name}_{suffix_num}",
    )

    # Set #Draft flag on mentors
    set_mentor_draft_flags(project_file, changespec_name)

    return (True, old_status, None, suffix_append_info)


def handle_ready_transition(
    project_file: str,
    changespec_name: str,
    old_status: str,
    new_status: str,
    lines: list[str],
    validate: bool,
) -> tuple[bool, str | None, str | None, tuple[str, str] | None]:
    """Handle transition to Ready status (from WIP or Draft), or other non-Draft statuses.

    Returns:
        Tuple of (success, old_status, error_msg, suffix_strip_info)
    """
    from sase.ace.changespec import parse_project_file

    # Check parent constraint
    changespecs = parse_project_file(project_file)
    current_cs = next((cs for cs in changespecs if cs.name == changespec_name), None)
    if current_cs and current_cs.parent:
        parent_cs = next(
            (cs for cs in changespecs if cs.name == current_cs.parent), None
        )
        if (
            parent_cs
            and parent_cs.status in ("WIP", "Draft")
            and new_status not in ("WIP", "Draft", "Reverted")
        ):
            error_msg = (
                f"Cannot transition '{changespec_name}' to {new_status}: "
                f"parent '{current_cs.parent}' is {parent_cs.status}. "
                f"Children of WIP/Draft ChangeSpecs must be WIP, Draft, or Reverted."
            )
            logger.error(error_msg)
            return (False, old_status, error_msg, None)

    # Validate transition if requested
    if validate and not is_valid_transition(old_status, new_status):
        error_msg = (
            f"Invalid status transition for '{changespec_name}': "
            f"'{old_status}' -> '{new_status}'. "
            f"Allowed transitions from '{old_status}': "
            f"{VALID_TRANSITIONS.get(old_status, [])}"
        )
        logger.error(error_msg)
        return (False, old_status, error_msg, None)

    # Validate siblings don't have unreverted children when transitioning to Ready
    if new_status == "Ready" and old_status in ("WIP", "Draft"):
        from sase.core.changespec import has_suffix, strip_reverted_suffix

        if has_suffix(changespec_name):
            base_name = strip_reverted_suffix(changespec_name)
            sibling_error = check_siblings_for_unreverted_children(
                project_file, base_name, changespec_name
            )
            if sibling_error:
                logger.error(sibling_error)
                return (False, old_status, sibling_error, None)

    # Perform transition
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = (
        f"[{timestamp}] Transitioning {changespec_name}: "
        f"'{old_status}' -> '{new_status}'"
    )
    if not validate:
        log_msg += " (validation skipped)"
    logger.info(log_msg)

    updated_content = apply_status_update(lines, changespec_name, new_status)
    write_changespec_atomic(
        project_file,
        updated_content,
        f"Update STATUS to {new_status} for {changespec_name}",
    )

    suffix_strip_info = None

    # Clear #Draft from mentors when transitioning from Draft to Ready
    # (WIP has no mentors to clear)
    if old_status == "Draft" and new_status == "Ready":
        from sase.ace.mentors import clear_mentor_draft_flags
        from sase.core.changespec import has_suffix, strip_reverted_suffix

        clear_mentor_draft_flags(project_file, changespec_name)

        # Check if we need to strip suffix (done outside lock)
        if has_suffix(changespec_name):
            suffix_strip_info = (
                changespec_name,
                strip_reverted_suffix(changespec_name),
            )

    # Strip suffix when transitioning from WIP to Ready
    if old_status == "WIP" and new_status == "Ready":
        from sase.core.changespec import has_suffix, strip_reverted_suffix

        if has_suffix(changespec_name):
            suffix_strip_info = (
                changespec_name,
                strip_reverted_suffix(changespec_name),
            )

    return (True, old_status, None, suffix_strip_info)


def handle_wip_to_draft_transition(
    project_file: str,
    changespec_name: str,
    old_status: str,
    new_status: str,
    lines: list[str],
    validate: bool,
) -> tuple[bool, str | None, str | None]:
    """Handle transition from WIP to Draft status.

    This is a simple status change — no suffix manipulation, no mentor flags.

    Returns:
        Tuple of (success, old_status, error_msg)
    """
    if validate and not is_valid_transition(old_status, new_status):
        error_msg = (
            f"Invalid status transition for '{changespec_name}': "
            f"'{old_status}' -> '{new_status}'. "
            f"Allowed transitions from '{old_status}': "
            f"{VALID_TRANSITIONS.get(old_status, [])}"
        )
        logger.error(error_msg)
        return (False, old_status, error_msg)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = (
        f"[{timestamp}] Transitioning {changespec_name}: "
        f"'{old_status}' -> '{new_status}'"
    )
    if not validate:
        log_msg += " (validation skipped)"
    logger.info(log_msg)

    updated_content = apply_status_update(lines, changespec_name, new_status)
    write_changespec_atomic(
        project_file,
        updated_content,
        f"Update STATUS to {new_status} for {changespec_name}",
    )
    return (True, old_status, None)


def handle_reverted_transition(
    project_file: str,
    changespec_name: str,
    old_status: str,
    new_status: str,
    lines: list[str],
    validate: bool,
) -> tuple[bool, str | None, str | None]:
    """Handle transition to Reverted status.

    Returns:
        Tuple of (success, old_status, error_msg)
    """
    if validate and not is_valid_transition(old_status, new_status):
        error_msg = (
            f"Invalid status transition for '{changespec_name}': "
            f"'{old_status}' -> '{new_status}'. "
            f"Allowed transitions from '{old_status}': "
            f"{VALID_TRANSITIONS.get(old_status, [])}"
        )
        logger.error(error_msg)
        return (False, old_status, error_msg)

    # Perform transition to Reverted
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = (
        f"[{timestamp}] Transitioning {changespec_name}: "
        f"'{old_status}' -> '{new_status}'"
    )
    if not validate:
        log_msg += " (validation skipped)"
    logger.info(log_msg)

    updated_content = apply_status_update(lines, changespec_name, new_status)
    write_changespec_atomic(
        project_file,
        updated_content,
        f"Update STATUS to {new_status} for {changespec_name}",
    )
    return (True, old_status, None)


def handle_archived_transition(
    project_file: str,
    changespec_name: str,
    old_status: str,
    new_status: str,
    lines: list[str],
    validate: bool,
) -> tuple[bool, str | None, str | None]:
    """Handle transition to Archived status.

    Returns:
        Tuple of (success, old_status, error_msg)
    """
    if validate and not is_valid_transition(old_status, new_status):
        error_msg = (
            f"Invalid status transition for '{changespec_name}': "
            f"'{old_status}' -> '{new_status}'. "
            f"Allowed transitions from '{old_status}': "
            f"{VALID_TRANSITIONS.get(old_status, [])}"
        )
        logger.error(error_msg)
        return (False, old_status, error_msg)

    # Perform transition to Archived
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = (
        f"[{timestamp}] Transitioning {changespec_name}: "
        f"'{old_status}' -> '{new_status}'"
    )
    if not validate:
        log_msg += " (validation skipped)"
    logger.info(log_msg)

    updated_content = apply_status_update(lines, changespec_name, new_status)
    write_changespec_atomic(
        project_file,
        updated_content,
        f"Update STATUS to {new_status} for {changespec_name}",
    )
    return (True, old_status, None)

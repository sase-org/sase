"""Transition status handler for spec write operations."""

import logging
from datetime import datetime

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse
from sase.status_state_machine.constants import VALID_TRANSITIONS, is_valid_transition
from sase.status_state_machine.field_updates import (
    apply_status_update,
    read_status_from_lines,
)

logger = logging.getLogger(__name__)


def handle_transition_status(request: SpecWriteRequest) -> SpecWriteResponse:
    """Handle a composite status transition operation.

    Performs the lock-held phase: read current status, validate the transition,
    apply the status update, and write. Returns structured data describing
    what post-lock operations the client should perform.

    Params:
        changespec_name: Name of the ChangeSpec
        new_status: Target status value
        validate: Whether to validate the transition (default True)

    Result dict on success:
        old_status: Previous status value
        suffix_strip_info: [suffixed_name, base_name] or None
        suffix_append_info: [base_name, suffixed_name] or None
        mentor_op: "set_draft" | "clear_draft" | None
    """
    changespec_name = request.params["changespec_name"]
    new_status = request.params["new_status"]
    validate = request.params.get("validate", True)

    suffix_strip_info: list[str] | None = None
    suffix_append_info: list[str] | None = None
    mentor_op: str | None = None

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        old_status = read_status_from_lines(lines, changespec_name)

        if old_status is None:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error=f"ChangeSpec '{changespec_name}' not found in {request.project_file}",
            )

        if new_status == "Draft" and old_status == "WIP":
            # WIP → Draft: simple status change, no suffix/mentor
            error = _validate_transition(
                changespec_name, old_status, new_status, validate
            )
            if error:
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=error,
                    result={"old_status": old_status},
                )

        elif new_status == "Draft" and old_status == "Ready":
            # Ready → Draft: children constraint, append suffix, set mentor
            from sase.ace.changespec import find_all_changespecs
            from sase.sase_utils import get_next_suffix_number

            all_changespecs = find_all_changespecs()

            # Check children constraint
            invalid_children = [
                cs
                for cs in all_changespecs
                if cs.parent == changespec_name
                and cs.status not in ("WIP", "Draft", "Reverted")
            ]
            if invalid_children:
                child_info = ", ".join(
                    f"{cs.name} ({cs.status})" for cs in invalid_children
                )
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=(
                        f"Cannot transition '{changespec_name}' to Draft: "
                        f"children must be WIP, Draft, or Reverted. "
                        f"Invalid children: {child_info}"
                    ),
                    result={"old_status": old_status},
                )

            error = _validate_transition(
                changespec_name, old_status, new_status, validate
            )
            if error:
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=error,
                    result={"old_status": old_status},
                )

            existing_names = {cs.name for cs in all_changespecs}
            suffix_num = get_next_suffix_number(changespec_name, existing_names)
            suffix_append_info = [
                changespec_name,
                f"{changespec_name}_{suffix_num}",
            ]
            mentor_op = "set_draft"

        elif new_status == "Ready":
            # Any → Ready: parent constraint, sibling check, strip suffix
            error = _check_parent_constraint(
                request.project_file, changespec_name, new_status
            )
            if error:
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=error,
                    result={"old_status": old_status},
                )

            error = _validate_transition(
                changespec_name, old_status, new_status, validate
            )
            if error:
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=error,
                    result={"old_status": old_status},
                )

            # Check siblings for unreverted children if suffixed
            if old_status in ("WIP", "Draft"):
                from sase.sase_utils import has_suffix, strip_reverted_suffix

                if has_suffix(changespec_name):
                    base_name = strip_reverted_suffix(changespec_name)
                    from sase.status_state_machine.transitions import (
                        check_siblings_for_unreverted_children,
                    )

                    sibling_error = check_siblings_for_unreverted_children(
                        request.project_file, base_name, changespec_name
                    )
                    if sibling_error:
                        return SpecWriteResponse(
                            request_id=request.request_id,
                            success=False,
                            error=sibling_error,
                            result={"old_status": old_status},
                        )

            # Compute suffix_strip_info
            if old_status in ("Draft", "WIP"):
                from sase.sase_utils import has_suffix, strip_reverted_suffix

                if has_suffix(changespec_name):
                    suffix_strip_info = [
                        changespec_name,
                        strip_reverted_suffix(changespec_name),
                    ]

            if old_status == "Draft":
                mentor_op = "clear_draft"

        elif new_status in ("Reverted", "Archived"):
            # Simple validation + write
            error = _validate_transition(
                changespec_name, old_status, new_status, validate
            )
            if error:
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=error,
                    result={"old_status": old_status},
                )

        else:
            # Mailed, Submitted, etc.: parent constraint + validation
            error = _check_parent_constraint(
                request.project_file, changespec_name, new_status
            )
            if error:
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=error,
                    result={"old_status": old_status},
                )

            error = _validate_transition(
                changespec_name, old_status, new_status, validate
            )
            if error:
                return SpecWriteResponse(
                    request_id=request.request_id,
                    success=False,
                    error=error,
                    result={"old_status": old_status},
                )

        # Apply status update and write
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
            request.project_file,
            updated_content,
            f"Update STATUS to {new_status} for {changespec_name}",
        )

    return SpecWriteResponse(
        request_id=request.request_id,
        success=True,
        result={
            "old_status": old_status,
            "suffix_strip_info": suffix_strip_info,
            "suffix_append_info": suffix_append_info,
            "mentor_op": mentor_op,
        },
    )


def _validate_transition(
    changespec_name: str,
    old_status: str,
    new_status: str,
    validate: bool,
) -> str | None:
    """Validate a status transition. Returns error message or None."""
    if validate and not is_valid_transition(old_status, new_status):
        return (
            f"Invalid status transition for '{changespec_name}': "
            f"'{old_status}' -> '{new_status}'. "
            f"Allowed transitions from '{old_status}': "
            f"{VALID_TRANSITIONS.get(old_status, [])}"
        )
    return None


def _check_parent_constraint(
    project_file: str,
    changespec_name: str,
    new_status: str,
) -> str | None:
    """Check parent constraint for non-WIP/Draft/Reverted transitions."""
    from sase.ace.changespec import parse_project_file

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
            return (
                f"Cannot transition '{changespec_name}' to {new_status}: "
                f"parent '{current_cs.parent}' is {parent_cs.status}. "
                f"Children of WIP/Draft ChangeSpecs must be WIP, Draft, or Reverted."
            )
    return None

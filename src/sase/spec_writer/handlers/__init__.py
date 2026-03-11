"""Handler dispatch for spec write operations."""

import logging
from collections.abc import Callable

from sase.spec_writer.models import (
    OperationType,
    SpecWriteRequest,
    SpecWriteResponse,
)

logger = logging.getLogger(__name__)

HandlerFn = Callable[[SpecWriteRequest], SpecWriteResponse]

HANDLER_REGISTRY: dict[OperationType, HandlerFn] = {}


def _register_handlers() -> None:
    """Lazily populate the registry on first use."""
    if HANDLER_REGISTRY:
        return
    from sase.spec_writer.handlers.commits import (
        handle_add_commit_entry,
        handle_add_proposed_commit_entry,
        handle_reject_all_new_proposals,
        handle_reject_proposals_and_set_status,
        handle_update_commit_entry_suffix,
    )
    from sase.spec_writer.handlers.fields import (
        handle_set_cl,
        handle_set_description,
        handle_set_name,
        handle_set_parent,
        handle_set_status,
        handle_update_parent_references,
    )
    from sase.spec_writer.handlers.hooks import (
        handle_add_hook,
        handle_clear_hook_suffix,
        handle_merge_hooks,
        handle_rerun_delete_hooks,
        handle_set_hook_suffix,
        handle_set_hooks,
        handle_try_claim_hook_for_fix,
        handle_update_hook_suffix_type,
    )
    from sase.spec_writer.handlers.comments import (
        handle_add_comment,
        handle_remove_comment,
        handle_set_comments,
    )
    from sase.spec_writer.handlers.mentors import (
        handle_add_mentor_entry,
        handle_clear_mentor_status_lines,
        handle_set_mentor_status,
        handle_set_mentors,
    )
    from sase.spec_writer.handlers.running import (
        handle_claim_workspace,
        handle_release_workspace,
        handle_update_running_cl_name,
    )
    from sase.spec_writer.handlers.file_ops import (
        handle_add_changespec,
        handle_create_project_file,
        handle_mark_proposal_broken,
        handle_rename_changespec,
        handle_set_bare_repo_dir,
        handle_set_workspace_dir,
    )
    from sase.spec_writer.handlers.renumber import (
        handle_renumber_commit_entries,
        handle_rewind_commit_entries,
    )
    from sase.spec_writer.handlers.transitions import handle_transition_status

    HANDLER_REGISTRY.update(
        {
            OperationType.SET_STATUS: handle_set_status,
            OperationType.SET_CL: handle_set_cl,
            OperationType.SET_PARENT: handle_set_parent,
            OperationType.SET_DESCRIPTION: handle_set_description,
            OperationType.SET_NAME: handle_set_name,
            OperationType.UPDATE_PARENT_REFERENCES: handle_update_parent_references,
            OperationType.SET_HOOKS: handle_set_hooks,
            OperationType.MERGE_HOOKS: handle_merge_hooks,
            OperationType.ADD_HOOK: handle_add_hook,
            OperationType.SET_HOOK_SUFFIX: handle_set_hook_suffix,
            OperationType.CLEAR_HOOK_SUFFIX: handle_clear_hook_suffix,
            OperationType.UPDATE_HOOK_SUFFIX_TYPE: handle_update_hook_suffix_type,
            OperationType.RERUN_DELETE_HOOKS: handle_rerun_delete_hooks,
            OperationType.TRY_CLAIM_HOOK_FOR_FIX: handle_try_claim_hook_for_fix,
            OperationType.ADD_COMMIT_ENTRY: handle_add_commit_entry,
            OperationType.ADD_PROPOSED_COMMIT_ENTRY: handle_add_proposed_commit_entry,
            OperationType.REJECT_PROPOSALS_AND_SET_STATUS: handle_reject_proposals_and_set_status,
            OperationType.REJECT_ALL_NEW_PROPOSALS: handle_reject_all_new_proposals,
            OperationType.UPDATE_COMMIT_ENTRY_SUFFIX: handle_update_commit_entry_suffix,
            OperationType.SET_COMMENTS: handle_set_comments,
            OperationType.ADD_COMMENT: handle_add_comment,
            OperationType.REMOVE_COMMENT: handle_remove_comment,
            OperationType.SET_MENTORS: handle_set_mentors,
            OperationType.ADD_MENTOR_ENTRY: handle_add_mentor_entry,
            OperationType.SET_MENTOR_STATUS: handle_set_mentor_status,
            OperationType.CLEAR_MENTOR_STATUS_LINES: handle_clear_mentor_status_lines,
            OperationType.CLAIM_WORKSPACE: handle_claim_workspace,
            OperationType.RELEASE_WORKSPACE: handle_release_workspace,
            OperationType.UPDATE_RUNNING_CL_NAME: handle_update_running_cl_name,
            OperationType.ADD_CHANGESPEC: handle_add_changespec,
            OperationType.CREATE_PROJECT_FILE: handle_create_project_file,
            OperationType.SET_WORKSPACE_DIR: handle_set_workspace_dir,
            OperationType.SET_BARE_REPO_DIR: handle_set_bare_repo_dir,
            OperationType.RENAME_CHANGESPEC: handle_rename_changespec,
            OperationType.MARK_PROPOSAL_BROKEN: handle_mark_proposal_broken,
            OperationType.RENUMBER_COMMIT_ENTRIES: handle_renumber_commit_entries,
            OperationType.REWIND_COMMIT_ENTRIES: handle_rewind_commit_entries,
            OperationType.TRANSITION_STATUS: handle_transition_status,
        }
    )


def dispatch(request: SpecWriteRequest) -> SpecWriteResponse:
    """Look up and call the handler for a request's operation type."""
    _register_handlers()
    handler = HANDLER_REGISTRY.get(request.operation)
    if handler is None:
        return SpecWriteResponse(
            request_id=request.request_id,
            success=False,
            error=f"No handler for operation: {request.operation}",
        )
    try:
        return handler(request)
    except Exception as e:
        logger.exception("Handler error for %s", request.operation)
        return SpecWriteResponse(
            request_id=request.request_id,
            success=False,
            error=str(e),
        )

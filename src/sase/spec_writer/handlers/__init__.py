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

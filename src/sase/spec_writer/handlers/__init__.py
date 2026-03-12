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
    from sase.spec_writer.handlers.fields import (
        handle_set_cl,
        handle_set_description,
        handle_set_name,
        handle_set_parent,
        handle_set_status,
        handle_update_parent_references,
    )

    HANDLER_REGISTRY.update(
        {
            OperationType.SET_STATUS: handle_set_status,
            OperationType.SET_CL: handle_set_cl,
            OperationType.SET_PARENT: handle_set_parent,
            OperationType.SET_DESCRIPTION: handle_set_description,
            OperationType.SET_NAME: handle_set_name,
            OperationType.UPDATE_PARENT_REFERENCES: handle_update_parent_references,
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

"""Shared durable-operation request/result contracts."""

from .cli import (
    add_operation_io_flags,
    emit_operation_result,
    finish_operation,
    load_request,
    resolve_proc_id,
    resolve_request_path,
    resolve_result_path,
)
from .errors import DurableSubmitError, OperationIOError
from .io import (
    read_operation_request,
    read_operation_result,
    write_operation_request,
    write_operation_result,
    write_private_json,
)
from .models import (
    OPERATION_ENV,
    OPERATION_SCHEMA_VERSION,
    PROC_ID_ENV,
    REQUEST_ENV,
    RESULT_ENV,
    SUPPORTED_OPERATION_SCHEMA_VERSIONS,
    DurableOperationRequest,
    DurableOperationResult,
)

__all__ = [
    "OPERATION_ENV",
    "OPERATION_SCHEMA_VERSION",
    "PROC_ID_ENV",
    "REQUEST_ENV",
    "RESULT_ENV",
    "SUPPORTED_OPERATION_SCHEMA_VERSIONS",
    "DurableOperationRequest",
    "DurableOperationResult",
    "DurableSubmitError",
    "OperationIOError",
    "add_operation_io_flags",
    "emit_operation_result",
    "finish_operation",
    "load_request",
    "read_operation_request",
    "read_operation_result",
    "resolve_proc_id",
    "resolve_request_path",
    "resolve_result_path",
    "write_operation_request",
    "write_operation_result",
    "write_private_json",
]

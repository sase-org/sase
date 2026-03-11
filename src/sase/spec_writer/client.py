"""Client API for submitting spec write requests."""

import time
import uuid
from datetime import UTC, datetime

from sase.spec_writer.models import (
    OperationType,
    SpecWriteRequest,
    SpecWriteResponse,
    WriteMode,
)
from sase.spec_writer.queue import (
    delete_response,
    enqueue_request,
    ensure_queue_dirs,
    find_pending_by_idempotency_key,
    has_completed_key,
    read_response,
)


def make_request(
    project_file: str,
    operation: OperationType,
    params: dict,
    idempotency_key: str | None = None,
) -> SpecWriteRequest:
    """Create a SpecWriteRequest with auto-filled metadata."""
    return SpecWriteRequest(
        request_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        project_file=project_file,
        operation=operation,
        params=params,
        idempotency_key=idempotency_key,
    )


def submit_spec_write(request: SpecWriteRequest) -> None:
    """Submit a request asynchronously (fire-and-forget).

    If an idempotency key is set and already completed or pending, skips enqueue.
    """
    ensure_queue_dirs()
    request.mode = WriteMode.ASYNC

    if request.idempotency_key:
        if has_completed_key(request.idempotency_key):
            return
        if find_pending_by_idempotency_key(request.idempotency_key) is not None:
            return

    enqueue_request(request)


def submit_spec_write_and_wait(
    request: SpecWriteRequest, timeout: float = 10.0
) -> SpecWriteResponse:
    """Submit a request synchronously and wait for the response.

    Polls with exponential backoff (10ms -> 100ms cap).

    Raises:
        TimeoutError: If no response within timeout seconds.
    """
    ensure_queue_dirs()
    request.mode = WriteMode.SYNC

    if request.idempotency_key:
        if has_completed_key(request.idempotency_key):
            return SpecWriteResponse(
                request_id=request.request_id, success=True, duplicate=True
            )
        if find_pending_by_idempotency_key(request.idempotency_key) is not None:
            return SpecWriteResponse(
                request_id=request.request_id, success=True, duplicate=True
            )

    enqueue_request(request)

    delay = 0.01
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        resp = read_response(request.request_id)
        if resp is not None:
            delete_response(request.request_id)
            return resp
        time.sleep(delay)
        delay = min(delay * 2, 0.1)

    raise TimeoutError(f"No response for request {request.request_id} after {timeout}s")


def has_pending_or_completed(idempotency_key: str) -> bool:
    """Check if a request with this idempotency key is pending or already completed."""
    if has_completed_key(idempotency_key):
        return True
    return find_pending_by_idempotency_key(idempotency_key) is not None

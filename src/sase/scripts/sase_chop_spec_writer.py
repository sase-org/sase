"""Spec writer chop script — processes queued project spec file write requests."""

import argparse
import logging

from sase.axe.chop_script_context import read_chop_context
from sase.spec_writer.handlers import dispatch
from sase.spec_writer.models import WriteMode
from sase.spec_writer.queue import (
    cleanup_stale,
    delete_request,
    dequeue_pending,
    ensure_queue_dirs,
    has_completed_key,
    reap_completed_keys,
    write_completed_key,
    write_response,
)

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    read_chop_context(args.context)

    ensure_queue_dirs()
    reap_completed_keys()

    pending = dequeue_pending()
    if not pending:
        cleanup_stale()
        return

    # Dedup pass: skip requests whose idempotency key is already completed
    to_process = []
    for req in pending:
        if req.idempotency_key and has_completed_key(req.idempotency_key):
            if req.mode == WriteMode.SYNC:
                from sase.spec_writer.models import SpecWriteResponse

                write_response(
                    SpecWriteResponse(
                        request_id=req.request_id, success=True, duplicate=True
                    )
                )
            delete_request(req.request_id)
        else:
            to_process.append(req)

    # Group by project_file, sort each group by timestamp
    groups: dict[str, list] = {}
    for req in to_process:
        groups.setdefault(req.project_file, []).append(req)
    for group in groups.values():
        group.sort(key=lambda r: r.timestamp)

    # Process sequentially within each group
    for _project_file, group in groups.items():
        for req in group:
            response = dispatch(req)
            if req.mode == WriteMode.SYNC:
                write_response(response)
            if req.idempotency_key:
                write_completed_key(req.idempotency_key)
            delete_request(req.request_id)

    cleanup_stale()


if __name__ == "__main__":
    main()

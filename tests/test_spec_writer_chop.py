"""Integration tests for the spec writer chop script."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.spec_writer.handlers import dispatch
from sase.spec_writer.models import (
    OperationType,
    SpecWriteRequest,
    WriteMode,
)
from sase.spec_writer.queue import (
    delete_request,
    dequeue_pending,
    enqueue_request,
    has_completed_key,
    read_response,
    write_completed_key,
)

GP_CONTENT = """\
NAME: my-change
DESCRIPTION:
  A description.
PARENT: parent-change
CL: 12345
STATUS: OPEN
"""


@pytest.fixture(autouse=True)
def _patch_queue_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.spec_writer.queue._get_requests_dir",
        lambda: tmp_path / "requests",
    )
    monkeypatch.setattr(
        "sase.spec_writer.queue._get_responses_dir",
        lambda: tmp_path / "responses",
    )
    monkeypatch.setattr(
        "sase.spec_writer.queue._get_completed_keys_dir",
        lambda: tmp_path / "completed_keys",
    )
    (tmp_path / "requests").mkdir()
    (tmp_path / "responses").mkdir()
    (tmp_path / "completed_keys").mkdir()


def _make_gp_file(content: str = GP_CONTENT) -> str:
    fd, path = tempfile.mkstemp(suffix=".gp")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestEndToEnd:
    def test_enqueue_process_verify(self, mock_commit: object) -> None:
        """Full cycle: enqueue a sync request, process it, check response."""
        gp_path = _make_gp_file()
        try:
            req = SpecWriteRequest(
                request_id="e2e-1",
                timestamp="2024-01-01T00:00:00",
                project_file=gp_path,
                operation=OperationType.SET_STATUS,
                params={"changespec_name": "my-change", "new_status": "CLOSED"},
                mode=WriteMode.SYNC,
                idempotency_key="idem-e2e-1",
            )
            enqueue_request(req)

            # Simulate chop processing
            pending = dequeue_pending()
            assert len(pending) == 1
            for r in pending:
                response = dispatch(r)
                if r.mode == WriteMode.SYNC:
                    from sase.spec_writer.queue import write_response

                    write_response(response)
                if r.idempotency_key:
                    write_completed_key(r.idempotency_key)
                delete_request(r.request_id)

            # Verify response
            resp = read_response("e2e-1")
            assert resp is not None
            assert resp.success is True

            # Verify idempotency key recorded
            assert has_completed_key("idem-e2e-1")

            # Verify request cleaned up
            assert dequeue_pending() == []

            # Verify file was actually updated
            with open(gp_path) as f:
                content = f.read()
            assert "STATUS: CLOSED" in content
        finally:
            os.unlink(gp_path)

    def test_async_no_response_written(self, mock_commit: object) -> None:
        """Async requests should not produce response files."""
        gp_path = _make_gp_file()
        try:
            req = SpecWriteRequest(
                request_id="e2e-async",
                timestamp="2024-01-01T00:00:00",
                project_file=gp_path,
                operation=OperationType.SET_STATUS,
                params={"changespec_name": "my-change", "new_status": "CLOSED"},
                mode=WriteMode.ASYNC,
            )
            enqueue_request(req)

            pending = dequeue_pending()
            for r in pending:
                response = dispatch(r)
                if r.mode == WriteMode.SYNC:
                    from sase.spec_writer.queue import write_response

                    write_response(response)
                delete_request(r.request_id)

            assert read_response("e2e-async") is None
        finally:
            os.unlink(gp_path)

    def test_multiple_ops_same_file(self, mock_commit: object) -> None:
        """Multiple operations on the same file are processed in order."""
        gp_path = _make_gp_file()
        try:
            req1 = SpecWriteRequest(
                request_id="multi-1",
                timestamp="2024-01-01T00:00:01",
                project_file=gp_path,
                operation=OperationType.SET_STATUS,
                params={"changespec_name": "my-change", "new_status": "CLOSED"},
                mode=WriteMode.ASYNC,
            )
            req2 = SpecWriteRequest(
                request_id="multi-2",
                timestamp="2024-01-01T00:00:02",
                project_file=gp_path,
                operation=OperationType.SET_CL,
                params={"changespec_name": "my-change", "new_cl": "99999"},
                mode=WriteMode.ASYNC,
            )
            enqueue_request(req1)
            enqueue_request(req2)

            pending = dequeue_pending()
            assert len(pending) == 2
            # Process in timestamp order
            pending.sort(key=lambda r: r.timestamp)
            for r in pending:
                dispatch(r)
                delete_request(r.request_id)

            with open(gp_path) as f:
                content = f.read()
            assert "STATUS: CLOSED" in content
            assert "CL: 99999" in content
        finally:
            os.unlink(gp_path)

    def test_idempotency_dedup(self, mock_commit: object) -> None:
        """Duplicate idempotency keys get deduped."""
        gp_path = _make_gp_file()
        try:
            write_completed_key("already-done")
            req = SpecWriteRequest(
                request_id="dedup-1",
                timestamp="2024-01-01T00:00:00",
                project_file=gp_path,
                operation=OperationType.SET_STATUS,
                params={"changespec_name": "my-change", "new_status": "CLOSED"},
                mode=WriteMode.SYNC,
                idempotency_key="already-done",
            )
            enqueue_request(req)

            # Simulate dedup pass from chop script
            pending = dequeue_pending()
            for r in pending:
                if r.idempotency_key and has_completed_key(r.idempotency_key):
                    from sase.spec_writer.models import SpecWriteResponse
                    from sase.spec_writer.queue import write_response

                    if r.mode == WriteMode.SYNC:
                        write_response(
                            SpecWriteResponse(
                                request_id=r.request_id,
                                success=True,
                                duplicate=True,
                            )
                        )
                    delete_request(r.request_id)

            resp = read_response("dedup-1")
            assert resp is not None
            assert resp.duplicate is True

            # File should NOT have been modified
            with open(gp_path) as f:
                content = f.read()
            assert "STATUS: OPEN" in content
        finally:
            os.unlink(gp_path)

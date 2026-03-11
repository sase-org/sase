"""Tests for sase.spec_writer.client."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.spec_writer.client import (
    has_pending_or_completed,
    make_request,
    submit_spec_write,
    submit_spec_write_and_wait,
)
from sase.spec_writer.models import (
    OperationType,
    SpecWriteResponse,
    WriteMode,
)


class TestMakeRequest:
    def test_fills_metadata(self) -> None:
        req = make_request(
            project_file="/tmp/test.gp",
            operation=OperationType.SET_STATUS,
            params={"changespec_name": "foo", "new_status": "OPEN"},
        )
        assert req.request_id
        assert req.timestamp
        assert req.project_file == "/tmp/test.gp"
        assert req.operation == OperationType.SET_STATUS
        assert req.params == {"changespec_name": "foo", "new_status": "OPEN"}

    def test_accepts_idempotency_key(self) -> None:
        req = make_request(
            project_file="/tmp/test.gp",
            operation=OperationType.SET_CL,
            params={},
            idempotency_key="my-key",
        )
        assert req.idempotency_key == "my-key"


class TestSubmitSpecWrite:
    @patch("sase.spec_writer.client.enqueue_request")
    @patch("sase.spec_writer.client.ensure_queue_dirs")
    def test_async_enqueues(self, mock_ensure: object, mock_enqueue: object) -> None:
        req = make_request("/tmp/test.gp", OperationType.SET_STATUS, {"a": "b"})
        submit_spec_write(req)
        assert req.mode == WriteMode.ASYNC
        mock_enqueue.assert_called_once_with(req)  # type: ignore[union-attr]

    @patch("sase.spec_writer.client.enqueue_request")
    @patch("sase.spec_writer.client.ensure_queue_dirs")
    @patch("sase.spec_writer.client.has_completed_key", return_value=True)
    def test_skips_completed_idempotency(
        self, mock_has: object, mock_ensure: object, mock_enqueue: object
    ) -> None:
        req = make_request(
            "/tmp/test.gp", OperationType.SET_STATUS, {}, idempotency_key="done"
        )
        submit_spec_write(req)
        mock_enqueue.assert_not_called()  # type: ignore[union-attr]

    @patch("sase.spec_writer.client.enqueue_request")
    @patch("sase.spec_writer.client.ensure_queue_dirs")
    @patch("sase.spec_writer.client.has_completed_key", return_value=False)
    @patch(
        "sase.spec_writer.client.find_pending_by_idempotency_key",
        return_value="existing",
    )
    def test_skips_pending_idempotency(
        self,
        mock_find: object,
        mock_has: object,
        mock_ensure: object,
        mock_enqueue: object,
    ) -> None:
        req = make_request(
            "/tmp/test.gp", OperationType.SET_STATUS, {}, idempotency_key="pending"
        )
        submit_spec_write(req)
        mock_enqueue.assert_not_called()  # type: ignore[union-attr]


class TestSubmitSpecWriteAndWait:
    @patch("sase.spec_writer.client.delete_response")
    @patch(
        "sase.spec_writer.client.read_response",
        return_value=SpecWriteResponse(request_id="r1", success=True),
    )
    @patch("sase.spec_writer.client.enqueue_request")
    @patch("sase.spec_writer.client.ensure_queue_dirs")
    def test_returns_response(
        self,
        mock_ensure: object,
        mock_enqueue: object,
        mock_read: object,
        mock_delete: object,
    ) -> None:
        req = make_request("/tmp/test.gp", OperationType.SET_STATUS, {"a": "b"})
        req.request_id = "r1"
        resp = submit_spec_write_and_wait(req, timeout=1.0)
        assert resp.success is True
        assert req.mode == WriteMode.SYNC

    @patch(
        "sase.spec_writer.client.read_response",
        return_value=None,
    )
    @patch("sase.spec_writer.client.enqueue_request")
    @patch("sase.spec_writer.client.ensure_queue_dirs")
    def test_timeout(
        self,
        mock_ensure: object,
        mock_enqueue: object,
        mock_read: object,
    ) -> None:
        req = make_request("/tmp/test.gp", OperationType.SET_STATUS, {"a": "b"})
        with pytest.raises(TimeoutError):
            submit_spec_write_and_wait(req, timeout=0.05)

    @patch("sase.spec_writer.client.ensure_queue_dirs")
    @patch("sase.spec_writer.client.has_completed_key", return_value=True)
    def test_duplicate_returns_immediately(
        self, mock_has: object, mock_ensure: object
    ) -> None:
        req = make_request(
            "/tmp/test.gp", OperationType.SET_STATUS, {}, idempotency_key="done"
        )
        resp = submit_spec_write_and_wait(req, timeout=1.0)
        assert resp.success is True
        assert resp.duplicate is True


class TestHasPendingOrCompleted:
    @patch("sase.spec_writer.client.has_completed_key", return_value=True)
    def test_completed(self, mock_has: object) -> None:
        assert has_pending_or_completed("key1") is True

    @patch("sase.spec_writer.client.has_completed_key", return_value=False)
    @patch(
        "sase.spec_writer.client.find_pending_by_idempotency_key",
        return_value="something",
    )
    def test_pending(self, mock_find: object, mock_has: object) -> None:
        assert has_pending_or_completed("key1") is True

    @patch("sase.spec_writer.client.has_completed_key", return_value=False)
    @patch("sase.spec_writer.client.find_pending_by_idempotency_key", return_value=None)
    def test_neither(self, mock_find: object, mock_has: object) -> None:
        assert has_pending_or_completed("key1") is False

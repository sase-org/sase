"""Tests for sase.spec_writer.queue."""

import time
from pathlib import Path

import pytest

from sase.spec_writer.models import OperationType, SpecWriteRequest, SpecWriteResponse
from sase.spec_writer.queue import (
    cleanup_stale,
    delete_request,
    delete_response,
    dequeue_pending,
    enqueue_request,
    find_pending_by_idempotency_key,
    has_completed_key,
    read_response,
    reap_completed_keys,
    write_completed_key,
    write_response,
)


@pytest.fixture(autouse=True)
def _patch_queue_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all queue dirs to a temp directory."""
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


def _make_request(**kwargs: object) -> SpecWriteRequest:
    defaults: dict = {
        "project_file": "/tmp/test.gp",
        "operation": OperationType.SET_STATUS,
        "params": {"changespec_name": "foo", "new_status": "OPEN"},
    }
    defaults.update(kwargs)
    return SpecWriteRequest(**defaults)


class TestEnqueueDequeue:
    def test_enqueue_creates_file(self, tmp_path: Path) -> None:
        req = _make_request()
        path = enqueue_request(req)
        assert path.exists()
        assert path.name == f"{req.request_id}.json"

    def test_dequeue_returns_all_sorted(self) -> None:
        r1 = _make_request(request_id="r1", timestamp="2024-01-01T00:00:01")
        r2 = _make_request(request_id="r2", timestamp="2024-01-01T00:00:00")
        enqueue_request(r1)
        enqueue_request(r2)
        pending = dequeue_pending()
        assert len(pending) == 2
        assert pending[0].request_id == "r2"  # earlier timestamp first
        assert pending[1].request_id == "r1"

    def test_dequeue_empty(self) -> None:
        assert dequeue_pending() == []

    def test_delete_request(self) -> None:
        req = _make_request()
        enqueue_request(req)
        delete_request(req.request_id)
        assert dequeue_pending() == []


class TestResponseReadWrite:
    def test_write_and_read(self) -> None:
        resp = SpecWriteResponse(request_id="r1", success=True)
        write_response(resp)
        loaded = read_response("r1")
        assert loaded is not None
        assert loaded.request_id == "r1"
        assert loaded.success is True

    def test_read_missing(self) -> None:
        assert read_response("nonexistent") is None

    def test_delete_response(self) -> None:
        resp = SpecWriteResponse(request_id="r1", success=True)
        write_response(resp)
        delete_response("r1")
        assert read_response("r1") is None


class TestIdempotencyKeys:
    def test_write_and_check(self) -> None:
        assert not has_completed_key("key1")
        write_completed_key("key1")
        assert has_completed_key("key1")

    def test_find_pending_by_key(self) -> None:
        req = _make_request(idempotency_key="idem-1")
        enqueue_request(req)
        found = find_pending_by_idempotency_key("idem-1")
        assert found is not None
        assert found.request_id == req.request_id

    def test_find_pending_not_found(self) -> None:
        assert find_pending_by_idempotency_key("missing") is None


class TestReaping:
    def test_reap_expired_keys(self, tmp_path: Path) -> None:
        write_completed_key("old-key")
        # Backdate the key file
        key_files = list((tmp_path / "completed_keys").glob("*.key"))
        assert len(key_files) == 1
        key_files[0].write_text(str(time.time() - 200))

        removed = reap_completed_keys(ttl=120.0)
        assert removed == 1
        assert not has_completed_key("old-key")

    def test_reap_keeps_fresh_keys(self) -> None:
        write_completed_key("fresh-key")
        removed = reap_completed_keys(ttl=120.0)
        assert removed == 0
        assert has_completed_key("fresh-key")


class TestCleanupStale:
    def test_cleanup_old_requests(self, tmp_path: Path) -> None:
        req = _make_request()
        path = enqueue_request(req)
        # Backdate mtime
        old_time = time.time() - 120
        import os

        os.utime(str(path), (old_time, old_time))

        cleanup_stale(request_ttl=60.0, response_ttl=120.0)
        assert dequeue_pending() == []

    def test_cleanup_keeps_fresh(self) -> None:
        req = _make_request()
        enqueue_request(req)
        cleanup_stale(request_ttl=60.0, response_ttl=120.0)
        assert len(dequeue_pending()) == 1

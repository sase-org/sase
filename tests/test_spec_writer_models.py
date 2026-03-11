"""Tests for sase.spec_writer.models."""

from sase.spec_writer.models import (
    OperationType,
    SpecWriteRequest,
    SpecWriteResponse,
    WriteMode,
)


class TestOperationType:
    def test_enum_values(self) -> None:
        assert OperationType.SET_STATUS == "SET_STATUS"
        assert OperationType.SET_CL == "SET_CL"
        assert OperationType.SET_PARENT == "SET_PARENT"
        assert OperationType.SET_DESCRIPTION == "SET_DESCRIPTION"
        assert OperationType.SET_NAME == "SET_NAME"
        assert OperationType.UPDATE_PARENT_REFERENCES == "UPDATE_PARENT_REFERENCES"

    def test_all_members(self) -> None:
        assert len(OperationType) == 19


class TestWriteMode:
    def test_enum_values(self) -> None:
        assert WriteMode.SYNC == "SYNC"
        assert WriteMode.ASYNC == "ASYNC"


class TestSpecWriteRequest:
    def test_defaults(self) -> None:
        req = SpecWriteRequest(
            project_file="/tmp/test.gp",
            operation=OperationType.SET_STATUS,
            params={"changespec_name": "foo", "new_status": "OPEN"},
        )
        assert req.request_id  # auto-generated uuid
        assert req.timestamp  # auto-generated
        assert req.mode == WriteMode.ASYNC
        assert req.idempotency_key is None
        assert req.caller_pid > 0

    def test_to_dict_from_dict_roundtrip(self) -> None:
        req = SpecWriteRequest(
            request_id="test-id-123",
            timestamp="2024-01-01T00:00:00+00:00",
            project_file="/tmp/test.gp",
            operation=OperationType.SET_CL,
            params={"changespec_name": "bar", "new_cl": "12345"},
            mode=WriteMode.SYNC,
            idempotency_key="idem-key-1",
            caller_pid=42,
        )
        d = req.to_dict()
        assert d["operation"] == "SET_CL"
        assert d["mode"] == "SYNC"

        restored = SpecWriteRequest.from_dict(d)
        assert restored.request_id == req.request_id
        assert restored.operation == OperationType.SET_CL
        assert restored.mode == WriteMode.SYNC
        assert restored.params == req.params
        assert restored.idempotency_key == "idem-key-1"
        assert restored.caller_pid == 42

    def test_from_dict_converts_string_enums(self) -> None:
        d = {
            "request_id": "r1",
            "timestamp": "t1",
            "project_file": "/f",
            "operation": "SET_NAME",
            "params": {},
            "mode": "ASYNC",
            "idempotency_key": None,
            "caller_pid": 1,
        }
        req = SpecWriteRequest.from_dict(d)
        assert isinstance(req.operation, OperationType)
        assert isinstance(req.mode, WriteMode)


class TestSpecWriteResponse:
    def test_defaults(self) -> None:
        resp = SpecWriteResponse(request_id="r1", success=True)
        assert resp.duplicate is False
        assert resp.error is None
        assert resp.result is None

    def test_to_dict_from_dict_roundtrip(self) -> None:
        resp = SpecWriteResponse(
            request_id="r1",
            success=False,
            duplicate=True,
            error="something broke",
            result={"detail": "info"},
        )
        d = resp.to_dict()
        restored = SpecWriteResponse.from_dict(d)
        assert restored.request_id == "r1"
        assert restored.success is False
        assert restored.duplicate is True
        assert restored.error == "something broke"
        assert restored.result == {"detail": "info"}

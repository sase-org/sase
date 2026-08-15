"""Request/result sidecar I/O, permissions, and validation."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from sase.ops import (
    DurableOperationRequest,
    DurableOperationResult,
    OperationIOError,
    read_operation_request,
    read_operation_result,
    write_operation_request,
    write_operation_result,
)


def test_request_result_round_trip_is_mode_0600(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(operation="patch.status", payload={"name": "foo"}),
    )
    write_operation_result(
        result_path,
        DurableOperationResult(
            operation="patch.status",
            proc_id="proc-1",
            success=True,
            message="ok",
            payload={"status": "Ready"},
        ),
    )

    loaded_request = read_operation_request(
        request_path, expected_operation="patch.status"
    )
    loaded_result = read_operation_result(
        result_path, expected_operation="patch.status", expected_proc_id="proc-1"
    )

    assert loaded_request.payload == {"name": "foo"}
    assert loaded_result.payload == {"status": "Ready"}
    assert stat.S_IMODE(request_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert stat.S_ISREG(request_path.stat().st_mode)


def test_unsupported_schema_and_invalid_json_are_explicit(tmp_path: Path) -> None:
    bad_schema = tmp_path / "schema.json"
    write_operation_request(
        bad_schema,
        DurableOperationRequest(operation="patch.status", payload={}),
    )
    payload = json.loads(bad_schema.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    bad_schema.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(bad_schema, 0o600)
    with pytest.raises(OperationIOError, match="schema_version") as exc:
        read_operation_request(bad_schema)
    assert exc.value.kind == "unsupported_schema"

    malformed = tmp_path / "partial.json"
    fd = os.open(malformed, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, b'{"operation": "patch.status",')
    os.close(fd)
    with pytest.raises(OperationIOError, match="valid JSON") as exc:
        read_operation_request(malformed)
    assert exc.value.kind == "malformed"

    array_file = tmp_path / "array.json"
    fd = os.open(array_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, b"[1, 2]")
    os.close(fd)
    with pytest.raises(OperationIOError, match="JSON object") as exc:
        read_operation_request(array_file)
    assert exc.value.kind == "malformed"


def test_operation_and_proc_mismatches_and_missing_files(tmp_path: Path) -> None:
    missing = tmp_path / "gone.json"
    with pytest.raises(OperationIOError, match="missing") as exc:
        read_operation_result(missing)
    assert exc.value.kind == "missing"

    result_path = tmp_path / "result.json"
    write_operation_result(
        result_path,
        DurableOperationResult(
            operation="patch.status",
            proc_id="proc-1",
            success=True,
            message="ok",
        ),
    )
    with pytest.raises(OperationIOError, match="expected 'patch.revert'") as exc:
        read_operation_result(result_path, expected_operation="patch.revert")
    assert exc.value.kind == "mismatched"
    with pytest.raises(OperationIOError, match="expected 'proc-2'") as exc:
        read_operation_result(result_path, expected_proc_id="proc-2")
    assert exc.value.kind == "mismatched"


def test_wrong_permissions_and_non_regular_files(tmp_path: Path) -> None:
    path = tmp_path / "loose.json"
    write_operation_request(
        path, DurableOperationRequest(operation="patch.status", payload={})
    )
    os.chmod(path, 0o644)
    with pytest.raises(OperationIOError, match="mode 0600") as exc:
        read_operation_request(path)
    assert exc.value.kind == "permission"

    directory = tmp_path / "dir"
    directory.mkdir()
    with pytest.raises(OperationIOError, match="regular file") as exc:
        read_operation_request(directory)
    assert exc.value.kind == "not_regular"

"""Notify durable-operation command tests.

Split from ``test_ops_commands``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.main.notify_handler import handle_notify_command
from sase.main.parser import create_parser
from sase.ops import (
    DurableOperationRequest,
    read_operation_result,
    write_operation_request,
)
from sase.ops.commands.notify import handle_notify_operation


def test_notify_apply_state_success_and_failure(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr("sase.notifications.store.mark_read", lambda _id: True)
    result_path = tmp_path / "notify.json"
    args = create_parser().parse_args(
        ["notify", "apply-state", "n-1", "read", "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-notify")
    assert handle_notify_operation(args) == 0
    loaded = read_operation_result(
        result_path,
        expected_operation="notify.apply-state",
        expected_proc_id="proc-notify",
    )
    assert loaded.success is True

    monkeypatch.setattr("sase.notifications.store.mark_dismissed", lambda _id: False)
    fail_path = tmp_path / "notify-fail.json"
    fail_args = create_parser().parse_args(
        ["notify", "apply-state", "missing", "dismiss", "-R", str(fail_path)]
    )
    assert handle_notify_operation(fail_args) == 1
    failed = read_operation_result(
        fail_path,
        expected_operation="notify.apply-state",
        expected_proc_id="proc-notify",
    )
    assert failed.success is False


def test_notify_apply_state_undismiss_reaches_store(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Parser plus apply-state dispatch must run the undismiss transition."""
    monkeypatch.setattr("sase.notifications.store.mark_undismissed", lambda _id: True)
    result_path = tmp_path / "notify-undismiss.json"
    args = create_parser().parse_args(
        ["notify", "apply-state", "n-1", "undismiss", "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-notify-undismiss")
    assert handle_notify_operation(args) == 0
    loaded = read_operation_result(
        result_path,
        expected_operation="notify.apply-state",
        expected_proc_id="proc-notify-undismiss",
    )
    assert loaded.success is True
    assert loaded.payload is not None
    assert loaded.payload["action"] == "undismiss"


def test_notify_apply_state_many_undismiss_reaches_bulk_store(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Parser plus apply-state-many dispatch must run the bulk undismiss."""
    marked: list[str] = []

    def fake_mark_many_undismissed(ids: object) -> int:
        assert isinstance(ids, tuple)
        marked.extend(ids)
        return len(ids)

    monkeypatch.setattr(
        "sase.notifications.store.mark_many_undismissed", fake_mark_many_undismissed
    )
    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="notify.apply-state",
            payload={"ids": ["n1", "n2"]},
        ),
    )
    args = create_parser().parse_args(
        [
            "notify",
            "apply-state-many",
            "undismiss",
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-notify-many-undismiss")
    assert handle_notify_operation(args) == 0
    assert marked == ["n1", "n2"]
    loaded = read_operation_result(
        result_path,
        expected_operation="notify.apply-state",
        expected_proc_id="proc-notify-many-undismiss",
    )
    assert loaded.success is True
    assert loaded.payload is not None
    assert loaded.payload["action"] == "undismiss"
    assert loaded.payload["matched_count"] == 2


def test_notify_apply_state_many_read_reaches_tab_scoped_store(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Parser plus top-level notify dispatch must run tab-scoped bulk reads."""
    marked: list[str] = []

    def fake_mark_tab_read(tab_key: str) -> int:
        marked.append(tab_key)
        return 3

    monkeypatch.setattr("sase.notifications.store.mark_tab_read", fake_mark_tab_read)
    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="notify.apply-state",
            payload={"ids": ["n1"], "tab_key": "alpha"},
        ),
    )
    args = create_parser().parse_args(
        [
            "notify",
            "apply-state-many",
            "read",
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-notify-many")
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(args)
    assert excinfo.value.code == 0
    assert marked == ["alpha"]
    loaded = read_operation_result(
        result_path,
        expected_operation="notify.apply-state",
        expected_proc_id="proc-notify-many",
    )
    assert loaded.success is True
    assert loaded.payload is not None
    assert loaded.payload["action"] == "read"
    assert loaded.payload["ids"] == ["n1"]
    assert loaded.payload["matched_count"] == 3

"""Patch/bead status and typed-result helper tests.

Split from ``test_ops_commands``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.main.parser import create_parser
from sase.ops import (
    RESULT_ENV,
    read_operation_result,
)
from sase.ops.commands.bead import handle_bead_operation
from sase.ops.commands.monitor import emit_monitor_stop_result
from sase.ops.commands.patch import handle_patch_operation
from sase.ops.commands.plugin import emit_plugin_install_result
from sase.ops.commands.proc import emit_proc_kill_result
from sase.ops.commands.run import emit_run_launch_result


def test_patch_status_success_and_failure_results(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.ops.commands.patch._project_file",
        lambda _args: str(tmp_path / "proj.sase"),
    )

    def fake_transition(*_a: Any, **_k: Any) -> tuple[bool, str, str | None, list[Any]]:
        return True, "Draft", None, []

    monkeypatch.setattr(
        "sase.core.status_facade.transition_patch_status", fake_transition
    )
    result_path = tmp_path / "ok.json"
    args = create_parser().parse_args(
        ["patch", "status", "demo", "Ready", "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-status")
    assert handle_patch_operation(args) == 0
    loaded = read_operation_result(
        result_path, expected_operation="patch.status", expected_proc_id="proc-status"
    )
    assert loaded.success is True
    assert loaded.payload is not None
    assert loaded.payload["status"] == "Ready"

    def fail_transition(*_a: Any, **_k: Any) -> tuple[bool, None, str, list[Any]]:
        return False, None, "blocked by parent", []

    monkeypatch.setattr(
        "sase.core.status_facade.transition_patch_status", fail_transition
    )
    fail_path = tmp_path / "fail.json"
    fail_args = create_parser().parse_args(
        ["patch", "status", "demo", "Ready", "-R", str(fail_path)]
    )
    assert handle_patch_operation(fail_args) == 1
    failed = read_operation_result(
        fail_path, expected_operation="patch.status", expected_proc_id="proc-status"
    )
    assert failed.success is False
    assert "blocked" in failed.message


def test_bead_apply_status_success_and_failure(
    monkeypatch: Any, tmp_path: Path
) -> None:
    class _Project:
        def update(self, bead_id: str, **fields: str) -> SimpleNamespace:
            return SimpleNamespace(id=bead_id, status=fields["status"])

    class _Mutation:
        def __init__(self) -> None:
            self.project = _Project()
            self.committed: list[str] = []

        def commit(self, message: str) -> None:
            self.committed.append(message)

        def __enter__(self) -> _Mutation:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(
        "sase.bead.cli_common.bead_store_mutation", lambda *_a, **_k: _Mutation()
    )
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_bead_operation_context",
        lambda targets, **_kwargs: SimpleNamespace(resolved_ids=tuple(targets)),
    )
    result_path = tmp_path / "bead.json"
    args = create_parser().parse_args(
        ["bead", "apply-status", "sase-ab", "closed", "-R", str(result_path)]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-bead")
    assert handle_bead_operation(args) == 0
    loaded = read_operation_result(
        result_path, expected_operation="bead.status", expected_proc_id="proc-bead"
    )
    assert loaded.success is True
    assert loaded.payload == {"bead_id": "sase-ab", "status": "closed"}


def test_plugin_monitor_and_run_result_helpers(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_PROC_ID", "proc-family")
    plugin_path = tmp_path / "plugin.json"
    monkeypatch.setenv(RESULT_ENV, str(plugin_path))
    emit_plugin_install_result(
        success=True, message="installed github", payload={"plugin": "github"}
    )
    assert read_operation_result(
        plugin_path, expected_operation="plugin.install", expected_proc_id="proc-family"
    ).success

    monitor_path = tmp_path / "monitor.json"
    monkeypatch.setenv(RESULT_ENV, str(monitor_path))
    emit_monitor_stop_result(
        success=False, message="not found", payload={"monitor_id": "m1"}
    )
    assert (
        read_operation_result(
            monitor_path,
            expected_operation="monitor.stop",
            expected_proc_id="proc-family",
        ).success
        is False
    )

    proc_path = tmp_path / "proc.json"
    monkeypatch.setenv(RESULT_ENV, str(proc_path))
    emit_proc_kill_result(
        success=True,
        message="killed proc",
        payload={"proc_id": "abc123", "changed": True},
    )
    assert read_operation_result(
        proc_path,
        expected_operation="proc.kill",
        expected_proc_id="proc-family",
    ).payload == {"proc_id": "abc123", "changed": True}

    run_path = tmp_path / "run.json"
    monkeypatch.setenv(RESULT_ENV, str(run_path))
    emit_run_launch_result(success=True, message="started", payload={"count": 1})
    assert read_operation_result(
        run_path, expected_operation="run.launch", expected_proc_id="proc-family"
    ).payload == {"count": 1}

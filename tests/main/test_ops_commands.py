"""Parser help and typed results for durable domain commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.main.notify_handler import handle_notify_command
from sase.main.parser import create_parser
from sase.ops import (
    DurableOperationRequest,
    RESULT_ENV,
    read_operation_result,
    write_operation_request,
)
from sase.ops.commands.agent import handle_agent_operation
from sase.ops.commands.notify import handle_notify_operation
from sase.ops.commands.patch import handle_patch_operation
from tests.main.parser_help_helpers import (
    assert_metavar_option_documented,
    flat_help,
    help_subcommand_rows,
    parser_for,
)


def test_patch_help_lists_operation_commands_sorted() -> None:
    patch_parser = parser_for(("sase", "patch"))
    expected = {
        "accept",
        "archive",
        "current",
        "mail",
        "migrate-extension",
        "rebase",
        "ref",
        "restore",
        "revert",
        "rewind",
        "reword",
        "search",
        "set-origin",
        "status",
        "submit",
        "sync",
        "sync-deltas",
        "sync-external",
        "tag",
    }
    assert help_subcommand_rows(patch_parser.format_help(), expected) == sorted(
        expected
    )
    status_help = flat_help(parser_for(("sase", "patch", "status")).format_help())
    assert_metavar_option_documented(
        status_help, "-p", "--project-file", "PROJECT_FILE"
    )
    assert (
        "-Q, --request-path" in status_help
        or "-Q PATH, --request-path PATH" in status_help
    )


def test_notify_and_agent_operation_help() -> None:
    notify_help = parser_for(("sase", "notify")).format_help()
    assert help_subcommand_rows(
        notify_help,
        {"apply-state", "apply-state-many", "create", "list", "show"},
    ) == ["apply-state", "apply-state-many", "create", "list", "show"]
    agent_help = parser_for(("sase", "agent", "persist-directive")).format_help()
    assert "artifacts directory" in agent_help.lower() or "artifacts_dir" in agent_help
    assert "-Q" in agent_help and "--request-path" in agent_help
    cleanup_help = parser_for(("sase", "agent", "persist-cleanup")).format_help()
    assert "-Q" in cleanup_help and "--request-path" in cleanup_help


def test_bead_apply_status_help_is_documented() -> None:
    help_text = parser_for(("sase", "bead", "apply-status")).format_help()
    assert "bead id" in help_text.lower() or "BEAD_ID" in help_text
    assert "-R" in help_text and "--result-path" in help_text


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


def test_agent_persist_directive_uses_request_sidecar(
    monkeypatch: Any, tmp_path: Path
) -> None:
    request_path = tmp_path / "req.json"
    result_path = tmp_path / "res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.persist-directive",
            payload={"meta_set": {"agent_name": "renamed"}},
        ),
    )
    captured: dict[str, Any] = {}

    def fake_persist(spec: Any) -> Any:
        captured["artifacts_dir"] = str(spec.artifacts_dir)
        captured["meta"] = spec.meta_patch
        return SimpleNamespace(
            meta_updated=True,
            ready_updated=False,
            tribe_updated=False,
            waiting_updated=False,
        )

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._directive_persistence.persist_agent_directive_update",
        fake_persist,
    )
    args = create_parser().parse_args(
        [
            "agent",
            "persist-directive",
            str(tmp_path / "artifacts"),
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-agent")
    assert handle_agent_operation(args) == 0
    assert captured["artifacts_dir"].endswith("artifacts")
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.persist-directive",
        expected_proc_id="proc-agent",
    )
    assert loaded.success is True


def test_agent_persist_directive_applies_prompt_mutation(
    monkeypatch: Any, tmp_path: Path
) -> None:
    request_path = tmp_path / "req-prompt.json"
    result_path = tmp_path / "res-prompt.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.persist-directive",
            payload={
                "meta_set": {"name": "renamed"},
                "prompt": {"kind": "set_name", "name": "renamed"},
            },
        ),
    )
    captured: dict[str, Any] = {}

    def fake_persist(spec: Any) -> Any:
        captured["prompt"] = spec.prompt_mutator
        return SimpleNamespace(
            meta_updated=True,
            ready_updated=False,
            tribe_updated=False,
            waiting_updated=False,
        )

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._directive_persistence.persist_agent_directive_update",
        fake_persist,
    )
    args = create_parser().parse_args(
        [
            "agent",
            "persist-directive",
            str(tmp_path / "artifacts"),
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-agent-prompt")
    assert handle_agent_operation(args) == 0
    assert captured["prompt"] is not None
    assert captured["prompt"]("%id(old)") != "%id(old)"


def test_agent_persist_cleanup_applies_json_identities(
    monkeypatch: Any, tmp_path: Path
) -> None:
    request_path = tmp_path / "cleanup-req.json"
    result_path = tmp_path / "cleanup-res.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="agent.cleanup",
            payload={
                "action": "dismiss",
                "dismissed_identities": [["run", "feature", "20240101120000"]],
                "message": "Dismissed feature",
                "refresh_notifications": True,
            },
        ),
    )
    saved: list[Any] = []

    def fake_save(snapshot: Any) -> bool:
        saved.append(snapshot)
        return True

    monkeypatch.setattr("sase.ace.dismissed_agents.save_dismissed_agents", fake_save)
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.sync_dismissed_agent_artifact_index",
        lambda *_a, **_k: None,
    )
    args = create_parser().parse_args(
        [
            "agent",
            "persist-cleanup",
            "-Q",
            str(request_path),
            "-R",
            str(result_path),
        ]
    )
    monkeypatch.setenv("SASE_PROC_ID", "proc-cleanup")
    assert handle_agent_operation(args) == 0
    assert saved
    identity = next(iter(saved[0]))
    assert identity[0].value == "run"
    assert identity[1] == "feature"
    loaded = read_operation_result(
        result_path,
        expected_operation="agent.cleanup",
        expected_proc_id="proc-cleanup",
    )
    assert loaded.success is True
    assert loaded.payload is not None
    assert loaded.payload["action"] == "dismiss"


def test_bead_apply_status_success_and_failure(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from sase.ops.commands.bead import handle_bead_operation

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
    from sase.ops.commands.monitor import emit_monitor_stop_result
    from sase.ops.commands.plugin import emit_plugin_install_result
    from sase.ops.commands.proc import emit_proc_kill_result
    from sase.ops.commands.run import emit_run_launch_result

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

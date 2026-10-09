"""Agent persist-directive/cleanup operation tests.

Split from ``test_ops_commands``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.main.parser import create_parser
from sase.ops import (
    DurableOperationRequest,
    read_operation_result,
    write_operation_request,
)
from sase.ops.commands.agent import handle_agent_operation


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

    def fake_add(identities: Any) -> set[Any]:
        saved.append(set(identities))
        return set(identities)

    monkeypatch.setattr("sase.ace.dismissed_agents.add_dismissed_agents", fake_add)
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

"""Continuation-aware fork replay tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.continuation_capture import persist_monitor_result
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.history.chat import build_fork_injected_history

_SHA = "a" * 64


def _write_agent_node(
    artifacts_dir: Path,
    *,
    name: str,
    node_id: str,
    parents: Sequence[str] = (),
    prompt: str,
    response: str | None,
) -> None:
    root = artifacts_dir / "continuation"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    final_response_ref = None
    if response is not None:
        final_response_ref = _write_text_blob(root, response)

    delta: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "authored_local_request": prompt,
        "materialized_local_prompt_segments": [],
        "source_refs": [],
        "status": "completed",
    }
    if final_response_ref:
        delta["final_response_ref"] = final_response_ref
    delta_ref = f"local:continuation/records/agent_delta/{node_id}.json"
    delta_sha = _write_json(root / "records" / "agent_delta" / f"{node_id}.json", delta)

    node = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": "agent_delta",
        "parent_ids": list(parents),
        "owner": {
            "project": "proj",
            "run_id": artifacts_dir.name,
            "agent_name": name,
        },
        "content_ref": delta_ref,
        "content_sha256": delta_sha,
    }
    node_ref = f"local:continuation/nodes/{node_id}.json"
    node_sha = _write_json(root / "nodes" / f"{node_id}.json", node)

    manifest = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "local_continuation_capture",
        "node_id": node_id,
        "agent_delta_ref": delta_ref,
        "agent_delta_sha256": delta_sha,
        "node_ref": node_ref,
        "node_sha256": node_sha,
    }
    manifest_path = root / "manifest.json"
    _write_json(manifest_path, manifest)
    meta = {
        "name": name,
        "continuation_node_id": node_id,
        "continuation_node_ref": node_ref,
        "continuation_manifest_path": str(manifest_path),
        "continuation_manifest_ref": "local:continuation/manifest.json",
        "continuation_parent_node_ids": list(parents),
    }
    _write_json(artifacts_dir / "agent_meta.json", meta)


def _agent_member(
    tmp_path: Path,
    suffix: str,
    name: str,
) -> dict[str, object]:
    chat = tmp_path / f"{suffix}.md"
    chat.write_text("legacy transcript should not be parsed\n", encoding="utf-8")
    return {
        "kind": "agent",
        "name": name,
        "path": str(chat),
        "artifact_dir": str(tmp_path / "artifacts" / suffix),
        "outcome": "completed",
    }


def _monitor_member(
    artifacts_dir: Path,
    *,
    name: str = "acme--mon",
    log_tail: str = "SECRET_MONITOR_TAIL\n",
    next_output: str = "tail",
    status: str = "failed",
    exit_code: int | None = 7,
) -> dict[str, object]:
    return {
        "kind": "proc",
        "name": name,
        "artifact_dir": str(artifacts_dir),
        "outcome": status,
        "proc": {
            "proc_id": "mon123",
            "is_monitor": True,
            "terminal": True,
            "failed": status != "completed",
            "shell_name": name,
            "command": "just check",
            "cwd": "/workspace/acme",
            "project": "proj",
            "started_at": "2026-09-11T10:00:00Z",
            "finished_at": "2026-09-11T10:01:00Z",
            "status": status,
            "exit_code": exit_code,
            "timeout_seconds": 120.0,
            "elapsed_seconds": 60.0,
            "log_path": "/tmp/monitor.log",
            "log_tail": log_tail,
            "log_truncated": False,
            "monitor_next_output": next_output,
        },
    }


def _write_monitor_result_node(
    artifacts_dir: Path,
    *,
    parents: Sequence[str] = (),
    next_output: str = "tail",
    status: str = "failed",
    exit_code: int | None = 7,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "name": "acme--mon",
        "monitor_id": "mon123",
        "monitor_command": "just check",
        "monitor_cwd": "/workspace/acme",
        "monitor_next_output": next_output,
        "monitor_state": status,
        "run_started_at": "2026-09-11T10:00:00Z",
        "workspace_dir": "/workspace/acme",
        "workspace_num": 1,
        "continuation_parent_node_ids": list(parents),
        "continuation_intent_ref": "local:continuation/intents/intent.json",
        "continuation_checkpoint_ref": "local:continuation/checkpoints/start.json",
        "monitor_diagnostic_manifest_ref": "file:explicit:diagnostics",
        "monitor_retained_log_ref": "file:explicit:monitor-log",
    }
    persist_monitor_result(
        artifacts_dir=artifacts_dir,
        meta=meta,
        monitor_state=status,
        exit_code=exit_code,
        elapsed_seconds=60.0,
        stopped_at="2026-09-11T10:01:00Z",
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:monitor-log",
            "local_locator": "/tmp/monitor.log",
            "total_observed_bytes": len("SECRET_MONITOR_TAIL\n"),
            "retained_ranges": [
                {"start": 0, "end": len("SECRET_MONITOR_TAIL\n")},
            ],
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=False,
    )
    _write_json(artifacts_dir / "agent_meta.json", meta)


def _write_text_blob(root: Path, text: str) -> str:
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    path = root / "text" / f"{digest}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"local:continuation/text/{digest}.txt"


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    data = _json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def test_versioned_family_replay_deduplicates_shared_parent(tmp_path: Path) -> None:
    base = tmp_path / "artifacts" / "20260911010101"
    child = tmp_path / "artifacts" / "20260911010202"
    _write_agent_node(
        base,
        name="acme--0",
        node_id="agent-delta-base",
        prompt="Keep base constraints.",
        response="BASE_REPLY",
    )
    _write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-base"],
        prompt="Continue from the base.",
        response="CHILD_REPLY",
    )
    source = {
        "kind": "family",
        "name": "acme",
        "members": [
            _agent_member(tmp_path, "20260911010101", "acme--0"),
            _agent_member(tmp_path, "20260911010202", "acme--1"),
        ],
        "excluded": [],
    }

    rendered = build_fork_injected_history([source])

    assert "# Previous Continuation" in rendered
    assert rendered.count("BASE_REPLY") == 1
    assert rendered.count("CHILD_REPLY") == 1
    assert "Continuation Block `block:v1:" in rendered
    assert "Member 1 of 2" not in rendered


def test_versioned_replay_keeps_hundred_turn_chain_linear(tmp_path: Path) -> None:
    members = []
    parent: str | None = None
    for index in range(100):
        suffix = f"20260911{index:06}"
        node_id = f"agent-delta-{index:03}"
        _write_agent_node(
            tmp_path / "artifacts" / suffix,
            name=f"chain--{index}",
            node_id=node_id,
            parents=([parent] if parent else []),
            prompt=f"UNIQUE_PROMPT_{index:03}",
            response=f"UNIQUE_REPLY_{index:03}",
        )
        members.append(_agent_member(tmp_path, suffix, f"chain--{index}"))
        parent = node_id
    source = {"kind": "family", "name": "chain", "members": members, "excluded": []}

    rendered = build_fork_injected_history([source])
    replayed = build_fork_injected_history([source])

    assert rendered == replayed
    assert rendered.count("UNIQUE_REPLY_") == 100
    assert rendered.count("Continuation Block `block:v1:") == 100
    assert len(rendered.encode("utf-8")) < 200_000


def test_versioned_monitor_result_does_not_reinject_raw_tail(tmp_path: Path) -> None:
    starter = tmp_path / "artifacts" / "20260911010101"
    monitor = tmp_path / "artifacts" / "20260911010202"
    _write_agent_node(
        starter,
        name="acme--0",
        node_id="agent-delta-starter",
        prompt="Run the verification monitor.",
        response="STARTER_REPLY",
    )
    _write_json(
        monitor / "agent_meta.json",
        {
            "name": "acme--mon",
            "continuation_parent_node_ids": ["agent-delta-starter"],
            "continuation_intent_ref": "local:continuation/intents/intent.json",
            "continuation_checkpoint_ref": "local:continuation/checkpoints/start.json",
            "monitor_next_output": "none",
        },
    )
    direct = _monitor_member(
        monitor, next_output="none", status="completed", exit_code=0
    )
    source = {
        "kind": "family",
        "name": "acme",
        "members": [
            _agent_member(tmp_path, "20260911010101", "acme--0"),
            direct,
        ],
        "excluded": [],
    }

    rendered = build_fork_injected_history([direct, source])

    assert "STARTER_REPLY" in rendered
    assert "Monitor Result" in rendered
    assert "SECRET_MONITOR_TAIL" not in rendered
    assert "sase monitor show mon123 --all-lines" in rendered


def test_versioned_monitor_result_tail_policy_uses_frozen_node_once(
    tmp_path: Path,
) -> None:
    starter = tmp_path / "artifacts" / "20260911010101"
    monitor = tmp_path / "artifacts" / "20260911010202"
    _write_agent_node(
        starter,
        name="acme--0",
        node_id="agent-delta-starter",
        prompt="Run the verification monitor.",
        response="STARTER_REPLY",
    )
    _write_monitor_result_node(
        monitor,
        parents=["agent-delta-starter"],
        next_output="tail",
    )
    direct = _monitor_member(monitor, next_output="tail")
    family = {
        "kind": "family",
        "name": "acme",
        "members": [
            _agent_member(tmp_path, "20260911010101", "acme--0"),
            direct,
        ],
        "excluded": [],
    }

    rendered = build_fork_injected_history([direct, family])

    assert "STARTER_REPLY" in rendered
    assert rendered.count("SECRET_MONITOR_TAIL") == 1
    assert rendered.count("mon123") >= 1


def test_versioned_replay_reports_missing_parent(tmp_path: Path) -> None:
    child = tmp_path / "artifacts" / "20260911010202"
    _write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-missing"],
        prompt="Continue from a missing source.",
        response="CHILD_REPLY",
    )
    source = _agent_member(tmp_path, "20260911010202", "acme--1")

    rendered = build_fork_injected_history([source])

    assert "`missing_parent`" in rendered
    assert "parent `agent-delta-missing`" in rendered
    assert "CHILD_REPLY" in rendered


def test_versioned_replay_keeps_uncertain_legacy_as_opaque_boundary(
    tmp_path: Path,
) -> None:
    legacy_chat = tmp_path / "legacy.md"
    legacy_chat.write_text(
        "## Prompt\n\nOld prompt\n\n## Response\n\nOLD_REPLY\n",
        encoding="utf-8",
    )
    current = tmp_path / "artifacts" / "20260911010202"
    _write_agent_node(
        current,
        name="acme--1",
        node_id="agent-delta-current",
        prompt="Continue after legacy context.",
        response="CURRENT_REPLY",
    )
    source = {
        "kind": "family",
        "name": "acme",
        "members": [
            {
                "kind": "agent",
                "name": "acme--0",
                "path": str(legacy_chat),
                "artifact_dir": str(tmp_path / "artifacts" / "20260911010101"),
                "outcome": "completed",
            },
            _agent_member(tmp_path, "20260911010202", "acme--1"),
        ],
        "excluded": [],
    }

    rendered = build_fork_injected_history([source])

    assert "Opaque Legacy Boundary" in rendered
    assert "OLD_REPLY" not in rendered
    assert "CURRENT_REPLY" in rendered

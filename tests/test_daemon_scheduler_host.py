"""Tests for the daemon scheduler Python host bridge."""

from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.launch_types import AgentLaunchResult
from sase.daemon.scheduler_host import (
    cancel_launch_slot,
    execute_launch_slot,
    handle_scheduler_host_bridge,
    prepare_launch_slot,
)
from sase.main.parser import create_parser


def _axe_slot(tmp_path: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "slot": {
            "schema_version": 1,
            "task_id": {
                "schema_version": 1,
                "batch_id": "batch-axe",
                "slot_id": "batch-axe:0",
                "queue_id": "axe",
            },
            "project_id": "proj",
            "slot_index": 0,
            "status": "queued",
            "launch_spec": {
                "schema_version": 1,
                "project_id": "proj",
                "prompt": "axe:chop:hooks:hook_checks",
                "cwd": str(tmp_path),
                "metadata": {
                    "scheduler_task_kind": "axe",
                    "axe_task": {
                        "schema_version": 1,
                        "task_kind": "chop",
                        "task_key": "hooks:hook_checks",
                        "metadata": {
                            "lumberjack_name": "hooks",
                            "chop_name": "hook_checks",
                            "source": "scheduled",
                        },
                    },
                },
            },
        },
    }


def _slot(tmp_path: Path, prompt: str = "%name:queued.demo\nDo work") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "slot": {
            "schema_version": 1,
            "task_id": {
                "schema_version": 1,
                "batch_id": "batch-a",
                "slot_id": "batch-a:0",
                "queue_id": "agents",
            },
            "project_id": "proj",
            "slot_index": 0,
            "status": "queued",
            "launch_spec": {
                "schema_version": 1,
                "project_id": "proj",
                "prompt": prompt,
                "cwd": str(tmp_path),
                "model": "codex/gpt-5.5",
                "metadata": {"agent_name": "queued.demo"},
            },
        },
    }


def test_prepare_launch_slot_validates_slot_and_shapes_host_input(
    tmp_path: Path,
) -> None:
    payload = prepare_launch_slot(_slot(tmp_path, prompt="Do work"))

    assert payload["status"] == "prepared"
    assert payload["batch_id"] == "batch-a"
    assert payload["slot_id"] == "batch-a:0"
    assert payload["launch"] == {
        "prompt": "%model:codex/gpt-5.5\nDo work",
        "cwd": str(tmp_path),
        "model": "codex/gpt-5.5",
        "parent_agent_id": None,
        "workflow_id": None,
        "metadata": {"agent_name": "queued.demo"},
        "agent_name": None,
    }


def test_execute_launch_slot_uses_existing_launch_shape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    captured: dict[str, Any] = {}

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        captured["prompt"] = prompt
        captured["cwd"] = str(Path.cwd())
        return [
            AgentLaunchResult(
                pid=123,
                workspace_num=4,
                workspace_dir="/tmp/ws4",
                output_path="/tmp/out.txt",
                project_file="/tmp/proj/proj.sase",
                project_name="proj",
                workflow_name="ace(run)-260514_010203",
                cl_name="proj",
                timestamp="260514_010203",
            )
        ]

    payload = execute_launch_slot(_slot(tmp_path), launch_fn=fake_launch)

    assert captured == {
        "prompt": "%model:codex/gpt-5.5\n%name:queued.demo\nDo work",
        "cwd": str(tmp_path),
    }
    assert payload["status"] == "launched"
    assert payload["primary"] == payload["slots"][0]
    assert payload["primary"]["pid"] == 123
    assert payload["primary"]["workspace_claim"] == {
        "workspace_num": 4,
        "workspace_dir": "/tmp/ws4",
        "project_file": "/tmp/proj/proj.sase",
        "project_name": "proj",
    }
    assert payload["primary"]["artifact_dir"].endswith(
        "/.sase/projects/proj/artifacts/ace-run/20260514010203"
    )
    assert payload["primary"]["agent_name"] == "queued.demo"


def test_execute_launch_slot_returns_typed_failure(tmp_path: Path) -> None:
    def fake_launch(_prompt: str) -> list[AgentLaunchResult]:
        raise RuntimeError("spawn failed")

    payload = execute_launch_slot(_slot(tmp_path), launch_fn=fake_launch)

    assert payload["status"] == "failed"
    assert payload["primary"] is None
    assert payload["failure"] == {
        "type": "RuntimeError",
        "message": "spawn failed",
        "retryable": False,
    }


def test_cancel_launch_slot_hands_off_to_named_agent_kill(tmp_path: Path) -> None:
    calls: list[str] = []

    @dataclass
    class Kill:
        status: str = "killed"
        pid: int = 456
        changed: bool = True
        message: str = "Killed agent 'queued.demo' (PID 456)"

    payload = cancel_launch_slot(
        _slot(tmp_path),
        kill_fn=lambda name: calls.append(name) or Kill(),
    )

    assert calls == ["queued.demo"]
    assert payload["status"] == "killed"
    assert payload["pid"] == 456
    assert payload["changed"] is True


def test_scheduler_bridge_parser_and_handler_execute_slot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.daemon.scheduler_host._default_launch_fn",
        lambda _prompt: [
            AgentLaunchResult(
                pid=789,
                workspace_num=0,
                workspace_dir=str(tmp_path),
                output_path="/tmp/out.txt",
                project_name="proj",
                timestamp="260514_010204",
            )
        ],
    )
    args = create_parser().parse_args(
        ["daemon", "scheduler-bridge", "execute-launch-slot"]
    )
    stdout = io.StringIO()

    code = handle_scheduler_host_bridge(
        args,
        stdin=io.StringIO(json.dumps(_slot(tmp_path))),
        stdout=stdout,
    )

    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["operation"] == "execute-launch-slot"
    assert payload["primary"]["pid"] == 789


def test_scheduler_bridge_parser_and_handler_execute_axe_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.axe.scheduler_tasks._execute_axe_task_payload",
        lambda task: {
            "task_kind": task["task_kind"],
            "chop_name": task["metadata"]["chop_name"],
            "status": "success",
        },
    )
    args = create_parser().parse_args(
        ["daemon", "scheduler-bridge", "execute-axe-task"]
    )
    stdout = io.StringIO()

    code = handle_scheduler_host_bridge(
        args,
        stdin=io.StringIO(json.dumps(_axe_slot(tmp_path))),
        stdout=stdout,
    )

    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["operation"] == "execute-axe-task"
    assert payload["queue_id"] == "axe"
    assert payload["result"] == {
        "task_kind": "chop",
        "chop_name": "hook_checks",
        "status": "success",
    }


def test_scheduler_bridge_parser_accepts_hidden_subcommand() -> None:
    args = create_parser().parse_args(
        ["daemon", "scheduler-bridge", "prepare-launch-slot"]
    )

    assert args.daemon_subcommand == "scheduler-bridge"
    assert args.daemon_scheduler_bridge_subcommand == "prepare-launch-slot"


def test_scheduler_bridge_parser_accepts_hidden_axe_subcommand() -> None:
    args = create_parser().parse_args(
        ["daemon", "scheduler-bridge", "prepare-axe-task"]
    )

    assert args.daemon_subcommand == "scheduler-bridge"
    assert args.daemon_scheduler_bridge_subcommand == "prepare-axe-task"

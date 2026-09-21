"""Shared helpers for gate-shell runner-slot capacity acceptance tests."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.gate_shell.member import create_gate_shell_member
from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.models import GateSpec
from sase.notification_gates.service import create_gate
from sase.plan_gate import build_plan_approval_gate_spec
from sase.plan_shell.create import plan_gate_shell_block

from tests.fakey._runner_slot_harness import _WAIT_TIMEOUT

MONITOR_PROJECT = "fakey-slots"


def dispatch_gate_answer(argv: list[str]) -> tuple[int, dict[str, object]]:
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", *argv, "--json"])
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as excinfo:
            handle_gate_command(args)
    code = int(excinfo.value.code or 0)
    payload = json.loads(out.getvalue()) if out.getvalue().strip() else {}
    return code, payload


def blocking_gate_command_script(started: Path, release: Path) -> str:
    """Return a gate-option command script that signals then blocks."""
    return (
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys, time\n"
        "json.load(sys.stdin)\n"
        f"pathlib.Path({str(started)!r}).write_text('1')\n"
        f"deadline = time.monotonic() + {_WAIT_TIMEOUT}\n"
        f"while not pathlib.Path({str(release)!r}).exists():\n"
        "    if time.monotonic() > deadline:\n"
        "        sys.exit(1)\n"
        "    time.sleep(0.01)\n"
        "print(json.dumps({'status': 'ok'}))\n"
    )


def make_blocking_gate(
    *,
    request_id: str,
    member_name: str,
    lane: str,
    started: Path,
    release: Path,
    queue_weight: float = 1.0,
    queue_weight_explicit: bool = False,
) -> tuple[Path, str]:
    """Create a real gate bundle plus its gate-shell member.

    The bundle's one option runs a command that blocks until *release*
    exists, so a test can drive real ``wait_for_runner_slot`` contention
    around the gate's execution window.
    """
    shell_block: dict[str, object] = {
        "pending_status": "GATE",
        "settled_status": "GATED",
    }
    spec: dict[str, object] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Runner-slot capacity acceptance",
            "notes": ["Exercise real runner-slot capacity contention."],
        },
        "query": "run",
        "primary_branch": ["run"],
        "options": [
            {"id": "run", "label": "Run", "command": {"argv": ["commands/run"]}}
        ],
        "resources": [
            {
                "path": "commands/run",
                "role": "command",
                "content": blocking_gate_command_script(started, release),
            }
        ],
        "shell": shell_block,
    }
    # This helper establishes the gate-shell row itself below: mark the spec
    # the way the production transaction does so the shell-row guard accepts
    # the setup.
    gate = create_gate(replace(GateSpec.from_mapping(spec), shell_row_managed=True))
    parsed_shell = GateShellSpec.from_mapping(shell_block, branches=(("run",),))
    artifacts_dir = create_gate_shell_member(
        MONITOR_PROJECT,
        {
            "name": member_name,
            "agent_family": lane,
            "model": "test",
            "queue_weight": queue_weight,
            "queue_weight_explicit": queue_weight_explicit,
        },
        lane=lane,
        suffix="--gate",
        prev_artifacts_timestamp="20260713090098",
        workspace_num=None,
        gate_id=request_id,
        gate_kind="custom",
        label="Runner-slot capacity acceptance",
        reason="wait for reviewer",
        creator_agent=member_name,
        timeout_seconds=86_400.0,
        request_fingerprint=None,
        shell=parsed_shell,
    )
    update_meta_field(artifacts_dir, "gate_bundle_path", str(gate.bundle_path))
    return gate.bundle_path, artifacts_dir


def make_plan_gate(
    *,
    request_id: str,
    member_name: str,
    lane: str,
    plan_file: Path,
) -> tuple[Path, str]:
    """Create a real shell-backed tale plan gate plus its gate-shell member."""
    spec = build_plan_approval_gate_spec(str(plan_file), request_id)
    spec["shell"] = plan_gate_shell_block("tale")
    gate = create_gate(spec)
    parsed_shell = GateShellSpec.from_mapping(
        spec["shell"],
        branches=(("approve", "commit"), ("reject",), ("feedback",)),
        allow_branch_subsets=True,
    )
    artifacts_dir = create_gate_shell_member(
        MONITOR_PROJECT,
        {
            "name": member_name,
            "agent_family": lane,
            "model": "test",
            "queue_weight": 1.0,
            "queue_weight_explicit": True,
        },
        lane=lane,
        suffix="--gate",
        prev_artifacts_timestamp="20260713090098",
        workspace_num=None,
        gate_id=request_id,
        gate_kind="plan",
        label="Plan capacity acceptance",
        reason="wait for reviewer",
        creator_agent=member_name,
        timeout_seconds=86_400.0,
        request_fingerprint=None,
        shell=parsed_shell,
    )
    update_meta_field(artifacts_dir, "gate_bundle_path", str(gate.bundle_path))
    return gate.bundle_path, artifacts_dir

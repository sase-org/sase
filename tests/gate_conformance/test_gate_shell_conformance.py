"""The shell dimension of the gate conformance matrix.

A shell-backed gate answered from every answering surface must settle its
gate shell identically: same terminal ``gate_state``, a written decision
chat, a ``gate.log`` with the executed command's live output, and the same
follow-up disposition -- whether or not the follow-up actually launches in
this sandbox. Every surface funnels through the same
:func:`~sase.notification_gates.executor.execute_gate_selection` plus
:func:`~sase.gate_shell.settlement.settle_gate_shell` pair; this test is what
would have caught the mobile bridge never calling either gate-shell hook at
all -- it answered the gate but left the shell pending forever.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.gate_shell.member import create_gate_shell_member
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.store import read_gate_shell_marker
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.service import create_gate
from tests.gate_conformance._cases import Submission
from tests.gate_conformance._surfaces import SURFACES, SurfaceTarget
from tests.monitor._fixtures import make_starter_agent, write_project_file

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)

_SHELL_BLOCK: dict[str, Any] = {
    "pending_status": "GATE",
    "settled_status": "GATED",
    "next": {
        "prompt": "Verify the cleanup landed.",
        "fork": "family",
        "output": ["results"],
    },
}


def _spec(request_id: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "conformance"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Reclaim disk space",
            "notes": ["Conformance shell dimension"],
        },
        "query": "cleanup",
        "primary_branch": ["cleanup"],
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            }
        ],
        "resources": [
            {"path": "commands/cleanup", "role": "command", "content": _ECHO_COMMAND}
        ],
        "shell": _SHELL_BLOCK,
    }


def _build_gate_shell(project: str, request_id: str) -> GateShellRecord:
    """Create a real gate bundle plus its gate-shell member, no live creator.

    Mirrors ``tests/test_gate_cli_answer_detach.py``'s ``_make_gate_shell_member``:
    the creation *transaction* (creator resolution, claim transfer) belongs to
    ``gate-shell``'s own tests; this only needs a durable member for every
    surface to answer identically.
    """
    write_project_file(project)
    creator_timestamp = "20260812120000"
    creator_dir = make_starter_agent(
        project,
        creator_timestamp,
        "lane",
        agent_family="lane",
        agent_family_role="root",
    )
    (Path(creator_dir) / "done.json").write_text("{}", encoding="utf-8")

    gate = create_gate(_spec(request_id))
    shell = GateShellSpec.from_mapping(_SHELL_BLOCK, branches=(("cleanup",),))
    artifacts_dir = create_gate_shell_member(
        project,
        {"name": "lane", "agent_family": "lane", "model": "gpt-5"},
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp=creator_timestamp,
        workspace_num=None,
        gate_id=request_id,
        gate_kind="custom",
        label="Reclaim disk space",
        reason="wait for reviewer",
        creator_agent="lane",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=shell,
    )
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    update_meta_fields(
        artifacts_dir,
        {
            "gate_bundle_path": str(gate.bundle_path),
            "gate_notification_id": gate.notification_id,
        },
    )
    record = read_gate_shell_marker(project, artifacts_dir)
    assert record is not None
    return record


def _fake_launch(**kwargs: Any) -> AgentLaunchResult:
    del kwargs
    return AgentLaunchResult(
        pid=999_999,
        workspace_num=3,
        workspace_dir="/tmp/conformance-followup",
        output_path="/tmp/conformance-followup.txt",
        agent_name="lane--code",
    )


def test_shell_gate_settles_identically_across_every_surface(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Answer the same shell gate from cli, ace, and mobile; compare outcomes."""
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.gate_shell.followup.spawn_agent_subprocess", _fake_launch)

    outcomes: dict[str, dict[str, Any]] = {}
    for surface in SURFACES:
        project = f"proj-{surface.name}"
        request_id = f"conf-shell-{surface.name}"
        record = _build_gate_shell(project, request_id)
        assert record.bundle_path is not None
        target = SurfaceTarget(
            bundle_path=Path(record.bundle_path),
            kind=record.kind,
            request_id=record.gate_id,
            notification_id=record.notification_id,
        )

        result = surface.submit(target, Submission(selected=("cleanup",)))
        assert result.answered, result.message

        meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
        log_path = Path(record.artifacts_dir) / "gate.log"
        outcomes[surface.name] = {
            "gate_state": meta.get("gate_state"),
            "chat_path_written": bool(meta.get("chat_path")),
            "gate_log_has_command_header": (
                "$ commands/cleanup" in log_path.read_text(encoding="utf-8")
                if log_path.is_file()
                else False
            ),
            "followup_outcome": meta.get("gate_followup_outcome"),
        }

    assert outcomes["cli"]["gate_state"] == "answered"
    for surface_name, outcome in outcomes.items():
        assert outcome == outcomes["cli"], (
            f"{surface_name} settled a shell gate differently than cli: {outcome} "
            f"!= {outcomes['cli']}"
        )

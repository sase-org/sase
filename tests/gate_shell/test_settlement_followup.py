"""Settlement ordering, launch wiring, and ``creator_live`` suppression."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.gate_shell.settlement as settlement_module
from sase.gate_shell.member import create_gate_shell_member
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.start_claim import GATE_WORKSPACE_CLAIM_WORKFLOW
from sase.gate_shell.store import read_gate_shell_marker
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.service import create_gate
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.shells.followup import FollowupLaunchResult

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


_DEFAULT_SHELL: dict[str, Any] = {
    "pending_status": "GATE",
    "settled_status": "GATED",
    "next": {"prompt": "Verify the cleanup landed."},
}


def _spec(request_id: str, *, shell: dict[str, Any] | None) -> dict[str, object]:
    spec: dict[str, object] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Reclaim disk space",
            "notes": ["Free up disk on the shared volume"],
        },
        "query": "cleanup OR reject",
        "primary_branch": ["cleanup"],
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            },
            {
                "id": "reject",
                "label": "Reject",
                "command": {"argv": ["commands/reject"]},
            },
        ],
        "resources": [
            {"path": "commands/cleanup", "role": "command", "content": _ECHO_COMMAND},
            {"path": "commands/reject", "role": "command", "content": _ECHO_COMMAND},
        ],
    }
    if shell is not None:
        spec["shell"] = shell
    return spec


def _make_gate_shell_member(
    request_id: str,
    bundle_path: Path,
    *,
    shell: dict[str, Any],
    workspace_num: int | None = None,
) -> str:
    """Build the gate-shell member from the *same* shell block as the bundle.

    Settlement resolves follow-up policy from the durable bundle envelope
    (the single source of truth), never from the member's own metadata, so a
    test that wants a resolvable policy must give both the same shell block.
    """
    parsed_shell = GateShellSpec.from_mapping(
        shell, branches=(("cleanup",), ("reject",))
    )
    base_meta: dict[str, Any] = {
        "name": "lane--0",
        "agent_family": "lane",
        "model": "gpt-5",
    }
    if workspace_num is not None:
        base_meta["workspace_dir"] = "/work/lane"
    artifacts_dir = create_gate_shell_member(
        "proj",
        base_meta,
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=workspace_num,
        gate_id=request_id,
        gate_kind="custom",
        label="Reclaim disk space",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=parsed_shell,
    )
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    update_meta_field(artifacts_dir, "gate_bundle_path", str(bundle_path))
    if workspace_num is not None:
        update_meta_field(artifacts_dir, "gate_workspace_policy", "inherit")
    return artifacts_dir


def _fake_launcher(
    artifacts_dir: str, meta: dict[str, Any], **kwargs: Any
) -> FollowupLaunchResult:
    """Mimic a real launcher's side effect of persisting the agent field.

    ``settle_shell_claim_and_followup`` only records the launch *outcome*
    itself -- persisting the agent name is the launcher's own job (done via
    ``record_followup_launched``), so a fake standing in for a real launcher
    must do it too, or ``gate_followup_agent`` never reaches ``meta``/disk.
    """
    del kwargs
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    meta["gate_followup_agent"] = "lane--1"
    update_meta_field(artifacts_dir, "gate_followup_agent", "lane--1")
    return FollowupLaunchResult(launched=True, agent_name="lane--1")


def test_launcher_only_runs_after_the_shell_is_terminal_and_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "reclaim-order"
    gate = create_gate(_spec(request_id, shell=_DEFAULT_SHELL))
    artifacts_dir = _make_gate_shell_member(
        request_id, gate.bundle_path, shell=_DEFAULT_SHELL
    )
    execute_gate_selection(gate.bundle_path, ["cleanup"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    observed: dict[str, Any] = {}

    def observing_launcher(
        called_artifacts_dir: str, meta: dict[str, Any], **kwargs: Any
    ) -> FollowupLaunchResult:
        del kwargs
        observed["done_exists"] = (Path(called_artifacts_dir) / "done.json").exists()
        observed["decision_exists"] = (
            Path(called_artifacts_dir) / "gate_decision.md"
        ).exists()
        on_disk = json.loads(
            (Path(called_artifacts_dir) / "agent_meta.json").read_text()
        )
        observed["gate_state"] = on_disk["gate_state"]
        observed["chat_path"] = on_disk.get("chat_path")
        return FollowupLaunchResult(launched=True, agent_name="lane--1")

    monkeypatch.setattr(
        settlement_module, "launch_gate_followup_agent", observing_launcher
    )

    settle_gate_shell(record, gate_state="answered", reason="gate answered")

    assert observed["done_exists"] is True
    assert observed["decision_exists"] is True
    assert observed["gate_state"] == "answered"
    assert observed["chat_path"]


def test_timeout_with_no_timeout_branch_launches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell: dict[str, Any] = {"next": {"prompt": "answered-only prompt"}}
    request_id = "reclaim-timeout-unmapped"
    gate = create_gate(_spec(request_id, shell=shell))
    artifacts_dir = _make_gate_shell_member(request_id, gate.bundle_path, shell=shell)
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    calls: list[str] = []
    monkeypatch.setattr(
        settlement_module,
        "launch_gate_followup_agent",
        lambda *a, **k: calls.append("called") or FollowupLaunchResult(launched=True),
    )

    settled = settle_gate_shell(record, gate_state="timeout", reason="gate timed out")

    assert settled.gate_state == "timeout"
    assert calls == []
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert "gate_next_action" not in meta


def test_timeout_with_a_timeout_branch_launches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell: dict[str, Any] = {"branches": {"timeout": {"prompt": "handle the timeout"}}}
    request_id = "reclaim-timeout-mapped"
    gate = create_gate(_spec(request_id, shell=shell))
    artifacts_dir = _make_gate_shell_member(request_id, gate.bundle_path, shell=shell)
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    calls: list[str] = []
    monkeypatch.setattr(
        settlement_module,
        "launch_gate_followup_agent",
        lambda *a, **k: (
            calls.append("called")
            or FollowupLaunchResult(launched=True, agent_name="lane--1")
        ),
    )

    settled = settle_gate_shell(record, gate_state="timeout", reason="gate timed out")

    assert settled.gate_state == "timeout"
    assert calls == ["called"]
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["gate_next_action"] == "handle the timeout"


def test_creator_live_suppresses_launch_and_stashes_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "reclaim-auto"
    gate = create_gate(_spec(request_id, shell=_DEFAULT_SHELL))
    artifacts_dir = _make_gate_shell_member(
        request_id, gate.bundle_path, shell=_DEFAULT_SHELL
    )
    execute_gate_selection(gate.bundle_path, ["cleanup"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    def failing_launcher(*args: Any, **kwargs: Any) -> FollowupLaunchResult:
        raise AssertionError("launch must not run when creator_live=True")

    monkeypatch.setattr(
        settlement_module, "launch_gate_followup_agent", failing_launcher
    )

    settled = settle_gate_shell(
        record, gate_state="answered", reason="auto-resolved", creator_live=True
    )

    assert settled.gate_state == "answered"
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["gate_followup_outcome"] == "suppressed"
    prompt_path = Path(meta["gate_followup_prompt_path"])
    assert prompt_path.exists()
    assert "Verify the cleanup landed." in prompt_path.read_text(encoding="utf-8")
    assert "gate_followup_agent" not in meta
    assert "gate_followup_error" not in meta


def test_creator_live_leaves_the_workspace_claim_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.monitor._fixtures import write_project_file

    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(3, GATE_WORKSPACE_CLAIM_WORKFLOW, "lane", pid=1234)
        ],
    )
    request_id = "reclaim-auto-claim"
    gate = create_gate(_spec(request_id, shell=_DEFAULT_SHELL))
    artifacts_dir = _make_gate_shell_member(
        request_id, gate.bundle_path, shell=_DEFAULT_SHELL, workspace_num=3
    )
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    update_meta_field(artifacts_dir, "workspace_num", 3)
    execute_gate_selection(gate.bundle_path, ["cleanup"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    def failing_launcher(*args: Any, **kwargs: Any) -> FollowupLaunchResult:
        raise AssertionError("launch must not run when creator_live=True")

    monkeypatch.setattr(
        settlement_module, "launch_gate_followup_agent", failing_launcher
    )

    settle_gate_shell(
        record, gate_state="answered", reason="auto-resolved", creator_live=True
    )

    claims = get_claimed_workspaces(project_file)
    assert any(
        claim.workspace_num == 3
        and claim.workflow == GATE_WORKSPACE_CLAIM_WORKFLOW
        and claim.pid == 1234
        for claim in claims
    )


def test_done_marker_carries_the_followup_outcome_and_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "reclaim-done"
    gate = create_gate(_spec(request_id, shell=_DEFAULT_SHELL))
    artifacts_dir = _make_gate_shell_member(
        request_id, gate.bundle_path, shell=_DEFAULT_SHELL
    )
    execute_gate_selection(gate.bundle_path, ["cleanup"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    monkeypatch.setattr(settlement_module, "launch_gate_followup_agent", _fake_launcher)

    settle_gate_shell(record, gate_state="answered", reason="gate answered")

    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["gate_followup_outcome"] == "launched"
    assert done["gate_followup_agent"] == "lane--1"

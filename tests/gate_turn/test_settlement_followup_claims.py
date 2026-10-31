"""Workspace-claim hold, restore, and release during gate-shell settlement."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import sase.gate_turn.settlement as settlement_module
from sase.gate_turn.claims import (
    GATE_WORKSPACE_CLAIM_WORKFLOW,
    gate_claim_is_releasable,
)
from sase.gate_turn.cancel import cancel_gate_turn
from sase.gate_turn.settlement import settle_gate_turn
from sase.gate_turn.store import read_gate_turn_marker
from sase.gate_turn.member import create_gate_turn_member
from sase.logs.workspace_claim_ledger import read_ledger_records
from sase.notification_gates.service import create_gate
from sase.question_gate_turn.create import _question_gate_turn_spec
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from tests.gate_turn._settlement_followup_helpers import (
    gate_spec,
    make_gate_turn_member,
    sandbox_home,
)

__all__ = ["sandbox_home"]


def _record_creator_claim_meta(
    artifacts_dir: str,
    *,
    pid: int,
    workflow: str,
    cl_name: str | None,
    artifacts_timestamp: str,
    pinned: bool = False,
) -> None:
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    update_meta_fields(
        artifacts_dir,
        {
            "gate_creator_claim_pid": pid,
            "gate_creator_claim_workflow": workflow,
            "gate_creator_claim_cl_name": cl_name,
            "gate_creator_claim_artifacts_timestamp": artifacts_timestamp,
            "gate_creator_claim_pinned": pinned,
            "cl_name": cl_name,
        },
    )


def test_settlement_holds_gate_claim_on_settling_pid_before_done_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
    from tests.monitor._fixtures import write_project_file

    creator_pid = 1234
    request_id = "reclaim-settle-hold"
    shell: dict[str, Any] = {}
    gate = create_gate(gate_spec(request_id, turn=shell))
    artifacts_dir = make_gate_turn_member(
        request_id, gate.bundle_path, turn=shell, workspace_num=3
    )
    gate_timestamp = Path(artifacts_dir).name
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                3,
                GATE_WORKSPACE_CLAIM_WORKFLOW,
                "feature",
                pid=creator_pid,
                artifacts_timestamp=gate_timestamp,
            )
        ],
    )
    _record_creator_claim_meta(
        artifacts_dir,
        pid=creator_pid,
        workflow="lane",
        cl_name="feature",
        artifacts_timestamp="20260812120000",
    )
    record = read_gate_turn_marker("proj", artifacts_dir)
    assert record is not None
    monkeypatch.setattr(
        "sase.gate_turn.start_claim.is_process_running",
        lambda _pid: False,
    )

    observed_claims: list[list[WorkspaceClaim]] = []

    def observing_done_marker(
        called_artifacts_dir: str, marker: dict[str, Any]
    ) -> None:
        observed_claims.append(get_claimed_workspaces(project_file))
        write_done_marker_and_update_index(called_artifacts_dir, marker)

    monkeypatch.setattr(
        settlement_module,
        "write_done_marker_and_update_index",
        observing_done_marker,
    )

    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
        settle_gate_turn(record, gate_state="timeout", reason="gate timed out")
        ledger = read_ledger_records(ledger_file=ledger_file)

    assert observed_claims
    first_claims = observed_claims[0]
    assert len(first_claims) == 1
    held = first_claims[0]
    assert held.workspace_num == 3
    assert held.workflow == GATE_WORKSPACE_CLAIM_WORKFLOW
    assert held.pid == os.getpid()
    assert held.artifacts_timestamp == gate_timestamp
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["gate_claim_holder_pid"] == os.getpid()
    assert any(
        entry["operation"] == "transfer"
        and entry["caller_tag"] == "gate-turn-settle-hold"
        and entry["claim_pid"] == os.getpid()
        for entry in ledger
    )


def test_dead_settlement_holder_with_terminal_marker_is_releasable(
    tmp_path: Path,
) -> None:
    from sase.axe.run_agent_helpers_artifacts import update_meta_field
    from tests.monitor._fixtures import write_project_file

    request_id = "reclaim-settle-crash"
    shell: dict[str, Any] = {}
    gate = create_gate(gate_spec(request_id, turn=shell))
    artifacts_dir = make_gate_turn_member(
        request_id, gate.bundle_path, turn=shell, workspace_num=3
    )
    update_meta_field(artifacts_dir, "gate_state", "answered")
    project_file = write_project_file("proj")
    claim = WorkspaceClaim(
        3,
        GATE_WORKSPACE_CLAIM_WORKFLOW,
        "feature",
        pid=987654,
        artifacts_timestamp=Path(artifacts_dir).name,
    )

    assert gate_claim_is_releasable(project_file, claim) is True


def test_settle_restores_original_claim_when_creator_pid_is_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.monitor._fixtures import write_project_file

    creator_pid = 1234
    creator_timestamp = "20260812120000"
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                3,
                GATE_WORKSPACE_CLAIM_WORKFLOW,
                "feature",
                pid=creator_pid,
                artifacts_timestamp="20260812120500",
            )
        ],
    )
    request_id = "reclaim-live-creator"
    shell: dict[str, Any] = {}
    gate = create_gate(gate_spec(request_id, turn=shell))
    artifacts_dir = make_gate_turn_member(
        request_id, gate.bundle_path, turn=shell, workspace_num=3
    )
    _record_creator_claim_meta(
        artifacts_dir,
        pid=creator_pid,
        workflow="lane",
        cl_name="feature",
        artifacts_timestamp=creator_timestamp,
    )
    record = read_gate_turn_marker("proj", artifacts_dir)
    assert record is not None
    monkeypatch.setattr(
        "sase.gate_turn.start_claim.is_process_running",
        lambda pid: pid == creator_pid,
    )

    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
        settle_gate_turn(record, gate_state="timeout", reason="gate timed out")
        ledger = read_ledger_records(ledger_file=ledger_file)

    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    restored = claims[0]
    assert restored.workspace_num == 3
    assert restored.workflow == "lane"
    assert restored.cl_name == "feature"
    assert restored.pid == creator_pid
    assert restored.artifacts_timestamp == creator_timestamp
    assert ledger[-1]["operation"] == "transfer"
    assert ledger[-1]["caller_tag"] == "gate-turn-settle-restore"
    assert ledger[-1]["claim_pid"] == creator_pid
    log_text = (Path(artifacts_dir) / "gate.log").read_text(encoding="utf-8")
    assert "creator pid 1234 is still alive" in log_text
    assert "restored workspace #3 claim to lane" in log_text


def test_settle_releases_gate_claim_when_creator_pid_is_dead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.monitor._fixtures import write_project_file
    from sase.axe.run_agent_helpers_artifacts import update_meta_field
    from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline

    creator_pid = 1234
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(
                3,
                GATE_WORKSPACE_CLAIM_WORKFLOW,
                "feature",
                pid=creator_pid,
                artifacts_timestamp="20260812120500",
            )
        ],
    )
    request_id = "reclaim-dead-creator"
    shell: dict[str, Any] = {}
    gate = create_gate(gate_spec(request_id, turn=shell))
    artifacts_dir = make_gate_turn_member(
        request_id, gate.bundle_path, turn=shell, workspace_num=3
    )
    checkout = tmp_path / "clean-workspace"
    checkout.mkdir()
    subprocess.run(["git", "-C", str(checkout), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.email", "test@example.com"],
        check=True,
    )
    source = checkout / "source.txt"
    source.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "source.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-qm", "baseline"], check=True
    )
    update_meta_field(artifacts_dir, "workspace_dir", str(checkout))
    parent_dir = Path(artifacts_dir).parent / "20260812120000"
    parent_dir.mkdir(parents=True, exist_ok=True)
    capture_dirty_baseline(str(checkout), str(parent_dir))
    _record_creator_claim_meta(
        artifacts_dir,
        pid=creator_pid,
        workflow="lane",
        cl_name="feature",
        artifacts_timestamp="20260812120000",
    )
    record = read_gate_turn_marker("proj", artifacts_dir)
    assert record is not None
    monkeypatch.setattr(
        "sase.gate_turn.start_claim.is_process_running",
        lambda _pid: False,
    )

    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
        settle_gate_turn(record, gate_state="timeout", reason="gate timed out")
        ledger = read_ledger_records(ledger_file=ledger_file)

    assert get_claimed_workspaces(project_file) == []
    assert ledger[-1]["operation"] == "release"
    assert ledger[-1]["caller_tag"] == "workspace-retention"
    log_path = Path(artifacts_dir) / "gate.log"
    assert not log_path.exists()


def test_cancelled_question_retains_dirty_creator_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Question cancellation settles through the shared terminal retention path."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields
    from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
    from tests.monitor._fixtures import write_project_file

    checkout = tmp_path / "workspace"
    checkout.mkdir()
    subprocess.run(["git", "-C", str(checkout), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.email", "test@example.com"],
        check=True,
    )
    source = checkout / "source.txt"
    source.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "source.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-qm", "baseline"], check=True
    )

    request = _question_gate_turn_spec(
        [{"question": "Which database?", "options": [{"label": "SQLite"}]}],
        session_id="cancelled-question-retention",
        base_prompt="Implement the feature.",
        prior_rounds=[],
    )
    request["request_id"] = "cancelled-question-retention"
    gate = create_gate(request)
    from sase.notification_gates.model_turn import GateTurnSpec

    turn = GateTurnSpec.from_mapping(request["turn"], branches=(("submit",),))
    artifacts_dir = create_gate_turn_member(
        "proj",
        {"name": "lane--0", "agent_session": "lane", "workspace_dir": str(checkout)},
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=3,
        gate_id="cancelled-question-retention",
        gate_kind="question",
        label="Question",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        turn=turn,
    )
    update_meta_fields(
        artifacts_dir,
        {"gate_bundle_path": str(gate.bundle_path), "workspace_dir": str(checkout)},
    )
    gate_meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    creator_pid = 987654
    gate_timestamp = Path(artifacts_dir).name
    parent_dir = Path(artifacts_dir).parent / str(gate_meta["parent_timestamp"])
    parent_dir.mkdir(parents=True, exist_ok=True)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(checkout), "name": "lane--0"}),
        encoding="utf-8",
    )
    capture_dirty_baseline(str(checkout), str(parent_dir))
    source.write_text("session-owned change\n", encoding="utf-8")
    update_meta_fields(
        artifacts_dir,
        {
            "gate_creator_claim_pid": creator_pid,
            "gate_creator_claim_workflow": "lane",
            "gate_creator_claim_cl_name": "feature",
            "gate_creator_claim_artifacts_timestamp": "20260812120000",
            "gate_claim_holder_pid": creator_pid,
            "cl_name": "feature",
        },
    )
    project_file = write_project_file(
        "proj",
        workspace_dir=str(checkout),
        running_claims=[
            WorkspaceClaim(
                3,
                GATE_WORKSPACE_CLAIM_WORKFLOW,
                "feature",
                pid=creator_pid,
                artifacts_timestamp=gate_timestamp,
            )
        ],
    )
    monkeypatch.setattr(
        "sase.workflows.utils.get_project_file_path",
        lambda _project_name: project_file,
    )
    monkeypatch.setattr(
        "sase.gate_turn.start_claim.is_process_running", lambda _pid: False
    )
    record = read_gate_turn_marker("proj", artifacts_dir)
    assert record is not None

    cancel_gate_turn(record)

    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1 and claims[0].pinned
    assert source.read_text(encoding="utf-8") == "session-owned change\n"
    retention = json.loads(
        (Path(artifacts_dir) / "diagnostics" / "workspace_retention.json").read_text(
            encoding="utf-8"
        )
    )
    assert retention["disposition"] == "retain"
    assert retention["affected_repo_ids"]
    assert retention["snapshot_paths"]

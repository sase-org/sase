"""Workspace-claim hold, restore, and release during gate-shell settlement."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import sase.gate_shell.settlement as settlement_module
from sase.gate_shell.claims import (
    GATE_WORKSPACE_CLAIM_WORKFLOW,
    gate_claim_is_releasable,
)
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import read_gate_shell_marker
from sase.logs.workspace_claim_ledger import read_ledger_records
from sase.notification_gates.service import create_gate
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from tests.gate_shell._settlement_followup_helpers import (
    gate_spec,
    make_gate_shell_member,
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
    gate = create_gate(gate_spec(request_id, shell=shell))
    artifacts_dir = make_gate_shell_member(
        request_id, gate.bundle_path, shell=shell, workspace_num=3
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
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    monkeypatch.setattr(
        "sase.gate_shell.start_claim.is_process_running",
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
        settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
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
        and entry["caller_tag"] == "gate-shell-settle-hold"
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
    gate = create_gate(gate_spec(request_id, shell=shell))
    artifacts_dir = make_gate_shell_member(
        request_id, gate.bundle_path, shell=shell, workspace_num=3
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
    gate = create_gate(gate_spec(request_id, shell=shell))
    artifacts_dir = make_gate_shell_member(
        request_id, gate.bundle_path, shell=shell, workspace_num=3
    )
    _record_creator_claim_meta(
        artifacts_dir,
        pid=creator_pid,
        workflow="lane",
        cl_name="feature",
        artifacts_timestamp=creator_timestamp,
    )
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    monkeypatch.setattr(
        "sase.gate_shell.start_claim.is_process_running",
        lambda pid: pid == creator_pid,
    )

    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
        settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
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
    assert ledger[-1]["caller_tag"] == "gate-shell-settle-restore"
    assert ledger[-1]["claim_pid"] == creator_pid
    log_text = (Path(artifacts_dir) / "gate.log").read_text(encoding="utf-8")
    assert "creator pid 1234 is still alive" in log_text
    assert "restored workspace #3 claim to lane" in log_text


def test_settle_releases_gate_claim_when_creator_pid_is_dead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.monitor._fixtures import write_project_file

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
    gate = create_gate(gate_spec(request_id, shell=shell))
    artifacts_dir = make_gate_shell_member(
        request_id, gate.bundle_path, shell=shell, workspace_num=3
    )
    _record_creator_claim_meta(
        artifacts_dir,
        pid=creator_pid,
        workflow="lane",
        cl_name="feature",
        artifacts_timestamp="20260812120000",
    )
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    monkeypatch.setattr(
        "sase.gate_shell.start_claim.is_process_running",
        lambda _pid: False,
    )

    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
        settle_gate_shell(record, gate_state="timeout", reason="gate timed out")
        ledger = read_ledger_records(ledger_file=ledger_file)

    assert get_claimed_workspaces(project_file) == []
    assert ledger[-1]["operation"] == "release"
    assert ledger[-1]["caller_tag"] == "gate-shell-settle"
    log_path = Path(artifacts_dir) / "gate.log"
    assert not log_path.exists()

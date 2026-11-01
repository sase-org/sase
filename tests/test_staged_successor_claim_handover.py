"""Staged successor delivery transfers only the dead origin's real claim."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import (
    acquire_adoption_lock,
    read_adoption_receipt,
    read_staged_successor,
    successor_prompt_digest,
    write_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
    write_staged_successor_locked,
    write_successor_prompt,
)
from sase.axe.run_agent_exec_staged import recover_staged_handoff
from sase.axe.run_agent_successor import deliver_staged_successor_detached
from sase.running_field import (
    claim_workspace,
    get_claimed_workspaces,
    hold_workspace_claim,
    release_workspace,
)
from sase.artifacts import convert_timestamp_to_artifacts_format
from tests.test_staged_recovery_service import STAGED_ID, _record

ORIGIN_PID = 67_890
OTHER_PID = 67_891
SUCCESSOR_PID = 67_892
WORKSPACE_NUM = 101
LAUNCH_TIMESTAMP = "261028_120001"
ARTIFACTS_TIMESTAMP = "20261028120001"


def _setup_staged_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner_pid: int = ORIGIN_PID,
    pinned: bool = False,
    attach: bool = False,
) -> dict[str, Any]:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    root = tmp_path / ".sase" / "projects"
    origin = root / "proj" / "artifacts" / "ace-run" / "20261028120000"
    origin.mkdir(parents=True)
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    child = origin.parent / ARTIFACTS_TIMESTAMP
    child.mkdir()

    project_file = tmp_path / "proj.sase"
    project_file.write_text("RUNNING:\n\nNAME: proj\nSTATUS: Ready\n", encoding="utf-8")
    claim_result = claim_workspace(
        str(project_file),
        WORKSPACE_NUM,
        "ace(run)-origin",
        owner_pid,
        cl_name="proj",
        artifacts_timestamp=origin.name,
    )
    assert claim_result.success, claim_result.error
    if pinned:
        pin_result = hold_workspace_claim(
            str(project_file),
            WORKSPACE_NUM,
            "ace(run)-origin",
            "proj",
            origin.name,
            expected_pid=owner_pid,
        )
        assert pin_result.success, pin_result.error

    stage = _record(tmp_path, "pipe")
    write_staged_handoff(stage, artifacts_dir=str(origin))
    write_staged_handoff_response(STAGED_ID, "continue", artifacts_dir=str(origin))
    (origin / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "origin-agent",
                "pid": ORIGIN_PID,
                "process_identity": {"start_ticks": 1},
                "cl_name": "proj",
                "workspace_dir": str(workspace_dir),
                "workspace_num": WORKSPACE_NUM,
                "finalizer_status": {
                    "phase": "settled",
                    "status": "success",
                    "run_id": "controller-run-1",
                    "plan_digest": "digest-1",
                    "started_at": "2026-10-28T12:01:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    (origin / "finalizer_result.json").write_text(
        json.dumps({"status": "success", "instances": []}), encoding="utf-8"
    )

    prompt = write_successor_prompt(origin, "continue the original task")
    launch_id = f"{STAGED_ID}:{ARTIFACTS_TIMESTAMP}"
    attach_plan = None
    if attach:
        attach_plan = {
            "parent_arg": "origin-agent",
            "suffix_arg": "--1",
            "parent_name": "origin-agent",
            "parent_base": "origin-agent",
            "parent_timestamp": origin.name,
            "parent_artifacts_dir": str(origin),
            "role_suffix": "--1",
            "agent_name": "origin-agent--1",
            "agent_session_role": "worker",
            "parent_agent_session_member_name": "origin-agent",
            "parent_agent_session_role_suffix": "--0",
            "parent_needs_rename": False,
            "parent_project_name": "proj",
            "parent_is_running": False,
            "parent_cl_name": "proj",
            "parent_workspace_dir": str(workspace_dir),
            "parent_workspace_num": WORKSPACE_NUM,
            "host_composed": True,
        }
    successor = {
        "agent_name": "origin-agent--1",
        "role_suffix": "--1",
        "artifacts_dir": str(child),
        "artifacts_timestamp": ARTIFACTS_TIMESTAMP,
        "launch_timestamp": LAUNCH_TIMESTAMP,
        "launch_identity": launch_id,
        "prompt_ref": str(prompt),
        "launch_prompt_ref": str(prompt),
        "prompt_digest": successor_prompt_digest(prompt.read_text()),
        "launch_prompt_digest": successor_prompt_digest(prompt.read_text()),
        "project_name": "proj",
        "project_file": str(project_file),
        "workspace_dir": str(workspace_dir),
        "workspace_num": WORKSPACE_NUM,
        "is_home_mode": False,
        "cl_name": "proj",
        "update_target": "",
        "history_sort_key": "proj",
        "workflow_name": "origin-agent",
        "origin_artifacts_timestamp": origin.name,
        "model": "model",
        "provider": "provider",
        "vcs_ref": None,
        "relationships": {},
        "continuation_refs": {},
        "loop_state": {},
        "attach_plan": attach_plan,
    }
    (child / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": successor["agent_name"],
                "staged_handoff_id": STAGED_ID,
                "staged_successor_launch_id": launch_id,
            }
        ),
        encoding="utf-8",
    )
    with acquire_adoption_lock(origin):
        write_staged_successor_locked(
            {
                "schema_version": 1,
                "staged_id": STAGED_ID,
                "kind": "pipe",
                "origin_artifacts_dir": str(origin),
                "delivery_state": "created",
                "successor": successor,
            },
            artifacts_dir=origin,
        )
    write_adoption_receipt(
        {
            "staged_id": STAGED_ID,
            "adopted_at": "2026-10-28T12:01:00Z",
            "outcome": "adopted",
            "refs": {"loop_outcome": None, "successor_artifacts_dir": str(child)},
        },
        artifacts_dir=str(origin),
    )
    return {
        "origin": origin,
        "root": root,
        "child": child,
        "workspace_dir": workspace_dir,
        "project_file": project_file,
        "successor": successor,
    }


def _install_fake_process_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    child: Path,
) -> list[int]:
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )

    def managed_tmpdir(*parts: str) -> str:
        path = tmp_path / ".sase" / "managed-tmp" / Path(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    monkeypatch.setattr("sase.core.paths.get_sase_managed_tmpdir", managed_tmpdir)
    monkeypatch.setattr(
        "sase.core.paths.sharded_path",
        lambda *_args: str(tmp_path / "agent-output.log"),
    )
    monkeypatch.setattr(
        "sase.agent.process_tree.process_is_running",
        lambda pid: pid == SUCCESSOR_PID,
    )
    monkeypatch.setattr(
        "sase.core.process_identity.process_identity_matches",
        lambda *_args: True,
    )
    process_pids: list[int] = []

    def fake_process(_prepared, *, env, claim_callback=None):
        del env
        assert claim_callback is not None
        assert claim_callback(SUCCESSOR_PID)
        process_pids.append(SUCCESSOR_PID)
        (child / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": "origin-agent--1",
                    "pid": SUCCESSOR_PID,
                    "process_identity": {"start_ticks": 2},
                    "staged_handoff_id": STAGED_ID,
                    "staged_successor_launch_id": f"{STAGED_ID}:{ARTIFACTS_TIMESTAMP}",
                }
            ),
            encoding="utf-8",
        )
        return SUCCESSOR_PID

    monkeypatch.setattr(
        "sase.core.agent_launch_facade.spawn_prepared_agent_process", fake_process
    )
    return process_pids


@pytest.mark.parametrize("attach", [False, True])
def test_automatic_reconcile_transfers_dead_origin_claim_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attach: bool
) -> None:
    setup = _setup_staged_successor(tmp_path, monkeypatch, attach=attach)
    process_pids = _install_fake_process_boundary(tmp_path, monkeypatch, setup["child"])
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_args: "dead",
    )
    monkeypatch.setattr(
        "sase.axe.staged_handoff_reconcile.staged_reconcile_page",
        lambda *_args: {
            "cursor": {"again": True},
            "candidates": [str(setup["origin"])],
            "scanned": 1,
            "errors": [],
        },
    )

    from sase.axe.staged_handoff_reconcile import reconcile_staged_handoffs

    state_path = tmp_path / ".sase" / "axe" / "staged_handoff_reconcile.json"
    first = reconcile_staged_handoffs(
        projects_root=setup["root"],
        index_path=tmp_path / "agent-index.jsonl",
        state_path=state_path,
    )
    assert first.delivered == 1, first
    claim_rows = [
        claim
        for claim in get_claimed_workspaces(str(setup["project_file"]))
        if claim.workspace_num == WORKSPACE_NUM
    ]
    assert len(claim_rows) == 1
    assert claim_rows[0].pid == SUCCESSOR_PID
    assert claim_rows[0].artifacts_timestamp == convert_timestamp_to_artifacts_format(
        setup["successor"]["launch_timestamp"]
    )
    assert read_adoption_receipt(str(setup["origin"]))["outcome"] == "adopted"
    record = read_staged_successor(str(setup["origin"]), staged_id=STAGED_ID)
    assert record["delivery_state"] == "submitted"
    assert record["successor"]["launch_pid"] == SUCCESSOR_PID

    second = reconcile_staged_handoffs(
        projects_root=setup["root"],
        index_path=tmp_path / "agent-index.jsonl",
        state_path=state_path,
    )
    assert second.already_adopted == 1, second
    assert process_pids == [SUCCESSOR_PID]


def test_explicit_readopt_service_transfers_origin_claim(tmp_path, monkeypatch):
    setup = _setup_staged_successor(tmp_path, monkeypatch)
    process_pids = _install_fake_process_boundary(tmp_path, monkeypatch, setup["child"])

    result = recover_staged_handoff(str(setup["origin"]), mode="explicit")

    assert result.adopted and result.already_adopted
    claim_rows = [
        claim
        for claim in get_claimed_workspaces(str(setup["project_file"]))
        if claim.workspace_num == WORKSPACE_NUM
    ]
    assert len(claim_rows) == 1 and claim_rows[0].pid == SUCCESSOR_PID
    assert (
        read_staged_successor(str(setup["origin"]), staged_id=STAGED_ID)["successor"][
            "launch_pid"
        ]
        == SUCCESSOR_PID
    )
    assert process_pids == [SUCCESSOR_PID]

    replay = recover_staged_handoff(str(setup["origin"]), mode="explicit")
    assert replay.adopted and process_pids == [SUCCESSOR_PID]


def test_foreign_workspace_owner_holds_then_release_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = _setup_staged_successor(tmp_path, monkeypatch, owner_pid=OTHER_PID)
    process_pids = _install_fake_process_boundary(tmp_path, monkeypatch, setup["child"])

    held = recover_staged_handoff(str(setup["origin"]), mode="explicit")

    assert not held.adopted
    assert f"workspace #{WORKSPACE_NUM}" in (held.reason or "")
    assert f"pid {OTHER_PID}" in (held.reason or "")
    assert "ace(run)-origin" in (held.reason or "")
    assert process_pids == []
    record = read_staged_successor(str(setup["origin"]), staged_id=STAGED_ID)
    assert record["delivery_state"] == "created"

    release = release_workspace(
        str(setup["project_file"]),
        WORKSPACE_NUM,
        workflow="ace(run)-origin",
        cl_name="proj",
        expected_pid=OTHER_PID,
    )
    assert release.success
    delivered = recover_staged_handoff(str(setup["origin"]), mode="explicit")
    assert delivered.adopted and process_pids == [SUCCESSOR_PID]
    claim_rows = [
        claim
        for claim in get_claimed_workspaces(str(setup["project_file"]))
        if claim.workspace_num == WORKSPACE_NUM
    ]
    assert len(claim_rows) == 1 and claim_rows[0].pid == SUCCESSOR_PID


def test_pinned_origin_claim_remains_pinned_on_successor(tmp_path, monkeypatch):
    setup = _setup_staged_successor(tmp_path, monkeypatch, pinned=True, attach=True)
    process_pids = _install_fake_process_boundary(tmp_path, monkeypatch, setup["child"])

    result = deliver_staged_successor_detached(str(setup["origin"]), STAGED_ID)

    assert result.state == "submitted"
    claim_rows = [
        claim
        for claim in get_claimed_workspaces(str(setup["project_file"]))
        if claim.workspace_num == WORKSPACE_NUM
    ]
    assert len(claim_rows) == 1
    assert claim_rows[0].pid == SUCCESSOR_PID
    assert claim_rows[0].pinned
    assert process_pids == [SUCCESSOR_PID]

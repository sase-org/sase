"""A later session member must settle its runner's exact workspace claim."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe.run_agent_helpers_artifacts import update_meta_fields
from sase.core.paths import sase_projects_dir
from sase.gate_turn._transaction_creator import CreatorContext, resolve_creator
from sase.gate_turn._transaction_spec import spec_from_request
from sase.gate_turn import transaction as transaction_module
from sase.gate_turn.models import GateTurnError
from sase.gate_turn.store import read_gate_turn_marker
from sase.running_field import ClaimResult, WorkspaceClaim, get_claimed_workspaces
from sase.turns.workspace_retention import RETENTION_RECORD_LOCATOR
from tests._notification_gates_fixtures import custom_gate_spec
from tests.monitor._fixtures import write_project_file


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "sase-test@example.invalid")
    _git(path, "config", "user.name", "SASE Test")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "base")


def _write_meta(path: Path, meta: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _spec(request_id: str) -> dict[str, Any]:
    spec = custom_gate_spec(request_id=request_id)
    spec["shell"] = {
        "pending_status": "GATE",
        "settled_status": "GATED",
        "workspace": "inherit",
        "next": {"prompt": "continue", "fork": "session", "output": ["results"]},
        "suffix": "--gate",
    }
    return spec


def test_resolve_creator_separates_current_member_from_root_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_timestamp = "20261102120000"
    member_timestamp = "20261102120100"
    root = tmp_path / root_timestamp
    member = tmp_path / member_timestamp
    _write_meta(
        root,
        {
            "name": "agent",
            "agent_session": "agent",
            "pid": 111,
            "workspace_num": 17,
            "cl_name": "feature",
        },
    )
    _write_meta(
        member,
        {
            "name": "agent--code",
            "agent_session": "agent",
            "pid": 111,
            "workspace_num": 17,
            "cl_name": "stale-member-patch",
        },
    )
    record = SimpleNamespace(
        artifact_dir=str(member), timestamp=member_timestamp, project_file="proj.sase"
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(member))
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", root_timestamp)
    monkeypatch.delenv("SASE_AGENT_CL_NAME", raising=False)
    monkeypatch.setattr(
        "sase.monitor.store_lane.resolve_caller_agent",
        lambda *_args, **_kwargs: SimpleNamespace(record=record),
    )

    creator = resolve_creator("proj")

    assert creator.artifacts_dir == str(member)
    assert creator.timestamp == member_timestamp
    assert creator.claim_artifacts_dir == str(root)
    assert creator.claim_artifacts_timestamp == root_timestamp
    assert creator.workspace_num == 17
    assert creator.runner_pid == 111
    assert creator.cl_name == "feature"
    assert creator.meta["name"] == "agent--code"


def test_staged_creator_persists_root_claim_identity_without_adopter_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.gate_turn._transaction_creator import creator_context_from_persisted
    from sase.gate_turn.staged_contract import (
        collect_staged_gate_creator,
        prepare_staged_gate,
    )
    import sase.gate_turn.staged_contract as staged_contract
    from tests.gate_turn.test_staged_contract import _request, _write_sources

    root_timestamp = "20261102120000"
    member_timestamp = "20261102120100"
    root = tmp_path / root_timestamp
    member = tmp_path / member_timestamp
    _write_meta(
        root,
        {
            "name": "agent",
            "agent_session": "agent",
            "pid": 111,
            "workspace_num": 17,
            "cl_name": "feature",
        },
    )
    _write_meta(
        member,
        {
            "name": "agent--code",
            "agent_session": "agent",
            "pid": 111,
            "workspace_num": 17,
            "cl_name": "stale-member-patch",
        },
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(member))
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", root_timestamp)
    monkeypatch.delenv("SASE_AGENT_CL_NAME", raising=False)
    monkeypatch.setattr(
        staged_contract, "_project_file_path", lambda _project: "proj.sase"
    )

    staged_creator = collect_staged_gate_creator(project_name="proj")

    assert staged_creator["timestamp"] == member_timestamp
    assert staged_creator["workspace_num"] == 17
    assert staged_creator["runner_pid"] == 111
    assert staged_creator["cl_name"] == "feature"
    assert staged_creator["meta"]["claim_origin"] == {
        "artifacts_dir": str(root),
        "artifacts_timestamp": root_timestamp,
        "workspace_num": 17,
        "runner_pid": 111,
        "cl_name": "feature",
    }
    _write_sources(tmp_path, monkeypatch)
    preparation = prepare_staged_gate(
        _request(),
        creator=staged_creator,
        artifacts_dir=str(member),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-11-02T12:01:00Z",
    )
    assert preparation.payload is not None
    assert (
        preparation.payload["creator"]["meta"]["claim_origin"]["artifacts_timestamp"]
        == root_timestamp
    )

    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20261102129999")
    persisted = creator_context_from_persisted(staged_creator)
    assert persisted.artifacts_dir == str(member)
    assert persisted.timestamp == member_timestamp
    assert persisted.claim_artifacts_dir == str(root)
    assert persisted.claim_artifacts_timestamp == root_timestamp
    assert persisted.cl_name == "feature"


def test_detached_failed_gate_pins_root_claim_and_preserves_private_linked_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    root_timestamp = "20261102120000"
    member_timestamp = "20261102120100"
    artifact_parent = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    root_artifacts = artifact_parent / root_timestamp[:6] / root_timestamp[6:8]
    root_artifacts = root_artifacts / root_timestamp
    member_artifacts = root_artifacts.parent / member_timestamp

    workspace = tmp_path / "workspace"
    linked = tmp_path / "private-sase-core"
    _init_repo(workspace)
    _init_repo(linked)
    root_meta = {
        "name": "agent",
        "agent_session": "agent",
        "pid": 111,
        "workspace_num": 17,
        "cl_name": "feature",
        "workspace_dir": str(workspace),
    }
    member_meta = {
        **root_meta,
        "name": "agent--code",
        "cl_name": "stale-member-patch",
    }
    _write_meta(root_artifacts, root_meta)
    (root_artifacts / "done.json").write_text('{"outcome":"failed"}', encoding="utf-8")
    _write_meta(member_artifacts, member_meta)

    from sase.llm_provider.commit_finalizer_git import normalize_path
    from sase._linked_repo_markers import record_opened_repo

    baseline = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": "primary",
                "path": normalize_path(str(workspace)),
                "kind": "primary",
                "name": "proj",
                "scope": "run_start",
                "captured_at": "2026-11-02T12:00:00+00:00",
                "fingerprints": {},
            }
        ],
    }
    (member_artifacts / "finalizer_baseline.json").write_text(
        json.dumps(baseline), encoding="utf-8"
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(member_artifacts))
    record_opened_repo(
        "sase-core",
        str(linked),
        kind="linked",
        reason="gate-origin regression",
        opened_at="2026-11-02T12:01:00+00:00",
    )
    (workspace / "tracked.txt").write_text("session primary edit\n", encoding="utf-8")
    (linked / "tracked.txt").write_text("session linked edit\n", encoding="utf-8")

    project_file = write_project_file(
        "proj",
        workspace_dir=str(workspace),
        running_claims=[
            WorkspaceClaim(
                workspace_num=17,
                workflow="run",
                cl_name="feature",
                pid=111,
                artifacts_timestamp=root_timestamp,
            )
        ],
    )
    creator = CreatorContext(
        project_name="proj",
        project_file=project_file,
        artifacts_dir=str(member_artifacts),
        timestamp=member_timestamp,
        target_name="agent--code",
        durable_lane="agent",
        meta=member_meta,
        workspace_num=17,
        runner_pid=111,
        cl_name="feature",
        claim_artifacts_dir=str(root_artifacts),
        claim_artifacts_timestamp=root_timestamp,
    )

    monkeypatch.setattr(
        transaction_module, "find_gate_turn_by_gate_id", lambda *_: None
    )
    monkeypatch.setattr(transaction_module, "has_any_gate_turn", lambda *_: False)
    monkeypatch.setattr(
        "sase.gate_turn.start_claim._creator_pid_is_live", lambda _pid: True
    )

    def refuse_move(*_args: object, **_kwargs: object) -> ClaimResult:
        return ClaimResult(False, "injected gate-start refusal")

    monkeypatch.setattr(
        "sase.gate_turn.start_claim.transfer_workspace_claim", refuse_move
    )
    gate_artifacts: list[str] = []
    real_create_member = transaction_module.create_gate_turn_member

    def capture_member(*args: object, **kwargs: object) -> str:
        result = real_create_member(*args, **kwargs)
        gate_artifacts.append(result)
        return result

    monkeypatch.setattr(transaction_module, "create_gate_turn_member", capture_member)
    monkeypatch.setattr(
        transaction_module, "_pulse_after_gate_visible", lambda *_: None
    )

    with pytest.raises(GateTurnError, match="injected gate-start refusal"):
        transaction_module.publish_gate_turn(
            spec_from_request(_spec("origin-refusal")),
            creator=creator,
            creator_live=False,
        )

    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].artifacts_timestamp == root_timestamp
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == (
        "session primary edit\n"
    )
    assert (linked / "tracked.txt").read_text(encoding="utf-8") == (
        "session linked edit\n"
    )
    retention_path = root_artifacts / RETENTION_RECORD_LOCATOR
    retention = json.loads(retention_path.read_text(encoding="utf-8"))
    assert retention["disposition"] == "retain"
    assert retention["evidence_artifacts_dir"] == str(member_artifacts)
    assert set(retention["affected_repo_ids"]) == {"primary", "linked:sase-core"}

    assert len(gate_artifacts) == 1
    gate_record = read_gate_turn_marker("proj", gate_artifacts[0])
    assert gate_record is not None and gate_record.gate_state == "failed"
    assert (Path(gate_artifacts[0]) / "done.json").is_file()

    from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries

    monkeypatch.setattr(
        "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
        lambda: [project_file],
    )
    monkeypatch.setattr(
        "sase.ace.scheduler.stale_running_sweep.is_process_running",
        lambda _pid: False,
    )
    assert cleanup_stale_running_entries() == 0
    assert get_claimed_workspaces(project_file)[0].pinned is True

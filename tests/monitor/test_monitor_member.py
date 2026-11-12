"""Tests for :mod:`sase.monitor.member`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.continuation_facade import (
    bind_conditional_completion,
    evaluate_conditional_completion,
    seal_conditional_completion,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase._linked_repo_markers import (
    opened_linked_repo_records,
    record_opened_linked_repo,
)
from sase.finalizers._prepare_observe import observe_completion_repositories
from sase.finalizers.declaration import publish_final_context
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_baseline import (
    capture_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.macro.directives import PromptDirectives
from sase.monitor.member import create_monitor_member
from tests.core._continuation_facade_helpers import (
    make_passed_stage,
    make_prepare_request,
)
from tests.finalizers_live_e2e_test_helpers import (
    attach_bare_remote,
    commit_instance,
    config_for,
    init_live_repo,
    isolate_host_config,
    real_git_stitch,
    run_controller,
    run_git,
    submit_from_context,
    use_config,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_create_monitor_member_inherits_lineage_and_sets_monitor_fields() -> None:
    base_meta = {
        "name": "acme--0",
        "model": "claude-sonnet-5",
        "llm_provider": "claude",
        "workspace_dir": "/work/acme",
        "cl_name": "acme",
        "bead_id": "sase-kp",
        "tribe": "sase",
        "agent_session": "acme",
        "agent_clan": "acme-clan",
        "agent_clan_generation": "20260812115000",
        "vcs_ref": ["gh", "sase"],
    }

    artifacts_dir = create_monitor_member(
        "proj",
        base_meta,
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=3,
        monitor_id="abc123def456",
        command="just check-full",
        cwd="/work/acme",
        label="just check-full",
        reason="verify the refactor",
        next_action="Fix anything the check reported.",
        next_model="@small",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=2700.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
        idle_timeout_seconds=600.0,
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())

    assert meta["name"] == "acme--mon"
    assert meta["workflow_name"] == "acme"
    assert meta["agent_session"] == "acme"
    assert meta["agent_session_role"] == "monitor"
    assert "agent_family" not in meta
    assert "agent_family_role" not in meta
    assert meta["agent_clan"] == "acme-clan"
    assert meta["agent_clan_generation"] == "20260812115000"
    assert meta["role_suffix"] == "--mon"
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 3

    # Inherited lineage from the selected parent artifact.
    assert meta["model"] == "claude-sonnet-5"
    assert meta["llm_provider"] == "claude"
    assert meta["workspace_dir"] == "/work/acme"
    assert meta["cl_name"] == "acme"
    assert meta["bead_id"] == "sase-kp"
    assert meta["tribe"] == "sase"
    assert meta["vcs_ref"] == ["gh", "sase"]

    # Monitor-specific fields.
    assert meta["monitor_id"] == "abc123def456"
    assert meta["proc_id"] == "abc123def456"
    assert meta["pid"] is None
    assert "process_identity" not in meta
    assert meta["turn_kind"] == "monitor"
    workflow_state = json.loads(
        (Path(artifacts_dir) / "workflow_state.json").read_text()
    )
    assert workflow_state["pid"] is None
    assert "process_identity" not in workflow_state
    assert meta["monitor_command"] == "just check-full"
    assert meta["monitor_cwd"] == "/work/acme"
    assert meta["monitor_label"] == "just check-full"
    assert meta["monitor_reason"] == "verify the refactor"
    assert meta["monitor_next_action"] == "Fix anything the check reported."
    assert meta["monitor_next_model"] == "@small"
    assert meta["monitor_start_status"] == "MONITORING"
    assert meta["monitor_stop_status"] == "MONITORED"
    assert meta["monitor_timeout_seconds"] == 2700.0
    assert meta["monitor_tail_lines"] == 200
    assert meta["monitor_next_output"] == "tail"
    assert meta["monitor_idle_timeout_seconds"] == 600.0
    assert meta["monitor_state"] == "running"
    assert meta["monitor_settled"] is False
    assert meta["monitor_request_fingerprint"] == "sha256:test"
    assert "monitor_execution_argv" not in meta


def test_create_monitor_member_inherits_parent_queue_weight_by_default() -> None:
    """No override: a general monitor inherits weight/claim like today."""
    base_meta = {
        "name": "acme--0",
        "agent_session": "acme",
        "queue_weight": 2.0,
        "queue_weight_explicit": True,
        "runner_claim_owner_key": "owner-key-123",
    }

    artifacts_dir = create_monitor_member(
        "proj",
        base_meta,
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=0,
        monitor_id="abc123def456",
        command="just check-full",
        cwd="/work/acme",
        label="just check-full",
        reason="verify",
        next_action=None,
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=30.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["queue_weight"] == 2.0
    assert meta["queue_weight_explicit"] is True
    assert meta["runner_claim_owner_key"] == "owner-key-123"


def test_create_monitor_member_queue_weight_override_replaces_inherited_weight() -> (
    None
):
    """An explicit override (epic-launch supervision) wins over inheritance."""
    base_meta = {
        "name": "acme--0",
        "agent_session": "acme",
        "queue_weight": 3.0,
        "queue_weight_explicit": True,
        "runner_claim_owner_key": "owner-key-123",
    }

    artifacts_dir = create_monitor_member(
        "proj",
        base_meta,
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=0,
        monitor_id="abc123def456",
        command="sase bead work plan.md --yes-to-all",
        cwd="/work/acme",
        label="Epic launch · plan",
        reason="Launch the approved epic from plan.md",
        next_action=None,
        start_status="EPIC APPROVED",
        stop_status="EPIC CREATED",
        timeout_seconds=30.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
        queue_weight_override=0.0,
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["queue_weight"] == 0.0
    assert meta["queue_weight_explicit"] is True
    assert meta["monitor_queue_weight_overridden"] is True
    assert meta["monitor_inherited_queue_weight"] == 3.0
    assert meta["monitor_inherited_queue_weight_explicit"] is True
    # The override is only about weight; the inherited claim lineage is
    # untouched so the monitor still represents the same live owner.
    assert meta["runner_claim_owner_key"] == "owner-key-123"


def test_create_monitor_member_persists_execution_argv() -> None:
    artifacts_dir = create_monitor_member(
        "proj",
        {"name": "acme--0", "agent_session": "acme"},
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=0,
        monitor_id="abc123def456",
        command="sase bead work plan.md --yes-to-all",
        cwd="/work/acme",
        label="Epic launch · plan",
        reason="Launch the approved epic from plan.md",
        next_action=None,
        start_status="EPIC APPROVED",
        stop_status="EPIC CREATED",
        timeout_seconds=30.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
        execution_argv=[
            "/usr/bin/python",
            "bootstrap.py",
            "--",
            "sase",
            "bead",
            "work",
        ],
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_command"] == "sase bead work plan.md --yes-to-all"
    assert meta["monitor_execution_argv"] == [
        "/usr/bin/python",
        "bootstrap.py",
        "--",
        "sase",
        "bead",
        "work",
    ]


def test_create_monitor_member_omits_next_action_when_none() -> None:
    base_meta = {"name": "acme--0", "agent_session": "acme"}

    artifacts_dir = create_monitor_member(
        "proj",
        base_meta,
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=0,
        monitor_id="abc123def456",
        command="sleep 5",
        cwd="/work/acme",
        label="sleep",
        reason="wait",
        next_action=None,
        start_status="SLEEPING",
        stop_status="SLEPT",
        timeout_seconds=30.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert "monitor_next_action" not in meta
    assert "monitor_next_model" not in meta
    assert "monitor_idle_timeout_seconds" not in meta
    assert "agent_clan" not in meta
    assert "agent_clan_generation" not in meta


def test_monitor_member_inherits_authoritative_finalizer_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = init_live_repo(tmp_path / "workspace")
    attach_bare_remote(workspace, tmp_path / "workspace.git")
    parent = tmp_path / "parent-artifacts"
    parent.mkdir()
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(workspace))
    capture_dirty_baseline(str(workspace), str(parent))

    main_path = workspace / "main-work.txt"
    main_path.write_text("authored before monitor\n", encoding="utf-8")
    linked = tmp_path / "linked-widget"
    init_live_repo(linked)
    attach_bare_remote(linked, tmp_path / "linked-widget.git")
    protected_path = linked / "pre-existing.txt"
    protected_path.write_text("pre-existing linked dirt\n", encoding="utf-8")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent))
    record_opened_linked_repo(
        "widget", str(linked), reason="monitor inheritance regression"
    )
    linked_path = linked / "linked-work.txt"
    linked_path.write_text("authored before monitor\n", encoding="utf-8")

    starter_observations = observe_completion_repositories(parent)
    starter_main_observation = next(
        item for item in starter_observations if item["kind"] == "main"
    )
    decided_repo_ids = [starter_main_observation["repo_id"]]
    prepare_request = make_prepare_request(observations=[starter_main_observation])
    prepare_request["creator"]["workspace_id"] = "0"
    prepare_request["context"]["obligation_ids"] = decided_repo_ids
    prepare_request["declaration"]["payloads"][0]["payload"]["repositories"] = [
        {
            "repo_id": repo_id,
            "action": "commit",
            "message": "fix: preserve monitor ownership",
        }
        for repo_id in decided_repo_ids
    ]
    prepared = seal_conditional_completion(prepare_request)
    bound = bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": prepared,
            "monitor_id": "inheritance-regression",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:inheritance-regression",
        }
    )

    monitor_dir = create_monitor_member(
        "proj",
        {
            "name": "acme--0",
            "agent_session": "acme",
            "workspace_dir": str(workspace),
            "workspace_num": 0,
        },
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20261112120000",
        workspace_num=0,
        monitor_id="inheritance-regression",
        command="just check",
        cwd=str(workspace),
        label="just check",
        reason="exercise baseline inheritance",
        next_action=None,
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=3600.0,
        tail_lines=20,
        next_output="tail",
        request_fingerprint="sha256:inheritance-regression",
        starter_artifacts_dir=str(parent),
    )
    monitor_root = Path(monitor_dir)

    inherited = load_finalizer_baseline_records(monitor_root)
    assert inherited is not None
    main_baseline = next(item for item in inherited if item.kind == "main")
    assert main_baseline.fingerprints == {}
    assert opened_linked_repo_records(monitor_root)["widget"]["workspace_dir"] == str(
        linked.resolve()
    )

    observations = observe_completion_repositories(monitor_root)
    main_observation = next(item for item in observations if item["kind"] == "main")
    main_path_observation = next(
        item for item in main_observation["paths"] if item["path"] == "main-work.txt"
    )
    assert main_path_observation["protected"] is False
    assert main_path_observation["foreign"] is False

    linked_observation = next(
        (item for item in observations if item["name"] == "widget"), None
    )
    assert linked_observation is not None, [
        (item["name"], item["kind"], item["repo_id"]) for item in observations
    ]
    linked_path_observation = next(
        item
        for item in linked_observation["paths"]
        if item["path"] == "linked-work.txt"
    )
    assert linked_path_observation["protected"] is False
    assert linked_path_observation["foreign"] is False
    protected_observation = next(
        item
        for item in linked_observation["paths"]
        if item["path"] == "pre-existing.txt"
    )
    assert protected_observation["protected"] is True
    assert protected_observation["foreign"] is True

    stages = [
        make_passed_stage("formatting", "fmt (python)"),
        make_passed_stage("ruff", "lint (ruff)"),
        make_passed_stage("mypy", "lint (mypy)"),
        make_passed_stage("validation", "SASE validation"),
        make_passed_stage("full_tests", "test (full)"),
    ]
    decision = evaluate_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": bound,
            "outcome": "completed",
            "exit_code": 0,
            "command": ["just", "check-full"],
            "observations": observations,
            "stages": stages,
            "executors": prepare_request["executors"],
            "workspace_identity": "0",
            "original_workspace_identity": "0",
            "degraded_workspace": False,
            "current_plan_digest": prepare_request["context"]["plan_digest"],
            "current_obligation_ids": decided_repo_ids,
            "substitutions": {"duration": "1m"},
        }
    )
    assert decision["eligible"] is True, decision["reasons"]

    isolate_host_config(monkeypatch, tmp_path)
    use_config(
        monkeypatch,
        config_for({"commit": commit_instance()}, ("commit",)),
    )
    monitor_meta = json.loads((monitor_root / "agent_meta.json").read_text())
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(monitor_root))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", monitor_root.name)
    monkeypatch.setenv("SASE_AGENT_NAME", monitor_meta["name"])
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "monitor-inheritance-nonce")
    monkeypatch.setenv("SASE_LINKED_REPOS_JSON", "[]")
    monkeypatch.delenv("SASE_SIBLING_REPOS_JSON", raising=False)
    resolve_and_persist_finalizer_plan(
        PromptDirectives(), artifacts_dir=str(monitor_root)
    )
    publication = publish_final_context(artifacts_dir=str(monitor_root))
    obligations = [
        item for item in publication.context.obligations if item.kind == "repository"
    ]
    obligated_paths = {path for item in obligations for path in item.paths}
    assert "main-work.txt" in obligated_paths
    assert "linked-work.txt" in obligated_paths
    assert "pre-existing.txt" not in obligated_paths

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", real_git_stitch
    )
    submit_from_context(monitor_root)
    result = run_controller(monitor_root)
    assert result.content == "done"
    commits = json.loads((monitor_root / "commit_results.json").read_text())
    assert {item["cwd"] for item in commits} == {
        str(workspace.resolve()),
        str(linked.resolve()),
    }
    main_commit_files = run_git(
        workspace, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).stdout.splitlines()
    linked_commit_files = run_git(
        linked, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).stdout.splitlines()
    assert main_commit_files == ["main-work.txt"]
    assert linked_commit_files == ["linked-work.txt"]
    assert "?? pre-existing.txt" in run_git(linked, "status", "--short").stdout

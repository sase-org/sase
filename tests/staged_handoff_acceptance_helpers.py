"""Shared fixtures for staged-handoff acceptance-matrix tests."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.staged_handoff import (
    build_plan_staged_record,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_staged import (
    StagedInlineContinuation,
    dispatch_completed_staged_handoff,
)
from sase.finalizers.commit import StitchCommandResult
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.transaction import GateTurnCreation
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.notification_gates.model_results import GateCreationResult
from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_exec_plan_helpers import patched_plan_deps
from tests.finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    dirty_state,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
)

RUN_ID = "20261028120000"
PLANNER_RESPONSE = "The model's actual final response."
STAGED_CREATED_AT = "2020-01-01T00:00:00Z"


def prepare_dual_repo_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path]:
    """Return ``(repo, linked, artifacts, plan_file)`` for settlement tests."""
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    artifacts = tmp_path / RUN_ID
    repo.mkdir()
    linked.mkdir()
    artifacts.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", RUN_ID)
    monkeypatch.setenv("SASE_AGENT", "1")
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent-1", "workspace_dir": str(repo)}),
        encoding="utf-8",
    )
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\nbody\n", encoding="utf-8")
    return repo, linked, artifacts, plan_file


def dual_dirty(repo: Path, linked: Path) -> dict[str, tuple[DirtyRepo, ...]]:
    return {
        "repos": (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
    }


def patch_dirty_for_settlement(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
) -> None:
    """Patch both the controller and staged-settlement dirty collectors."""
    patch_dirty(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.collect_dirty_state",
        lambda _project_dir, artifact_root=None: dirty_state(
            dirty["repos"], project_dir=repo
        ),
    )


def stage_plan(
    artifacts: Path,
    plan_file: Path,
    *,
    original_file: Path | None = None,
) -> dict[str, Any]:
    record = build_plan_staged_record(
        plan_file=str(plan_file),
        original_file=str(original_file or plan_file),
        dirty_obligations_at_stage=[],
        created_at=STAGED_CREATED_AT,
    )
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(record["staged_id"]),
        PLANNER_RESPONSE,
        artifacts_dir=str(artifacts),
    )
    return record


def commit_shas(artifacts: Path) -> dict[str, str]:
    payload = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    return {str(row["cwd"]): str(row["commit_sha"]) for row in payload}


def named_stitch(
    artifacts: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
    calls: list[str],
) -> Any:
    """Commit each dirty repo with a distinct SHA derived from its name."""

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append(repo_arg.name)
        remaining = tuple(item for item in dirty["repos"] if item.path != repo_arg.path)
        dirty["repos"] = remaining
        sha = ("1" if repo_arg.name == "main" else "2") * 40
        tree = ("a" if repo_arg.name == "main" else "b") * 40
        payload: list[dict[str, str]] = []
        existing = artifacts / "commit_results.json"
        if existing.is_file():
            payload = json.loads(existing.read_text(encoding="utf-8"))
        payload.append(
            {
                "cwd": repo_arg.path,
                "result": "ok",
                "commit_sha": sha,
                "commit_tree": tree,
            }
        )
        existing.write_text(json.dumps(payload), encoding="utf-8")
        return StitchCommandResult(returncode=0, stdout="ok\n")

    return run_stitch


def make_continuation(tmp_path: Path, artifacts: Path) -> tuple[object, LoopState]:
    ctx = replace(
        make_exec_ctx(tmp_path, is_home_mode=False),
        artifacts_dir=str(artifacts),
        agent_name="agent-1",
    )
    state = LoopState(
        current_prompt="planner prompt",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="planner prompt",
    )
    return ctx, state


def _gate_creation(
    member: Path, *, gate_state: str, notification_id: str | None
) -> GateTurnCreation:
    gate = GateCreationResult(
        schema_version=3,
        notification_id=notification_id,
        request_id="plan-gate",
        kind="plan",
        bundle_path=member / "bundle",
        request_path=member / "bundle" / "request.json",
        response_path=member / "bundle" / "response.json",
        preview_path=None,
        continuation_mode="plan_approval",
        auto_resolution={"state": "resolved"} if gate_state == "answered" else {},
        hashes={},
    )
    record = GateTurnRecord(
        gate_id="plan-gate",
        member_agent_name="agent-1--gate",
        lane="agent-1",
        project_name="sase",
        artifacts_dir=str(member),
        timestamp="20261028120000",
        kind="plan",
        gate_state=gate_state,  # type: ignore[arg-type]
        start_status="TALE",
        stop_status="TALE APPROVED",
        accent="#FFD75F",
        label="Plan",
        reason="wait for reviewer",
        creator_agent="agent-1--plan",
        bundle_path=str(member / "bundle"),
        notification_id=notification_id,
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )
    return GateTurnCreation(
        gate=gate, record=record, project_file=None, claim_move=None, cl_name=None
    )


def prepare_gate_member(tmp_path: Path) -> Path:
    member = tmp_path / "gate-member"
    member.mkdir(exist_ok=True)
    (member / "bundle").mkdir(exist_ok=True)
    (member / "agent_meta.json").write_text("{}", encoding="utf-8")
    return member


def pending_gate_creation(member: Path) -> GateTurnCreation:
    return _gate_creation(member, gate_state="pending", notification_id="notif-1")


def auto_gate_creation(member: Path) -> GateTurnCreation:
    return _gate_creation(member, gate_state="answered", notification_id=None)


def dispatch_with_gate(
    tmp_path: Path,
    artifacts: Path,
    *,
    expected_cwds: set[str] | None,
    gate_mode: str,
    plan_file: Path,
    extra_patches: tuple[Any, ...] = (),
) -> Any:
    """Adopt after settlement. When ``expected_cwds`` is set, the gate
    callback asserts those commit SHAs are already on disk.
    """
    ctx, state = make_continuation(tmp_path, artifacts)
    member = prepare_gate_member(tmp_path)
    publications: list[dict[str, str]] = []

    def create_gate(*_args: object, **_kwargs: object) -> GateTurnCreation:
        shas = (
            commit_shas(artifacts)
            if (artifacts / "commit_results.json").is_file()
            else {}
        )
        publications.append(shas)
        if expected_cwds is not None:
            assert set(shas) == expected_cwds
        if gate_mode == "pending":
            return pending_gate_creation(member)
        return auto_gate_creation(member)

    plan_result = (
        None
        if gate_mode == "reject"
        else PlanApprovalResult(
            action="approve",
            plan_file=str(plan_file),
            auto_approved=True,
        )
    )
    patchers = [
        patched_plan_deps(),
        patch("sase.plan_gate_turn.create_plan_gate_turn", side_effect=create_gate),
        patch(
            "sase.plan_gate_turn.plan_result_from_gate_creation",
            return_value=plan_result,
        ),
        patch(
            "sase.axe.run_agent_exec_plan_accept.handle_accepted_plan",
            return_value="completed",
        ),
        *extra_patches,
    ]
    if gate_mode != "pending":
        patchers.append(
            patch(
                "sase.axe.run_agent_exec_gate.handle_gate_marker",
                return_value="gated",
            )
        )
    with ExitStack() as stack:
        for patcher in patchers:
            stack.enter_context(patcher)
        result = dispatch_completed_staged_handoff(
            str(artifacts),
            StagedInlineContinuation(ctx=ctx, state=state),
        )
    if expected_cwds is not None:
        assert publications, "gate publication must run after commits"
    return result


def capturing_chat_patch() -> tuple[list[dict[str, Any]], Any]:
    """Patch ``save_chat_history`` and collect the kwargs of each call."""
    captured: list[dict[str, Any]] = []

    def save(**kwargs: Any) -> str:
        captured.append(kwargs)
        return "/fake/chat"

    return captured, patch("sase.history.chat.save_chat_history", side_effect=save)


def settle_commits(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    repo: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
) -> list[str]:
    """Declare, commit every dirty repo, and run the controller to settlement."""
    calls: list[str] = []
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        named_stitch(artifacts, dirty, calls),
    )
    submit_commit(artifacts)
    run_controller(artifacts)
    return calls

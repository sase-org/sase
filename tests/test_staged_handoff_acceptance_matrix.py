"""Commit-before-approval acceptance matrix for staged plan handoffs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.pending_handoff import (
    PIPE_PENDING_MARKER,
    PLAN_PENDING_MARKER,
    QUESTIONS_PENDING_MARKER,
)
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    write_pending_handoff_marker,
)
from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    StagedHandoffError,
    build_plan_staged_record,
    read_adoption_receipt,
    read_staged_handoff,
    write_staged_handoff,
)
from sase.axe.run_agent_exec import (
    _dispatch_staged_on_workflow_error,
    _handle_killed_iteration,
)
from sase.axe.run_agent_exec_staged import (
    StagedInlineContinuation,
    dispatch_completed_staged_handoff,
)
from sase.feature_flags import override_flags
from sase.finalizers.commit import BuiltinCommitFinalizerError, StitchCommandResult
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import FinalizerControllerError
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives, extract_prompt_directives
from tests.finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    run_controller,
    submit_commit,
)
from tests.staged_handoff_acceptance_helpers import (
    PLANNER_RESPONSE,
    capturing_chat_patch,
    commit_shas,
    dispatch_with_gate,
    dual_dirty,
    make_continuation,
    named_stitch,
    patch_dirty_for_settlement,
    prepare_dual_repo_env,
    settle_commits,
    stage_plan,
)


def _held(artifacts: Path, result: Any, *, fragment: str | None = None) -> None:
    assert result is not None and not result.adopted
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None
    assert receipt["outcome"] == "handoff_not_adopted"
    assert read_staged_handoff(str(artifacts)) is not None
    if fragment is not None:
        assert fragment in (result.reason or "")


def _fail_stitch(
    _repo: DirtyRepo,
    _message: str,
    _excludes: tuple[str, ...],
    _context: object,
) -> StitchCommandResult:
    return StitchCommandResult(returncode=1, stderr="hook failed\n")


def _mutate_config() -> FinalizerConfig:
    mutate = ConfiguredFinalizerInstance(
        instance_id="mutate",
        provider_ref="builtin@command",
        after=("commit",),
        config={"command": ["true"], "submission": "none"},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    return FinalizerConfig(
        defaults=("commit", "mutate"),
        required=(),
        instances={"commit": commit, "mutate": mutate},
        provenance={},
    )


@pytest.mark.parametrize("gate_mode", ["pending", "reject"])
def test_dirty_primary_and_linked_commits_before_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_mode: str,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    calls = settle_commits(monkeypatch, artifacts, repo, dirty)
    result = dispatch_with_gate(
        tmp_path,
        artifacts,
        expected_cwds={str(repo), str(linked)},
        gate_mode=gate_mode,
        plan_file=plan_file,
    )
    assert calls == ["main", "plans"]
    shas = commit_shas(artifacts)
    assert shas[str(repo)] == "1" * 40
    assert shas[str(linked)] == "2" * 40
    if gate_mode == "pending":
        assert result is not None and result.adopted
        assert result.outcome == "gated"
    else:
        _held(artifacts, result, fragment="could not be adopted")


def test_missing_declaration_recovers_then_commits_before_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    calls: list[str] = []
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        named_stitch(artifacts, dirty, calls),
    )
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))

    def recover(*_args: object, **_kwargs: object) -> InvokeResult:
        submit_commit(artifacts)
        return InvokeResult(content="recovered")

    provider = MagicMock()
    provider.invoke.side_effect = recover
    run_controller(artifacts, provider)
    result = dispatch_with_gate(
        tmp_path,
        artifacts,
        expected_cwds={str(repo), str(linked)},
        gate_mode="pending",
        plan_file=plan_file,
    )
    assert calls == ["main", "plans"]
    assert result is not None and result.adopted
    provider.invoke.assert_called()


def test_failed_declaration_recovery_holds_and_keeps_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="no declaration")
    with pytest.raises((RuntimeError, FinalizerControllerError)):
        run_controller(artifacts, provider)
    with patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate:
        result = dispatch_completed_staged_handoff(
            str(artifacts),
            StagedInlineContinuation(*make_continuation(tmp_path, artifacts)),
        )
    create_gate.assert_not_called()
    _held(artifacts, result)
    assert not (artifacts / "commit_results.json").exists()


def test_later_finalizer_dirt_reconverges_before_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": ()}
    stage_plan(artifacts, plan_file)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", _mutate_config)
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        named_stitch(artifacts, dirty, calls),
    )

    def run_mutate(*_args: object, **_kwargs: object) -> Any:
        dirty["repos"] = (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
        from sase.core.finalizer_wire import FinalizerInstanceResultWire

        return FinalizerInstanceResultWire(instance_id="mutate", status="success")

    monkeypatch.setattr(
        "sase.finalizers.controller_cycle.execute_non_commit_finalizer",
        run_mutate,
    )

    def recover(*_args: object, **_kwargs: object) -> InvokeResult:
        submit_commit(artifacts)
        return InvokeResult(content="recovered")

    provider = MagicMock()
    provider.invoke.side_effect = recover
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    run_controller(artifacts, provider)
    result = dispatch_with_gate(
        tmp_path,
        artifacts,
        expected_cwds={str(repo), str(linked)},
        gate_mode="pending",
        plan_file=plan_file,
    )
    assert calls == ["main", "plans"]
    assert result is not None and result.adopted


def test_failed_later_dirt_reconverge_holds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": ()}
    stage_plan(artifacts, plan_file)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", _mutate_config)
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        named_stitch(artifacts, dirty, []),
    )

    def run_mutate(*_args: object, **_kwargs: object) -> Any:
        dirty["repos"] = (dirty_repo(repo, name="main", kind="main"),)
        from sase.core.finalizer_wire import FinalizerInstanceResultWire

        return FinalizerInstanceResultWire(instance_id="mutate", status="success")

    monkeypatch.setattr(
        "sase.finalizers.controller_cycle.execute_non_commit_finalizer",
        run_mutate,
    )
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="nope")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    with pytest.raises((RuntimeError, FinalizerControllerError)):
        run_controller(artifacts, provider)
    with patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate:
        result = dispatch_completed_staged_handoff(
            str(artifacts),
            StagedInlineContinuation(*make_continuation(tmp_path, artifacts)),
        )
    create_gate.assert_not_called()
    _held(artifacts, result)


def test_clean_final_none_still_adopts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": ()}
    stage_plan(artifacts, plan_file)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    _, directives = extract_prompt_directives("%final:none\nDo work")
    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))
    run_controller(artifacts)
    result = dispatch_with_gate(
        tmp_path,
        artifacts,
        expected_cwds=set(),
        gate_mode="auto",
        plan_file=plan_file,
    )
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["instances"] == []
    assert result is not None and result.adopted


def test_dirty_final_none_cannot_activate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    _, directives = extract_prompt_directives("%final:none\nDo work")
    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))
    run_controller(artifacts)
    with patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate:
        result = dispatch_completed_staged_handoff(
            str(artifacts),
            StagedInlineContinuation(*make_continuation(tmp_path, artifacts)),
        )
    create_gate.assert_not_called()
    _held(artifacts, result)


def test_failed_commit_never_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
    )
    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError):
        run_controller(artifacts)
    with patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate:
        result = dispatch_completed_staged_handoff(
            str(artifacts),
            StagedInlineContinuation(*make_continuation(tmp_path, artifacts)),
        )
    create_gate.assert_not_called()
    _held(artifacts, result)
    assert not (artifacts / "commit_results.json").exists()


def test_partial_commit_keeps_receipts_and_holds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    patch_dirty_for_settlement(monkeypatch, repo, dirty)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        if repo_arg.name != "main":
            return _fail_stitch(repo_arg, _message, _excludes, _context)
        return named_stitch(artifacts, dirty, calls)(
            repo_arg, _message, _excludes, _context
        )

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", run_stitch
    )
    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError):
        run_controller(artifacts)
    with patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate:
        result = dispatch_completed_staged_handoff(
            str(artifacts),
            StagedInlineContinuation(*make_continuation(tmp_path, artifacts)),
        )
    create_gate.assert_not_called()
    _held(artifacts, result)
    assert commit_shas(artifacts) == {str(repo): "1" * 40}
    assert calls == ["main"]


def test_flag_flip_after_stage_does_not_switch_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    settle_commits(monkeypatch, artifacts, repo, dirty)
    with override_flags(staged_handoffs=False):
        result = dispatch_with_gate(
            tmp_path,
            artifacts,
            expected_cwds={str(repo), str(linked)},
            gate_mode="pending",
            plan_file=plan_file,
        )
    assert result is not None and result.adopted
    assert not (artifacts / PLAN_PENDING_MARKER).exists()
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta.get("handoff_protocol") == "staged"


def test_flag_enabled_questions_stages_instead_of_pending_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.questions_command_handler import handle_questions_command

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sase.main.questions_command_handler.kill_agent_runner_group",
        lambda _artifacts: (_ for _ in ()).throw(SystemExit(0)),
    )
    payload = json.dumps([{"question": "Pick one", "options": [{"label": "A"}]}])
    with override_flags(staged_handoffs=True), pytest.raises(SystemExit) as exc:
        handle_questions_command(payload)
    assert exc.value.code == 0
    assert not (tmp_path / QUESTIONS_PENDING_MARKER).exists()
    record = json.loads(
        (tmp_path / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8")
    )
    assert record["kind"] == "questions"
    assert record["successor_workspace"] == "inherit"
    assert record["carry_allowed"] is True


def test_flag_enabled_pipe_stages_instead_of_pending_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.pipe_handler import handle_pipe_command

    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "agent_session", "pid": 1}), encoding="utf-8"
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sase.main.pipe_handler.kill_agent_runner_group",
        lambda _artifacts: (_ for _ in ()).throw(SystemExit(0)),
    )
    with override_flags(staged_handoffs=True), pytest.raises(SystemExit) as exc:
        handle_pipe_command("finish the review")
    assert exc.value.code == 0
    assert not (tmp_path / PIPE_PENDING_MARKER).exists()
    record = json.loads(
        (tmp_path / STAGED_HANDOFF_FILENAME).read_text(encoding="utf-8")
    )
    assert record["kind"] == "pipe"
    assert record["successor_workspace"] == "inherit"
    assert record["carry_allowed"] is True
    assert record["payload"]["prompt"] == "finish the review"


@pytest.mark.parametrize("protocol", ["staged", "legacy"])
def test_second_handoff_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
) -> None:
    _repo, _linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    if protocol == "staged":
        stage_plan(artifacts, plan_file)
        with (
            pytest.raises(StagedHandoffError),
            patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate,
        ):
            write_staged_handoff(
                build_plan_staged_record(
                    plan_file=str(plan_file),
                    original_file=str(plan_file),
                    dirty_obligations_at_stage=[],
                ),
                artifacts_dir=str(artifacts),
            )
        create_gate.assert_not_called()
    else:
        write_pending_handoff_marker(
            PLAN_PENDING_MARKER,
            {"plan_file": str(plan_file)},
            artifacts_dir=str(artifacts),
        )
        with (
            pytest.raises(PendingHandoffError),
            patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate,
        ):
            write_pending_handoff_marker(
                PLAN_PENDING_MARKER,
                {"plan_file": str(plan_file)},
                artifacts_dir=str(artifacts),
            )
        create_gate.assert_not_called()


@pytest.mark.parametrize("gate_mode", ["pending", "auto"])
def test_planner_chat_keeps_final_message_and_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_mode: str,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    stage_plan(artifacts, plan_file)
    settle_commits(monkeypatch, artifacts, repo, dirty)
    captured, chat_patch = capturing_chat_patch()
    result = dispatch_with_gate(
        tmp_path,
        artifacts,
        expected_cwds={str(repo), str(linked)},
        gate_mode=gate_mode,
        plan_file=plan_file,
        extra_patches=(chat_patch,),
    )
    assert result is not None and result.adopted
    assert captured
    assert captured[0]["response"] == PLANNER_RESPONSE
    assert "## Proposed Plan Preview" in (captured[0].get("extra_sections") or "")
    assert "# Gate handoff" not in captured[0]["response"]
    for call in captured[1:]:
        assert "# Gate handoff" not in str(call.get("response"))
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    if gate_mode == "pending":
        assert meta.get("gate_id") == "plan-gate"
        assert meta.get("gate_member_agent_name") == "agent-1--gate"
    else:
        assert result.outcome == "completed"


def test_proposal_archive_links_do_not_pollute_planner_obligations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    dirty = dual_dirty(repo, linked)
    record = stage_plan(artifacts, plan_file)
    assert record["dirty_obligations_at_stage"] == []
    settle_commits(monkeypatch, artifacts, repo, dirty)
    result = dispatch_with_gate(
        tmp_path,
        artifacts,
        expected_cwds={str(repo), str(linked)},
        gate_mode="pending",
        plan_file=plan_file,
    )
    assert result is not None and result.adopted
    assert set(commit_shas(artifacts)) == {str(repo), str(linked)}


def test_provider_error_after_stage_does_not_retry_or_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, _linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    stage_plan(artifacts, plan_file)
    ctx, state = make_continuation(tmp_path, artifacts)
    with patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate:
        governed = _dispatch_staged_on_workflow_error(ctx, state)
    assert governed is True
    assert state.loop_outcome == "failed"
    create_gate.assert_not_called()
    assert read_staged_handoff(str(artifacts)) is not None


def test_user_kill_discards_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.user_kill import USER_KILL_INTENT_MARKER

    _repo, _linked, artifacts, plan_file = prepare_dual_repo_env(tmp_path, monkeypatch)
    stage_plan(artifacts, plan_file)
    (artifacts / USER_KILL_INTENT_MARKER).write_text(
        json.dumps(
            {"schema_version": 1, "timestamp": 50.0, "pid": 123, "source": "test"}
        ),
        encoding="utf-8",
    )
    ctx, state = make_continuation(tmp_path, artifacts)
    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.plan_gate_turn.create_plan_gate_turn") as create_gate,
    ):
        outcome = _handle_killed_iteration(ctx, state)
    assert outcome == "killed"
    create_gate.assert_not_called()
    assert read_staged_handoff(str(artifacts)) is None

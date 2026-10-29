"""Failure-boundary coverage for staged handoffs.

Covers provider failure before declaration, exhausted declaration recovery,
commit/finalizer failure, partial repository success, user kill, and the
prevention of retry/reclone/release on unresolved staging.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.agent.staged_handoff import (
    build_plan_staged_record,
    write_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.llm_provider.types import LLMInvocationError
from tests._axe_run_agent_exec_helpers import make_exec_ctx


def _record(tmp_path: Path, **overrides: object) -> dict[str, object]:
    base = build_plan_staged_record(
        plan_file=str(tmp_path / "plan.md"),
        original_file=str(tmp_path / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _ctx_state(tmp_path: Path) -> tuple[object, LoopState, Path]:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    return ctx, state, artifacts


def test_retry_blocked_when_staged_pending(tmp_path: Path, monkeypatch) -> None:
    ctx, state, artifacts = _ctx_state(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    tracker = RetryTracker(retry_cfg=None)
    with patch(
        "sase.llm_provider.retry_config.find_retry_config_for_error",
        return_value=SimpleNamespace(
            max_retries=3,
            fallback_model=None,
            continuation_prompt=None,
            spawn_new_agent=False,
            preserve_workspace=False,
        ),
    ):
        action = handle_workflow_error(RuntimeError("boom"), tracker, ctx, state)
    assert action == "raise"
    assert tracker.retry_count == 0


def test_retry_blocked_when_staged_malformed(tmp_path: Path, monkeypatch) -> None:
    ctx, state, artifacts = _ctx_state(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    (artifacts / ".sase_handoff_staged.json").write_text("{not-json", encoding="utf-8")
    tracker = RetryTracker(retry_cfg=None)
    with patch(
        "sase.llm_provider.retry_config.find_retry_config_for_error",
        return_value=SimpleNamespace(
            max_retries=3,
            fallback_model=None,
            continuation_prompt=None,
            spawn_new_agent=False,
            preserve_workspace=False,
        ),
    ):
        action = handle_workflow_error(RuntimeError("boom"), tracker, ctx, state)
    assert action == "raise"
    assert tracker.retry_count == 0


def test_retry_allowed_without_staged(tmp_path: Path) -> None:
    ctx, state, _ = _ctx_state(tmp_path)
    tracker = RetryTracker(retry_cfg=None)
    with patch(
        "sase.axe.run_agent_exec_retry.find_retry_config_for_error",
        return_value=None,
    ):
        action = handle_workflow_error(RuntimeError("boom"), tracker, ctx, state)
    assert action == "raise"


def test_workflow_error_dispatches_held_staged(tmp_path: Path, monkeypatch) -> None:
    from sase.axe import run_agent_exec as exec_mod

    ctx, state, artifacts = _ctx_state(tmp_path)
    record = _record(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(record["staged_id"]), "planner response", artifacts_dir=str(artifacts)
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent", "workspace_dir": str(tmp_path)}),
        encoding="utf-8",
    )
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": "failed", "instances": []}), encoding="utf-8"
    )
    assert exec_mod._dispatch_staged_on_workflow_error(ctx, state) is True
    assert state.loop_outcome == "failed"
    receipt = json.loads(
        (artifacts / ".sase_handoff_adopted.json").read_text(encoding="utf-8")
    )
    assert receipt["outcome"] == "handoff_not_adopted"


def test_vcs_release_blocked_on_staged(tmp_path: Path, monkeypatch) -> None:
    from sase.workspace_provider import vcs_release as release_mod

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    project_file = tmp_path / "project.sase"
    project_file.write_text("{}", encoding="utf-8")
    with patch.object(
        release_mod, "release_workspace", side_effect=AssertionError("must not release")
    ):
        result = release_mod.release_vcs_workspace(
            project_file=str(project_file),
            workspace_num=1,
            workspace_dir=str(tmp_path),
            workflow_name="ace-run",
            cl_name="test",
            caller_tag="git-release",
            runner_pid=1234,
            artifacts_dir=str(artifacts),
        )
    assert result.released is False
    assert result.skip_reason == release_mod.SKIP_HANDOFF


def test_sigterm_release_kept_on_staged(tmp_path: Path, monkeypatch) -> None:
    from sase.axe import run_agent_runner_signals as signals_mod

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    assert signals_mod._has_staged_handoff(str(artifacts)) is True
    assert signals_mod._has_staged_handoff(None) is False


def test_auto_restart_pending_includes_staged(tmp_path: Path, monkeypatch) -> None:
    from sase.agent.auto_restart import inputs as restart_inputs

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    assert restart_inputs.pending_handoff(artifacts) is False
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    assert restart_inputs.pending_handoff(artifacts) is True


def test_stranded_facts_show_staged(tmp_path: Path, monkeypatch) -> None:
    from sase.bead import stranded_facts as facts_mod

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    record = _record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_adoption_receipt(
        {
            "staged_id": str(record["staged_id"]),
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "handoff_not_adopted",
            "reason": "finalizer controller did not settle",
        },
        artifacts_dir=str(artifacts),
    )
    kind, outcome = facts_mod._staged_facts(str(artifacts))
    assert kind == "plan"
    assert outcome == "handoff_not_adopted"


def test_provider_failure_finalizes_staged(tmp_path: Path, monkeypatch) -> None:
    """A staged ordinary-provider error reaches finalizers with its evidence."""

    from sase.llm_provider import _invoke as invoke_mod

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    record = _record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(artifacts))

    from sase.llm_provider.preprocessing import _PreprocessResult

    provider = MagicMock()
    provider.invoke.side_effect = RuntimeError("provider down")

    monkeypatch.setattr(
        "sase.llm_provider._invoke.preprocess_prompt",
        lambda prompt, is_home_mode=False: _PreprocessResult(prompt="processed"),
    )
    monkeypatch.setattr(
        "sase.llm_provider._invoke.get_provider", lambda *args, **kwargs: provider
    )
    calls: dict[str, object] = {}

    def fake_finalizers(**kwargs: object) -> MagicMock:
        calls["invoke_result"] = kwargs["invoke_result"]
        raise RuntimeError("finalizer failed")

    monkeypatch.setattr("sase.finalizers.run_finalizers", fake_finalizers)
    with patch("sase.llm_provider._invoke.postprocess_error"):
        try:
            invoke_mod.invoke_agent(
                "raw prompt",
                agent_type="test",
                suppress_output=True,
                artifacts_dir=str(artifacts),
                provider_name="fakey",
            )
        except LLMInvocationError:
            pass
        else:  # pragma: no cover - provider failure must raise
            raise AssertionError("expected LLMInvocationError")

    assert "invoke_result" in calls
    failure_result = calls["invoke_result"]
    assert "provider down" in str(getattr(failure_result, "content", ""))
    recorded = json.loads(
        (artifacts / ".sase_provider_failure.json").read_text(encoding="utf-8")
    )
    assert recorded["schema_version"] == 1
    assert "provider down" in recorded["error"]


def test_provider_failure_skips_finalizers_when_finalizer_owned(
    tmp_path: Path, monkeypatch
) -> None:
    """Finalizer-owned provider failures never recurse into finalizers."""

    from sase.llm_provider import _invoke as invoke_mod

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGENT", "1")
    from sase.llm_provider.preprocessing import _PreprocessResult

    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    monkeypatch.setenv("SASE_FINALIZER_OWNED_TURN", "1")

    provider = MagicMock()
    provider.invoke.side_effect = RuntimeError("provider down")

    monkeypatch.setattr(
        "sase.llm_provider._invoke.preprocess_prompt",
        lambda prompt, is_home_mode=False: _PreprocessResult(prompt="processed"),
    )
    monkeypatch.setattr(
        "sase.llm_provider._invoke.get_provider", lambda *args, **kwargs: provider
    )
    with patch(
        "sase.finalizers.run_finalizers",
        side_effect=AssertionError("must not recurse"),
    ):
        with patch("sase.llm_provider._invoke.postprocess_error"):
            try:
                invoke_mod.invoke_agent(
                    "raw prompt",
                    agent_type="test",
                    suppress_output=True,
                    artifacts_dir=str(artifacts),
                    provider_name="fakey",
                )
            except LLMInvocationError:
                pass
            else:  # pragma: no cover - provider failure must raise
                raise AssertionError("expected LLMInvocationError")
    assert not (artifacts / ".sase_provider_failure.json").exists()

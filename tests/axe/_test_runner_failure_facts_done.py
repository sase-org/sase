"""Runner error and done marker integration tests for failure facts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import runner_lifecycle_phase as lifecycle_mod
from sase.axe.run_agent_markers import build_done_marker
from sase.axe.run_agent_runner_errors import RunnerErrorContext, record_runner_error
from sase.axe.run_agent_runner_finalize import write_error_done_marker
from sase.axe._run_agent_runner_shutdown_markers import ensure_failed_done_marker
from sase.axe.run_agent_exec import LoopState, _finalize_loop
from sase.axe.run_agent_exec_retry import RetryTracker
from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._run_agent_runner_lifecycle_helpers import make_context, make_state
from tests.axe._runner_failure_facts_helpers import clean_lifecycle as clean_lifecycle


# --- done.json facts ---------------------------------------------------------


def _error_context(tmp_path: Path) -> RunnerErrorContext:
    return RunnerErrorContext(
        current_artifacts_dir=str(tmp_path),
        cl_name="cl",
        project_file="/tmp/project.sase",
        timestamp="20261009_120000",
        artifacts_timestamp="20261009120000",
        workspace_num=1,
        workspace_dir=str(tmp_path / "workspace"),
        output_path=str(tmp_path / "output.log"),
        agent_name="worker",
        agent_model="model",
        agent_llm_provider="provider",
        agent_vcs_provider=None,
        agent_hidden=False,
    )


def _record_runner_error_output(
    tmp_path: Path, exc: BaseException, capsys: pytest.CaptureFixture[str]
) -> str:
    kills = SimpleNamespace(labels=MagicMock(return_value=MagicMock()))
    record_runner_error(
        exc,
        context=_error_context(tmp_path),
        write_error_done_marker=MagicMock(),
        agent_kills=kills,
        message_prefix="Error running agent",
    )
    return capsys.readouterr().err


def test_runner_error_uses_typed_transient_lookup_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.agent.names._lookup_named import AgentNamedLookupUnavailable

    error = AgentNamedLookupUnavailable(
        availability="busy",
        source="artifact_index",
        diagnostic="database is locked",
    )
    output = _record_runner_error_output(tmp_path, error, capsys)
    assert "transient" in output
    assert "database is locked" in output
    assert "safe once the index is idle" in output
    assert "This runner failure is retryable" not in output


@pytest.mark.parametrize("availability", ["corrupt", "stale_schema", "missing"])
def test_runner_error_recommends_index_repair_for_nontransient_lookup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], availability: str
) -> None:
    from sase.agent.names._lookup_named import AgentNamedLookupUnavailable

    error = AgentNamedLookupUnavailable(
        availability=availability,
        source="artifact_index",
        diagnostic="index cannot answer",
    )
    output = _record_runner_error_output(tmp_path, error, capsys)
    assert f"availability={availability}" in output
    assert "sase agent index status" in output
    assert "sase agent index gc" in output
    assert "sase agent index rebuild" in output
    assert "This runner failure is retryable" not in output


def test_runner_error_does_not_show_provider_hint_for_other_host_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    error = RuntimeError("sase stitch create failed: remote Internal Server Error")
    output = _record_runner_error_output(tmp_path, error, capsys)
    assert "This runner failure is retryable" not in output


def test_runner_error_keeps_provider_hint_for_provider_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _record_runner_error_output(
        tmp_path, RuntimeError("UNAVAILABLE: provider RPC failed"), capsys
    )
    assert "This runner failure is retryable" in output


def test_raised_failure_writes_facts_to_done_json(tmp_path: Path) -> None:
    lifecycle_mod.mark_lifecycle_phase(None, "waiting")
    kills = SimpleNamespace(labels=MagicMock(return_value=MagicMock()))
    try:
        raise ImportError("cannot import name 'gone' from 'sase.somewhere'")
    except ImportError as exc:
        record_runner_error(
            exc,
            context=_error_context(tmp_path),
            write_error_done_marker=write_error_done_marker,
            agent_kills=kills,
            message_prefix="Error running agent",
        )
    done = json.loads((tmp_path / "done.json").read_text(encoding="utf-8"))
    facts = done["failure_facts"]
    assert facts["lifecycle_phase"] == "waiting"
    assert facts["skew_suspect"] is True
    assert facts["import_error"]["missing_symbol"] == "gone"
    assert facts["exception_chain"][0]["type"] == "ImportError"


def test_shutdown_path_writes_phase_only_facts(tmp_path: Path) -> None:
    lifecycle_mod.mark_lifecycle_phase(None, "finalizing")
    context = make_context(tmp_path)
    state = make_state(
        current_artifacts_dir=str(tmp_path),
        error_summary="RuntimeError: boom",
        error_traceback_str="",
    )
    ensure_failed_done_marker(
        context=context,
        state=state,
        write_error_done_marker=write_error_done_marker,
    )
    done = json.loads((tmp_path / "done.json").read_text(encoding="utf-8"))
    assert done["failure_facts"]["lifecycle_phase"] == "finalizing"
    assert done["failure_facts"]["exception_chain"] == []
    assert done["failure_facts"]["skew_suspect"] is False


def test_finalize_loop_failed_outcome_writes_phase_facts(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="failed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    lifecycle_mod.mark_lifecycle_phase(None, "provider_done")
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
    ):
        _finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)

    done = json.loads(
        (Path(ctx.artifacts_dir) / "done.json").read_text(encoding="utf-8")
    )
    assert done["outcome"] == "failed"
    assert done["failure_facts"]["lifecycle_phase"] == "finalizing"
    assert done["failure_facts"]["skew_suspect"] is False


def test_finalize_loop_handoff_finalizer_failure_keeps_handoff_facts(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    Path(ctx.artifacts_dir, "finalizer_result.json").write_text(
        json.dumps({"status": "failed"}), encoding="utf-8"
    )
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="monitored",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    lifecycle_mod.mark_lifecycle_phase(None, "handoff")
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
    ):
        _finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)

    done = json.loads(
        (Path(ctx.artifacts_dir) / "done.json").read_text(encoding="utf-8")
    )
    assert done["outcome"] == "failed"
    assert done["failure_facts"]["lifecycle_phase"] == "handoff"


def test_nonfailure_finalize_outcome_omits_failure_facts(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="stopped",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
    ):
        _finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)

    done = json.loads(
        (Path(ctx.artifacts_dir) / "done.json").read_text(encoding="utf-8")
    )
    assert done["outcome"] == "stopped"
    assert "failure_facts" not in done


def test_build_done_marker_omits_facts_by_default() -> None:
    marker = build_done_marker(
        "cl",
        "/tmp/project.sase",
        "20261009_120000",
        "20261009120000",
        1,
        "/tmp/workspace",
        "/tmp/output.log",
        "failed",
        error="RuntimeError: boom",
        traceback_str="trace",
    )
    assert "failure_facts" not in marker

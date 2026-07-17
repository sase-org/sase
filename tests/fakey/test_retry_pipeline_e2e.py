"""End-to-end retry coverage through the real executor and fakey subprocess.

The spawn-on-retry case exercises the production handoff builder and parent
finalization, but substitutes the final detached launcher call. A fully detached
runner needs daemon-owned workspace claims and process cleanup outside pytest's
isolated sandbox; launcher lifecycle itself remains covered by its dedicated
tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe import runner_utils
from sase.axe.run_agent_exec import run_execution_loop
from sase.xprompt.workflow_models import WorkflowExecutionError

from tests.fakey.harness import (
    FakeyRetryHarness,
    retryable_failure,
    successful_attempt,
)


def test_execution_override_runs_fakey_with_requested_model_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_LLM_EXEC_PROVIDER", "fakey")
    requested_meta = {
        "name": "override-e2e",
        "model": "opus",
        "llm_provider": "claude",
        "workspace_dir": str(harness.workspace),
    }
    (harness.artifacts / "agent_meta.json").write_text(
        json.dumps(requested_meta, indent=2), encoding="utf-8"
    )
    context = harness.context()
    context.agent_name = "override-e2e"
    context.agent_model = "opus"
    context.agent_llm_provider = "claude"
    context.agent_meta = requested_meta

    result = run_execution_loop(
        context,
        "%model:opus\nInspect the parser and report progress.",
    )

    assert result.success is True
    invocation = harness.invocation_records()[0]
    assert invocation["model"] == "opus"
    assert invocation["outcome"]["status"] == "succeeded"
    assert harness.agent_meta() == {
        **requested_meta,
        "exec_llm_provider": "fakey",
    }
    assert harness.done_marker()["model"] == "opus"
    assert harness.done_marker()["llm_provider"] == "claude"
    assert harness.done_marker()["exec_llm_provider"] == "fakey"


def test_retryable_failure_then_success_records_lifecycle_and_nudge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(tmp_path, monkeypatch, wait_times=[1])
    harness.use_scenario(
        monkeypatch,
        [retryable_failure(), successful_attempt("second attempt succeeded")],
    )

    handle = harness.run_in_background("Keep the original task intact.")
    try:
        retrying = harness.wait_for_retry_state("retrying")
        assert retrying.retry_count == 1
        assert retrying.max_retries == 1
        result = handle.finish()
    finally:
        if handle.thread.is_alive():
            runner_utils._killed_state["killed"] = True
            handle.thread.join(5)
        runner_utils.reset_killed()

    assert result.success is True
    assert harness.retry_state() is None
    records = harness.invocation_records()
    assert len(records) == 2
    assert records[0]["outcome"]["status"] == "failed"
    assert records[1]["outcome"]["status"] == "succeeded"
    retry_prompt = records[1]["prompt"]
    assert "Your previous attempt hit a model context limit" in retry_prompt
    assert "Keep the original task intact." in retry_prompt
    done = harness.done_marker()
    assert done["outcome"] == "completed"
    assert done["retry_metadata"]["retry_count"] == 1


def test_retries_exhausted_raises_after_snapshotting_terminal_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(tmp_path, monkeypatch, max_retries=1)
    harness.use_scenario(
        monkeypatch,
        [retryable_failure("first failure"), retryable_failure("still down")],
    )

    with pytest.raises(WorkflowExecutionError, match="FAKEY-RETRYABLE"):
        harness.run()

    records = harness.invocation_records()
    assert len(records) == 2
    assert [record["outcome"]["status"] for record in records] == [
        "failed",
        "failed",
    ]
    assert harness.attempt_meta(1)["status"] == "failed"
    assert harness.attempt_meta(2)["status"] == "raised"
    assert not (harness.artifacts / "done.json").exists()


def test_fallback_switches_the_real_subprocess_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        max_retries=0,
        fallback_model="fakey-small",
    )
    harness.use_scenario(
        monkeypatch,
        [retryable_failure("primary unavailable"), successful_attempt("fallback")],
    )

    result = harness.run()

    assert result.success is True
    records = harness.invocation_records()
    assert [record["model"] for record in records] == [
        "fakey-large",
        "fakey-small",
    ]
    done = harness.done_marker()
    assert done["retry_metadata"]["used_fallback"] is True
    assert done["retry_metadata"]["fallback_model"] == "fakey-small"


def test_spawn_new_agent_writes_handoff_and_terminal_parent_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(
        tmp_path,
        monkeypatch,
        max_retries=1,
        spawn_new_agent=True,
    )
    harness.use_scenario(monkeypatch, [retryable_failure("handoff needed")])

    with (
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260710_120001"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=SimpleNamespace(pid=4242),
        ) as spawn,
    ):
        result = harness.run("Resume this task in the child.")

    assert result.outcome == "failed_retried"
    handoff = harness.retry_handoff()
    assert handoff["original_prompt"].endswith("Resume this task in the child.")
    assert handoff["retry_attempt"] == 1
    assert handoff["chain_root_timestamp"] == harness.artifacts.name
    meta = harness.agent_meta()
    assert meta["retry_terminal"] is True
    assert meta["retried_as_timestamp"] == "20260710120001"
    assert harness.done_marker()["outcome"] == "failed"
    child_prompt = spawn.call_args.kwargs["prompt"]
    assert "#fork:fakey-e2e" in child_prompt
    assert "Resume this task in the child." in child_prompt


def test_kill_during_retry_wait_stops_before_another_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(tmp_path, monkeypatch, max_retries=2, wait_times=[5])
    harness.use_scenario(
        monkeypatch,
        [retryable_failure("wait before retry"), successful_attempt("must not run")],
    )

    handle = harness.run_in_background()
    try:
        harness.wait_for_retry_state("retrying")
        runner_utils._killed_state["killed"] = True
        result = handle.finish(timeout=3)
    finally:
        if handle.thread.is_alive():
            runner_utils._killed_state["killed"] = True
            handle.thread.join(5)
        runner_utils.reset_killed()

    assert result.outcome == "killed"
    assert len(harness.invocation_records()) == 1
    assert harness.done_marker()["outcome"] == "killed"
    assert harness.retry_state() is None

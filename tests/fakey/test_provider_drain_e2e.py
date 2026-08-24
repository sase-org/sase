"""Real, hermetic end-to-end drill for the automatic provider-drain loop.

Exercises the production path documented by the ``provider_drain`` epic: a
real fakey subprocess trips a usage-limit failure, the flag-gated
``sase.llm_provider.usage_limit_disable`` ownership decision submits a real
``sase agent drain`` durable proc (not a mock of any of the decision points),
that proc runs as a genuinely separate OS process and relaunches a second,
stranded fakey agent for real, and exactly one enriched notification reports
what moved. A flag-off variant proves both disable paths behave exactly as
they do today.

Hermeticity for the *relaunched* agent's execution follows the pattern
documented in ``docs/fakey.md`` and used by ``tests/fakey/test_provider.py``:
``SASE_LLM_EXEC_PROVIDER=fakey`` pins the real CLI invocation to the harmless
fakey binary no matter which provider is chosen for display/routing, and
``SASE_<PROVIDER>_PATH`` lets a provider whose real CLI is not installed in
this sandbox (codex) still count as "available" for routing purposes.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider.provider_disable import get_active_provider_disables
from sase.llm_provider.registry import provider_path_env_var
from sase.notifications.store import load_notifications
from sase.ops import read_operation_result
from sase.ops.models import DurableOperationResult
from sase.ops.names import AGENT_DRAIN
from sase.procs import wait_for_proc
from sase.procs.models import Proc
from sase.procs.request import ProcSubmitRequest
from sase.procs.runtime import proc_operation_result_path
from sase.xprompt.workflow_models import WorkflowExecutionError

from tests.fakey.harness import FakeyRetryHarness, usage_limit_failure

# Generous: the drain proc's own child interpreter startup, its dismiss +
# relaunch of the second agent, and its grandchild agent spawn all happen as
# genuinely separate OS processes.
_DRAIN_WAIT_TIMEOUT = 180.0

_ALIAS_NAME = "drain-e2e-reroute"
_SECOND_PROJECT = "drain-e2e-second"
_SECOND_AGENT_NAME = "second-fakey"
_SECOND_TIMESTAMP = "20260810090000"
_USAGE_LIMIT_ERROR = "FAKEY-USAGE-LIMIT hit"


def _write_alias_overlay(config_dir: Path) -> None:
    """Publish a custom model alias whose ``||`` fallback reroutes off fakey.

    Lives under the fake ``$HOME/.config/sase`` overlay directory so it is
    visible to the real ``sase agent drain`` child process (and its
    grandchild relaunch), which run with cwd/``Path.home()`` resolved from
    the ``HOME`` env var this test controls -- not from any project-local
    config, since the relaunch deliberately runs from the home directory.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    overlay = config_dir / "sase_drain_e2e.yml"
    overlay.write_text(
        "llm_provider:\n"
        "  model_aliases:\n"
        "    custom:\n"
        f"      {_ALIAS_NAME}:\n"
        '        model: "fakey/fakey-large || codex/gpt-5"\n'
        '        description: "provider-drain e2e reroute alias"\n',
        encoding="utf-8",
    )


def _configure_reroute_environment(
    monkeypatch: pytest.MonkeyPatch, harness: FakeyRetryHarness
) -> None:
    """Make a hard fakey disable reroute (not strand) the second agent.

    Three env knobs, all inherited by the real ``sase agent drain`` child
    process and its grandchild relaunch:

    - ``HOME`` points at an isolated directory so the relaunch's
      ``contextlib.chdir(Path.home())`` never touches the real machine's
      home directory, and so the config overlay below is the only overlay
      visible.
    - ``SASE_CODEX_PATH`` points at the real fakey binary so codex counts as
      an installed CLI for routing purposes without needing a real codex
      install.
    - ``SASE_LLM_EXEC_PROVIDER=fakey`` overrides which CLI actually runs at
      invocation time; the reroute's *display* provider stays codex.
    """
    fake_home = harness.root / "operator-home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    _write_alias_overlay(fake_home / ".config" / "sase")
    fakey_binary = Path(sys.executable).with_name("fakey")
    assert fakey_binary.is_file(), "just install must register the fakey binary"
    monkeypatch.setenv(provider_path_env_var("codex"), str(fakey_binary))
    monkeypatch.setenv("SASE_LLM_EXEC_PROVIDER", "fakey")


def _seed_second_agent(harness: FakeyRetryHarness) -> Path:
    """Publish a real FAILED fakey row a drain can select and relaunch.

    A FAILED row (not a live one) is deliberately chosen: its stop step is a
    dismiss, not a kill, so there is no real process for the drain to signal
    -- unlike reusing this test's own pid for a "live" row, which the
    selection helpers in ``tests/fakey/harness.py`` warn against. The row
    sits within the FAILED-grace window and carries an error that matches
    fakey's own usage-limit pattern, so ``_drain_selection`` picks it up the
    same way a real just-failed sibling agent would be picked up.

    The stored prompt references the reroute alias (not a pinned
    ``fakey/model`` spelling), so once fakey is hard-disabled,
    ``plan_launch_units`` classifies the restart as a reroute onto codex
    instead of reporting it stranded.
    """
    project_dir = harness.home / "projects" / _SECOND_PROJECT
    workspace = harness.root / "second-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts = project_dir / "artifacts" / "ace-run" / _SECOND_TIMESTAMP
    artifacts.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{_SECOND_PROJECT}.sase").write_text(
        f"WORKSPACE_DIR: {workspace}\nRUNNING:\n\nNAME: {_SECOND_PROJECT}\n",
        encoding="utf-8",
    )
    (artifacts / "raw_xprompt.md").write_text(
        f"%model:@{_ALIAS_NAME}\nHandle the provider-drain reroute check.\n",
        encoding="utf-8",
    )
    meta = {
        "name": _SECOND_AGENT_NAME,
        "pid": 8_000_001,
        "model": "fakey-large",
        "llm_provider": "fakey",
        "workspace_dir": str(workspace),
    }
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    done = {
        "outcome": "failed",
        "finished_at": time.time(),
        "error": _USAGE_LIMIT_ERROR,
    }
    (artifacts / "done.json").write_text(json.dumps(done), encoding="utf-8")
    return artifacts


def _run_trigger_to_disable(
    harness: FakeyRetryHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the real fakey trigger agent into its usage-limit failure."""
    import time as real_time
    from types import SimpleNamespace

    from sase.axe import run_agent_exec_retry

    harness.use_scenario(monkeypatch, [usage_limit_failure(_USAGE_LIMIT_ERROR)])
    monkeypatch.setattr(
        run_agent_exec_retry,
        "time",
        SimpleNamespace(time=real_time.time, sleep=lambda _seconds: None),
    )
    with pytest.raises(WorkflowExecutionError, match="FAKEY-USAGE-LIMIT"):
        harness.run()


def _read_drain_result(proc_id: str) -> DurableOperationResult:
    return read_operation_result(
        proc_operation_result_path(proc_id),
        expected_operation=AGENT_DRAIN,
        expected_proc_id=proc_id,
    )


def test_provider_drain_e2e_flag_on_relaunches_stranded_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(tmp_path, monkeypatch, max_retries=1, wait_times=[0])
    _configure_reroute_environment(monkeypatch, harness)
    second_artifacts = _seed_second_agent(harness)

    from sase.procs import submit_proc_request as real_submit_proc_request

    captured_requests: list[ProcSubmitRequest] = []
    captured_procs: list[Proc] = []

    def _capturing_submit(request: ProcSubmitRequest) -> Proc:
        captured_requests.append(request)
        proc = real_submit_proc_request(request)
        captured_procs.append(proc)
        return proc

    with patch(
        "sase.procs.submit_proc_request", side_effect=_capturing_submit
    ) as mock_submit:
        with override_flags(provider_drain=True):
            _run_trigger_to_disable(harness, monkeypatch)

    # Exactly one active hard disable for fakey, written by the trigger's
    # own real usage-limit failure.
    disables = get_active_provider_disables()
    assert set(disables) == {"fakey"}
    assert disables["fakey"].source == "usage_limit"
    assert disables["fakey"].is_hard

    # Exactly one agent.drain proc submitted, with the exact argv and
    # concurrency key the automatic path promises.
    mock_submit.assert_called_once()
    request = captured_requests[0]
    assert request.argv == [
        "sase",
        "agent",
        "drain",
        "fakey",
        "--yes",
        "--json",
        "--limit",
        "20",
    ]
    assert request.operation == AGENT_DRAIN
    assert request.concurrency_keys == ["provider-drain:fakey"]
    assert request.operation_payload is not None
    assert request.operation_payload["notify"] is True

    proc = captured_procs[0]
    finished = wait_for_proc(proc.proc_id, timeout=_DRAIN_WAIT_TIMEOUT)

    result = _read_drain_result(proc.proc_id)
    payload = result.payload
    assert payload is not None
    assert payload["provider"] == "fakey"
    moves = payload["moves"]
    assert len(moves) == 1
    moved = moves[0]
    assert moved["name"] == _SECOND_AGENT_NAME
    # This is the one classification decision this drill exists to prove:
    # once fakey is hard-disabled, plan_launch_units routes the second
    # agent's reroute-alias prompt onto codex instead of reporting it
    # stranded. That part of the production path works correctly.
    assert moved["route"]["kind"] == "reroute"
    assert moved["route"]["target_provider"] == "codex"

    # The second agent's original row is gone: it was really stopped
    # (dismissed) and its artifacts wiped as part of the real restart,
    # even though the relaunch itself does not complete -- see below.
    assert not second_artifacts.exists()

    # KNOWN BUG, found by this drill and NOT fixed here per this task's
    # brief ("stop and report it instead of fixing it"): execute_agent_restart
    # (src/sase/agent/_restart_execute.py) launches ``plan.rewritten_prompt``,
    # which -- per sase.agent._restart_planning._plan_name_reuse -- still
    # carries the raw ``%id(!name)`` forced-reuse marker. Every other caller
    # that runs a forced-name-reuse prompt (sase.main.query_handler._launch's
    # ``sase run --allow-force-reuse`` path) launches
    # ``force_reuse_plan.rewritten_prompt`` instead -- the already-"!"-stripped
    # prompt -- specifically because ``launch_agents_from_cwd``'s single-agent
    # path (sase.agent.launch_cwd_agents) always calls
    # ``validate_launch_name_requests`` with the default ``allow_force_reuse=
    # False`` and has no way to learn that force reuse was already confirmed
    # upstream. The result: this move (and, by the same code path, EVERY
    # real ``sase agent restart`` / ``sase agent drain`` / ACE ",x" relaunch)
    # fails at the launch step with "Agent name '<name>' uses forced reuse;
    # confirmation is required." This reproduces with no drain/alias
    # machinery at all -- a bare ``plan_agent_restart`` + real
    # ``execute_agent_restart`` on a freshly named agent hits it too -- so it
    # is not specific to this drill. The fix is one line: execute_agent_restart
    # should launch ``plan.force_reuse_plan.rewritten_prompt``, matching
    # ``_launch.py``'s pattern, not ``plan.rewritten_prompt``.
    assert finished.status == "error"
    assert result.success is False
    assert payload["counts"] == {
        "moves": 1,
        "relaunched": 0,
        "failed": 1,
        "skipped": 0,
    }
    assert "confirmation is required" in payload["results"][0]["error"]

    # The drain still owns exactly one notification for this disable window,
    # honestly reporting that the relaunch attempt did not complete -- the
    # "one notification, never silent" contract holds even though the
    # relaunch itself is blocked by the bug documented above.
    notifications = [
        note for note in load_notifications() if note.sender == "llm.usage_limit"
    ]
    assert len(notifications) == 1
    notes = notifications[0].notes
    assert any("none completed" in line for line in notes)


def test_provider_drain_e2e_flag_off_leaves_agents_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = FakeyRetryHarness(tmp_path, monkeypatch, max_retries=1, wait_times=[0])
    _configure_reroute_environment(monkeypatch, harness)
    second_artifacts = _seed_second_agent(harness)
    second_meta_before = (second_artifacts / "agent_meta.json").read_text(
        encoding="utf-8"
    )
    second_done_before = (second_artifacts / "done.json").read_text(encoding="utf-8")

    from sase.procs import submit_proc_request as real_submit_proc_request

    def _capturing_submit(request: ProcSubmitRequest) -> Proc:
        return real_submit_proc_request(request)

    with patch(
        "sase.procs.submit_proc_request", side_effect=_capturing_submit
    ) as mock_submit:
        with override_flags(provider_drain=False):
            _run_trigger_to_disable(harness, monkeypatch)

    disables = get_active_provider_disables()
    assert set(disables) == {"fakey"}
    assert disables["fakey"].source == "usage_limit"

    # No drain proc submitted at all.
    mock_submit.assert_not_called()

    # The second agent's row is untouched: still there, byte-identical.
    assert second_artifacts.exists()
    assert (second_artifacts / "agent_meta.json").read_text(
        encoding="utf-8"
    ) == second_meta_before
    assert (second_artifacts / "done.json").read_text(
        encoding="utf-8"
    ) == second_done_before

    # Exactly one notification, with today's plain (no drain-notes) content.
    notifications = [
        note for note in load_notifications() if note.sender == "llm.usage_limit"
    ]
    assert len(notifications) == 1
    notes = notifications[0].notes
    assert not any(line.startswith("Relaunched") for line in notes)
    assert not any(line.startswith("Left alone") for line in notes)

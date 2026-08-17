"""Reusable real-subprocess harness for fakey retry-pipeline tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
import yaml  # type: ignore[import-untyped]

from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop
from sase.axe.run_agent_exec_types import AgentExecResult
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.llm_provider.retry_config import RetryState
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT


_CONTROL_ENV = (
    "FAKEY_DELAY",
    "FAKEY_EXIT_CODE",
    "FAKEY_FAIL_MESSAGE",
    "FAKEY_FAIL_TIMES",
    "FAKEY_REPLY",
    "FAKEY_SCENARIO",
    "FAKEY_STATE_DIR",
    "SASE_ARTIFACTS_DIR",
    "SASE_COMMIT_METHOD",
    "SASE_FAKEY_LARGE_ARGS",
    "SASE_FAKEY_SMALL_ARGS",
    "SASE_LLM_LARGE_ARGS",
    "SASE_LLM_SMALL_ARGS",
    "SASE_LLM_EXEC_PROVIDER",
    "SASE_MODEL_OVERRIDE",
)

_CANONICAL_VISUAL_TRACEBACK = """Traceback (most recent call last):
  File "/workspace/sase/src/sase/llm_provider/_invoke.py", line 261, in invoke_agent
    invoke_result = provider.invoke(query, options=invocation_options)
  File "/workspace/sase/src/sase/llm_provider/_plugin_manager.py", line 31, in invoke
    return plugin.invoke(query, options)
sase.llm_provider.errors.LLMInvocationError: temporary fakey outage"""


@dataclass(frozen=True)
class FakeyBarrier:
    """A pair of files suitable for fakey ``signal``/``wait_for`` steps."""

    started: Path
    release: Path
    timeout: float

    def steps(self) -> list[dict[str, object]]:
        return [
            {"signal": str(self.started)},
            {"wait_for": {"path": str(self.release), "timeout": self.timeout}},
        ]

    def wait_until_started(self, timeout: float = LOAD_TOLERANT_TIMEOUT) -> None:
        _wait_for_condition(
            self.started.exists, timeout, f"fakey barrier {self.started}"
        )

    def open(self) -> None:
        self.release.parent.mkdir(parents=True, exist_ok=True)
        self.release.touch()


@dataclass
class ExecutionHandle:
    """A bounded background ``run_execution_loop`` invocation."""

    thread: threading.Thread
    _results: list[AgentExecResult] = field(default_factory=list)
    _errors: list[BaseException] = field(default_factory=list)

    def finish(self, timeout: float = LOAD_TOLERANT_TIMEOUT) -> AgentExecResult:
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise TimeoutError("retry execution did not finish before its timeout")
        if self._errors:
            raise self._errors[0]
        assert len(self._results) == 1
        return self._results[0]


class FakeyRetryHarness:
    """Own an isolated SASE home, artifacts tree, scenario, and retry config."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        max_retries: int = 1,
        wait_times: list[int] | None = None,
        fallback_model: str | None = None,
        spawn_new_agent: bool = False,
        expose_to_agent_loader: bool = False,
        artifacts_timestamp: str = "20260710120000",
        is_home_mode: bool = False,
    ) -> None:
        self.repo_root = Path.cwd()
        self.root = tmp_path
        self.home = tmp_path / "sase-home"
        self.workspace = tmp_path / "workspace"
        self.artifacts_timestamp = artifacts_timestamp
        self.is_home_mode = is_home_mode
        self.project_name = "home" if is_home_mode else "fakey-e2e"
        if expose_to_agent_loader:
            self.project_dir = self.home / "projects" / self.project_name
            self.artifacts = (
                self.project_dir / "artifacts" / "ace-run" / self.artifacts_timestamp
            )
            self.project_file = self.project_dir / f"{self.project_name}.sase"
        else:
            self.project_dir = tmp_path
            self.artifacts = tmp_path / "artifacts" / self.artifacts_timestamp
            self.project_file = tmp_path / "project.sase"
        self.state_dir = tmp_path / "fakey-state"
        self.scenarios_dir = tmp_path / "scenarios"
        for path in (
            self.home,
            self.workspace,
            self.artifacts,
            self.state_dir,
            self.scenarios_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.project_file.write_text(
            f"WORKSPACE_DIR: {self.workspace}\nRUNNING:\n\nNAME: fakey-e2e\n",
            encoding="utf-8",
        )

        for name in _CONTROL_ENV:
            monkeypatch.delenv(name, raising=False)
        fakey_binary = Path(sys.executable).with_name("fakey")
        assert fakey_binary.is_file(), "just install must register the fakey binary"
        monkeypatch.setenv("SASE_HOME", str(self.home))
        monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "tmp"))
        monkeypatch.setenv("SASE_FAKEY_PATH", str(fakey_binary))
        monkeypatch.setenv("SASE_DISABLE_PRETTIER", "1")
        monkeypatch.setenv("FAKEY_STATE_DIR", str(self.state_dir))
        monkeypatch.chdir(self.workspace)
        self.configure_retry(
            max_retries=max_retries,
            wait_times=wait_times or [0],
            fallback_model=fallback_model,
            spawn_new_agent=spawn_new_agent,
        )

    def configure_retry(
        self,
        *,
        max_retries: int,
        wait_times: list[int],
        fallback_model: str | None = None,
        spawn_new_agent: bool = False,
    ) -> None:
        retry: dict[str, object] = {
            "max_retries": max_retries,
            "wait_times": wait_times,
            "spawn_new_agent": spawn_new_agent,
        }
        if fallback_model is not None:
            retry["fallback_model"] = fallback_model
        config = {"llm_provider": {"retry": {"fakey": retry}}}
        (self.workspace / "sase.yml").write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )

    def write_scenario(
        self,
        attempts: list[dict[str, object]],
        *,
        name: str = "retry",
        **common: object,
    ) -> Path:
        scenario = self.scenarios_dir / f"{name}.yml"
        payload = {"version": 1, **common, "attempts": attempts}
        scenario.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return scenario

    def use_scenario(
        self,
        monkeypatch: pytest.MonkeyPatch,
        attempts: list[dict[str, object]],
        *,
        name: str = "retry",
        **common: object,
    ) -> Path:
        scenario = self.write_scenario(attempts, name=name, **common)
        monkeypatch.setenv("FAKEY_SCENARIO", str(scenario))
        return scenario

    def barrier(
        self, name: str, *, timeout: float = LOAD_TOLERANT_TIMEOUT
    ) -> FakeyBarrier:
        barrier_dir = self.root / "barriers"
        return FakeyBarrier(
            started=barrier_dir / f"{name}.started",
            release=barrier_dir / f"{name}.release",
            timeout=timeout,
        )

    def context(self) -> AgentExecContext:
        return AgentExecContext(
            cl_name="fakey-e2e",
            project_file=str(self.project_file),
            workspace_dir=str(self.workspace),
            output_path=str(self.root / "output.log"),
            workspace_num=1,
            timestamp=_launch_timestamp(self.artifacts_timestamp),
            update_target="",
            project_name=self.project_name,
            is_home_mode=self.is_home_mode,
            artifacts_dir=str(self.artifacts),
            artifacts_timestamp=self.artifacts_timestamp,
            vcs_tag=None,
            agent_name="fakey-e2e",
            agent_model="fakey-large",
            agent_llm_provider="fakey",
            agent_vcs_provider=None,
            agent_hidden=False,
            agent_meta={},
            local_xprompts={},
        )

    def seed_running_agent(self, *, started_at: datetime) -> None:
        """Publish the same active-agent markers consumed by the real loader."""
        meta = {
            "name": "fakey-e2e",
            "pid": os.getpid(),
            "model": "fakey-large",
            "llm_provider": "fakey",
            "workspace_dir": str(self.workspace),
            "run_started_at": started_at.isoformat(),
        }
        (self.artifacts / "agent_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        if self.is_home_mode:
            running = {
                "pid": os.getpid(),
                "cl_name": "fakey-e2e",
                "model": "fakey-large",
                "llm_provider": "fakey",
                "workspace_dir": str(self.workspace),
            }
            (self.artifacts / "running.json").write_text(
                json.dumps(running, indent=2), encoding="utf-8"
            )

    def clear_running_agent(self) -> None:
        (self.artifacts / "running.json").unlink(missing_ok=True)

    def hold_retry_wait(
        self,
        monkeypatch: pytest.MonkeyPatch,
        barrier: FakeyBarrier,
    ) -> None:
        """Replace only the executor's retry sleep with a file barrier."""
        from sase.axe import run_agent_exec_retry

        real_time = time.time

        def wait_for_release(_seconds: float) -> None:
            barrier.started.parent.mkdir(parents=True, exist_ok=True)
            barrier.started.touch()
            _wait_for_condition(
                barrier.release.exists,
                barrier.timeout,
                f"retry-wait barrier {barrier.release}",
            )

        monkeypatch.setattr(
            run_agent_exec_retry,
            "time",
            SimpleNamespace(time=real_time, sleep=wait_for_release),
        )

    def normalize_visual_timestamps(
        self,
        visual_now: datetime,
        *,
        countdown_seconds: int | None = None,
        stopped_at: datetime | None = None,
        artifacts_dir: Path | None = None,
        sentinel_pid: int = 4242,
    ) -> None:
        """Rewrite nondeterministic persisted epochs to visual-clock sentinels."""
        target_dir = artifacts_dir or self.artifacts
        # The countdown renderer compares against ``time.time()`` while the
        # visual clock fixture is a naive local datetime, so preserve that
        # local-time interpretation here.
        visual_epoch = visual_now.timestamp()
        retry_path = target_dir / "retry_state.json"
        if retry_path.is_file():
            retry_state = json.loads(retry_path.read_text(encoding="utf-8"))
            if countdown_seconds is not None:
                retry_state["next_retry_at_epoch"] = visual_epoch + countdown_seconds
            retry_path.write_text(json.dumps(retry_state, indent=2), encoding="utf-8")

        meta_path = target_dir / "agent_meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["pid"] = sentinel_pid
            meta["run_started_at"] = datetime.strptime(
                target_dir.name, "%Y%m%d%H%M%S"
            ).isoformat()
            retry_started = meta.get("retry_started_at")
            if isinstance(retry_started, list):
                meta["retry_started_at"] = [visual_now.isoformat()]
            if stopped_at is not None:
                meta["stopped_at"] = stopped_at.isoformat()
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        running_path = target_dir / "running.json"
        if running_path.is_file():
            running = json.loads(running_path.read_text(encoding="utf-8"))
            running["pid"] = sentinel_pid
            running_path.write_text(json.dumps(running, indent=2), encoding="utf-8")

        workflow_path = target_dir / "workflow_state.json"
        if workflow_path.is_file():
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["pid"] = sentinel_pid
            workflow["start_time"] = datetime.strptime(
                target_dir.name, "%Y%m%d%H%M%S"
            ).isoformat()
            for step in workflow.get("steps", []):
                if not isinstance(step, dict):
                    continue
                error = step.get("error")
                if isinstance(error, str):
                    step["error"] = error.replace(
                        str(self.repo_root), "/workspace/sase"
                    )
                if isinstance(step.get("traceback"), str):
                    step["traceback"] = _CANONICAL_VISUAL_TRACEBACK
            workflow_path.write_text(json.dumps(workflow, indent=2), encoding="utf-8")

        attempt_base_epoch = visual_epoch - 20
        for attempt_index, attempt_path in enumerate(
            sorted((target_dir / "attempts").glob("*/attempt_meta.json"))
        ):
            attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
            attempt["start_epoch"] = attempt_base_epoch + attempt_index * 5
            attempt["end_epoch"] = attempt["start_epoch"] + 1
            attempt_path.write_text(json.dumps(attempt, indent=2), encoding="utf-8")

        # The TUI's first Agents load prefers the persistent artifact index.
        # Rewriting markers here without refreshing that index leaves the
        # real runner PID in the snapshot, so live visual rows load as
        # FAILED or disappear entirely.
        update_agent_artifact_index_for_marker_mutation(target_dir)

    def run_spawn_retry_chain(
        self,
        *,
        child_artifacts_timestamp: str,
        prompt: str = "Exercise the retry pipeline.",
    ) -> Path:
        """Run a real fakey parent failure and child success retry chain."""
        spawned: dict[str, Any] = {}

        def capture_spawn(**kwargs: Any) -> SimpleNamespace:
            spawned.update(kwargs)
            return SimpleNamespace(pid=os.getpid())

        child_launch_timestamp = _launch_timestamp(child_artifacts_timestamp)
        with (
            patch(
                "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
                return_value=[child_launch_timestamp],
            ),
            patch(
                "sase.agent.launcher.spawn_agent_subprocess",
                side_effect=capture_spawn,
            ),
        ):
            parent_result = self.run(prompt)

        assert parent_result.outcome == "failed_retried"
        child_artifacts = self.artifacts.parent / child_artifacts_timestamp
        child_artifacts.mkdir(parents=True, exist_ok=True)
        handoff = self.retry_handoff()
        child_meta = {
            "name": "fakey-e2e",
            "pid": os.getpid(),
            "model": "fakey-large",
            "llm_provider": "fakey",
            "workspace_dir": str(self.workspace),
            "run_started_at": datetime.strptime(
                child_artifacts_timestamp, "%Y%m%d%H%M%S"
            ).isoformat(),
            "retry_of_timestamp": handoff["parent_timestamp"],
            "retry_attempt": handoff["retry_attempt"],
            "retry_chain_root_timestamp": handoff["chain_root_timestamp"],
        }
        (child_artifacts / "agent_meta.json").write_text(
            json.dumps(child_meta, indent=2), encoding="utf-8"
        )
        child_ctx = self.context()
        child_ctx.artifacts_dir = str(child_artifacts)
        child_ctx.artifacts_timestamp = child_artifacts_timestamp
        child_ctx.timestamp = child_launch_timestamp
        child_ctx.agent_meta = child_meta
        child_prompt = str(spawned["prompt"])
        if child_prompt.startswith("#fork:"):
            # The detached runner resolves #fork into transcript context before
            # entering run_execution_loop. This exec-level harness already
            # has the parent's continuation/original prompt in the handoff,
            # so model that boundary by removing only the unresolved directive.
            child_prompt = child_prompt.split("\n\n", 1)[1]
        child_result = run_execution_loop(child_ctx, child_prompt)
        assert child_result.success is True
        return child_artifacts

    def run(self, prompt: str = "Exercise the retry pipeline.") -> AgentExecResult:
        return run_execution_loop(self.context(), f"%model:fakey-large\n{prompt}")

    def run_in_background(
        self, prompt: str = "Exercise the retry pipeline."
    ) -> ExecutionHandle:
        results: list[AgentExecResult] = []
        errors: list[BaseException] = []

        def target() -> None:
            try:
                results.append(self.run(prompt))
            except BaseException as exc:  # noqa: BLE001 - transported to test thread
                errors.append(exc)

        thread = threading.Thread(target=target, name="fakey-retry-e2e", daemon=True)
        handle = ExecutionHandle(thread=thread, _results=results, _errors=errors)
        thread.start()
        return handle

    def retry_state(self) -> RetryState | None:
        return RetryState.read_from(str(self.artifacts))

    def wait_for_retry_state(
        self, status: str, *, timeout: float = LOAD_TOLERANT_TIMEOUT
    ) -> RetryState:
        """Block until the executor publishes ``status``, or the ceiling trips.

        ``retry_state.json`` is transient: it is written on the way into the
        retry wait and cleared on the way out. A caller that lets the executor
        sleep a real interval is racing that window, so callers who need to
        *observe* the retrying state should hold the wait open with
        :meth:`hold_retry_wait` rather than rely on this poll winning the race.
        """
        found: list[RetryState] = []

        def state_matches() -> bool:
            state = self.retry_state()
            if state is not None and state.status == status:
                found.append(state)
                return True
            return False

        _wait_for_condition(state_matches, timeout, f"retry state {status!r}")
        return found[-1]

    def invocation_records(self) -> list[dict[str, Any]]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.state_dir.glob("invocation-*.json"))
        ]

    def done_marker(self) -> dict[str, Any]:
        return json.loads((self.artifacts / "done.json").read_text(encoding="utf-8"))

    def retry_handoff(self) -> dict[str, Any]:
        return json.loads(
            (self.artifacts / "retry_handoff.json").read_text(encoding="utf-8")
        )

    def agent_meta(self) -> dict[str, Any]:
        return json.loads(
            (self.artifacts / "agent_meta.json").read_text(encoding="utf-8")
        )

    def attempt_meta(self, attempt: int) -> dict[str, Any]:
        path = self.artifacts / "attempts" / f"{attempt:02d}" / "attempt_meta.json"
        return json.loads(path.read_text(encoding="utf-8"))


def retryable_failure(message: str = "temporary fakey outage") -> dict[str, object]:
    return {
        "fail": {
            "message": message,
            "retryable": True,
            "exit_code": 1,
            "channel": "stderr",
        }
    }


def usage_limit_failure(message: str = "FAKEY-USAGE-LIMIT hit") -> dict[str, object]:
    """Retryable failure that also trips fakey's usage-limit detector."""
    return retryable_failure(message)


def successful_attempt(reply: str = "fakey recovered") -> dict[str, object]:
    return {"succeed": {"reply": reply}}


def _wait_for_condition(
    predicate: Callable[[], bool], timeout: float, description: str
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    raise TimeoutError(f"timed out waiting for {description}")


def _launch_timestamp(artifacts_timestamp: str) -> str:
    parsed = datetime.strptime(artifacts_timestamp, "%Y%m%d%H%M%S")
    return parsed.strftime("%y%m%d_%H%M%S")

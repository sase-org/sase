"""Reusable real-subprocess harness for fakey retry-pipeline tests."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop
from sase.axe.run_agent_exec_types import AgentExecResult
from sase.llm_provider.retry_config import RetryState


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
    "SASE_MODEL_OVERRIDE",
)


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

    def wait_until_started(self, timeout: float = 5) -> None:
        _wait_until(self.started.exists, timeout, f"fakey barrier {self.started}")

    def open(self) -> None:
        self.release.parent.mkdir(parents=True, exist_ok=True)
        self.release.touch()


@dataclass
class ExecutionHandle:
    """A bounded background ``run_execution_loop`` invocation."""

    thread: threading.Thread
    _results: list[AgentExecResult] = field(default_factory=list)
    _errors: list[BaseException] = field(default_factory=list)

    def finish(self, timeout: float = 10) -> AgentExecResult:
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
    ) -> None:
        self.root = tmp_path
        self.home = tmp_path / "sase-home"
        self.workspace = tmp_path / "workspace"
        self.artifacts = tmp_path / "artifacts" / "20260710120000"
        self.state_dir = tmp_path / "fakey-state"
        self.scenarios_dir = tmp_path / "scenarios"
        self.project_file = tmp_path / "project.sase"
        for path in (
            self.home,
            self.workspace,
            self.artifacts,
            self.state_dir,
            self.scenarios_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.project_file.write_text("", encoding="utf-8")

        for name in _CONTROL_ENV:
            monkeypatch.delenv(name, raising=False)
        fakey_binary = Path(sys.executable).with_name("fakey")
        assert fakey_binary.is_file(), "just install must register the fakey binary"
        monkeypatch.setenv("SASE_HOME", str(self.home))
        monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "tmp"))
        monkeypatch.setenv("SASE_FAKEY_PATH", str(fakey_binary))
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

    def barrier(self, name: str, *, timeout: float = 5) -> FakeyBarrier:
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
            timestamp="260710_120000",
            update_target="",
            project_name="fakey-e2e",
            is_home_mode=False,
            artifacts_dir=str(self.artifacts),
            artifacts_timestamp=self.artifacts.name,
            vcs_tag=None,
            agent_name="fakey-e2e",
            agent_model="fakey-large",
            agent_llm_provider="fakey",
            agent_vcs_provider=None,
            agent_hidden=False,
            agent_meta={},
            local_xprompts={},
        )

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

    def wait_for_retry_state(self, status: str, *, timeout: float = 5) -> RetryState:
        found: list[RetryState] = []

        def state_matches() -> bool:
            state = self.retry_state()
            if state is not None and state.status == status:
                found.append(state)
                return True
            return False

        _wait_until(state_matches, timeout, f"retry state {status!r}")
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


def successful_attempt(reply: str = "fakey recovered") -> dict[str, object]:
    return {"succeed": {"reply": reply}}


def _wait_until(
    predicate: Callable[[], bool], timeout: float, description: str
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError(f"timed out waiting for {description}")

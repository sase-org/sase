"""Shared real-subprocess runner-slot harness for fakey e2e lifecycle tests.

Exercises the production filesystem scan, global flock, marker mutations,
live config reload, and a real bundled ``fakey`` subprocess. The only
shortened production behavior is the two-second parked-agent poll.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from sase.axe import run_agent_wait_slots
from sase.axe.run_agent_markers import record_run_started_at, write_agent_meta
from sase.config import core as config_core
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.llm_provider.fakey import FakeyProvider
from sase.plan_chain import AGENT_FAMILY_PARALLEL_FIELD

_WAIT_TIMEOUT = 30.0
_FAKEY_RELEASE_TIMEOUT = 60.0


@dataclass
class _Agent:
    name: str
    artifacts_dir: Path
    meta: dict[str, object]
    started: Path
    release: Path
    wait_runners: int | None = None
    wait_priority: int | None = None
    queue_weight: float = 1.0
    queue_weight_explicit: bool = False
    crash: bool = False
    killed: bool = False
    thread: threading.Thread | None = None


class _RunnerSlotFakeyHarness:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        cap: int,
    ) -> None:
        self.root = tmp_path
        self.home = tmp_path / "sase-home"
        self.workspace = tmp_path / "workspace"
        self.artifacts_root = (
            self.home / "projects" / "fakey-slots" / "artifacts" / "ace-run"
        )
        self.state_dir = tmp_path / "fakey-state"
        self.config_path = self.workspace / "sase.yml"
        self._errors: list[tuple[str, BaseException]] = []
        self._killed_threads: set[str] = set()
        self._lock = threading.Lock()
        self.claim_order: list[str] = []
        self.active_roots = 0
        self.max_active_roots = 0

        self.artifacts_root.mkdir(parents=True)
        self.workspace.mkdir()
        self.state_dir.mkdir()
        project_file = self.artifacts_root.parents[1] / "fakey-slots.sase"
        project_file.write_text("WORKSPACE_DIR: /tmp/fakey-slots\n", encoding="utf-8")
        self.write_cap(cap)

        fakey_binary = Path(sys.executable).with_name("fakey")
        assert fakey_binary.is_file(), "just install must register the fakey binary"
        monkeypatch.setenv("SASE_HOME", str(self.home))
        monkeypatch.setenv("SASE_FAKEY_PATH", str(fakey_binary))
        monkeypatch.setenv("FAKEY_STATE_DIR", str(self.state_dir))
        monkeypatch.delenv("FAKEY_SCENARIO", raising=False)
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        monkeypatch.chdir(self.workspace)
        monkeypatch.setattr(config_core, "_include_local_config", True)
        monkeypatch.setattr(run_agent_wait_slots, "_RUNNER_SLOT_POLL_INTERVAL", 0.01)
        monkeypatch.setattr(run_agent_wait_slots, "was_killed", self._was_killed)

    def write_cap(self, cap: int) -> None:
        self.config_path.write_text(
            f"max_running_agents: {cap}\n# phase-5-cap-{cap}\n",
            encoding="utf-8",
        )

    def create_agent(
        self,
        index: int,
        *,
        name: str | None = None,
        wait_runners: int | None = None,
        wait_priority: int | None = None,
        queue_weight: float = 1.0,
        queue_weight_explicit: bool = False,
        parent_timestamp: str | None = None,
        agent_family: str | None = None,
        agent_family_parallel: bool = False,
        monitor_id: str | None = None,
        crash: bool = False,
    ) -> _Agent:
        timestamp = f"202607130900{index:02d}"
        artifacts_dir = self.artifacts_root / timestamp
        artifacts_dir.mkdir()
        meta: dict[str, object] = {
            "name": name or f"slot-{index}",
            "pid": os.getpid(),
            "model": "fakey-large",
            "llm_provider": "fakey",
            "queue_weight": queue_weight,
            "queue_weight_explicit": queue_weight_explicit,
        }
        if wait_runners is not None:
            meta["wait_runners"] = wait_runners
        if wait_priority is not None:
            meta["wait_priority"] = wait_priority
        if parent_timestamp is not None:
            meta["parent_timestamp"] = parent_timestamp
        if agent_family is not None:
            meta["agent_family"] = agent_family
        if agent_family_parallel:
            meta[AGENT_FAMILY_PARALLEL_FIELD] = True
        if monitor_id is not None:
            meta["monitor_id"] = monitor_id
        write_agent_meta(str(artifacts_dir), meta)
        return _Agent(
            name=str(meta["name"]),
            artifacts_dir=artifacts_dir,
            meta=meta,
            started=self.root / "signals" / f"{timestamp}.started",
            release=self.root / "signals" / f"{timestamp}.release",
            wait_runners=wait_runners,
            wait_priority=wait_priority,
            queue_weight=queue_weight,
            queue_weight_explicit=queue_weight_explicit,
            crash=crash,
        )

    def start(self, agent: _Agent) -> None:
        assert agent.thread is None
        agent.thread = threading.Thread(
            target=self._run,
            args=(agent,),
            name=agent.name,
            daemon=True,
        )
        agent.thread.start()

    def wait_started(self, agent: _Agent) -> None:
        def started_or_failed() -> bool:
            if agent.started.exists():
                return True
            if agent.thread is not None and not agent.thread.is_alive():
                self.join(agent)
            return False

        _wait_for_condition(
            started_or_failed,
            f"fakey agent {agent.name} to start",
            diagnostics=lambda: self._diagnostics(agent),
        )

    def wait_parked(self, agent: _Agent) -> None:
        waiting_path = agent.artifacts_dir / "waiting.json"

        def is_slot_waiter() -> bool:
            try:
                marker = json.loads(waiting_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return False
            return bool(marker.get("slot_requested_at"))

        _wait_for_condition(
            is_slot_waiter,
            f"agent {agent.name} to park for a runner slot",
            diagnostics=lambda: self._diagnostics(agent),
        )

    def agent_meta(self, agent: _Agent) -> dict[str, object]:
        return json.loads(
            (agent.artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )

    def waiting_marker(self, agent: _Agent) -> dict[str, object]:
        return json.loads(
            (agent.artifacts_dir / "waiting.json").read_text(encoding="utf-8")
        )

    def assert_parked_not_started(self, agent: _Agent) -> None:
        assert not agent.started.exists(), self._diagnostics(agent)
        assert (agent.artifacts_dir / "waiting.json").exists(), self._diagnostics(agent)

    def release_agent(self, agent: _Agent) -> None:
        agent.release.parent.mkdir(parents=True, exist_ok=True)
        agent.release.touch()

    def kill_parked(self, agent: _Agent) -> None:
        agent.killed = True
        with self._lock:
            self._killed_threads.add(agent.name)
        self.join(agent)
        assert not (agent.artifacts_dir / "waiting.json").exists()

    def join(self, agent: _Agent) -> None:
        assert agent.thread is not None
        agent.thread.join(_WAIT_TIMEOUT)
        assert not agent.thread.is_alive(), (
            f"agent {agent.name} did not finish; {self._diagnostics(agent)}"
        )
        errors = [error for name, error in self._errors if name == agent.name]
        assert not errors, f"agent {agent.name} failed: {errors!r}"

    def join_all(self, agents: list[_Agent]) -> None:
        for agent in agents:
            self.join(agent)
        assert not self._errors

    def _was_killed(self) -> bool:
        with self._lock:
            return threading.current_thread().name in self._killed_threads

    def _claim(self, agent: _Agent) -> str:
        started_at = record_run_started_at(str(agent.artifacts_dir), agent.meta)
        with self._lock:
            self.claim_order.append(agent.name)
            if "parent_timestamp" not in agent.meta:
                self.active_roots += 1
                self.max_active_roots = max(
                    self.max_active_roots,
                    self.active_roots,
                )
        return started_at

    def _run(self, agent: _Agent) -> None:
        is_root = "parent_timestamp" not in agent.meta
        try:
            run_agent_wait_slots.wait_for_runner_slot(
                str(agent.artifacts_dir),
                "fakey-slots",
                agent.artifacts_dir.name,
                agent.meta,
                wait_runners=agent.wait_runners,
                wait_priority=agent.wait_priority,
                queue_weight=agent.queue_weight,
                queue_weight_explicit=agent.queue_weight_explicit,
                claim=lambda: self._claim(agent),
            )
            try:
                FakeyProvider().invoke(
                    self._prompt(agent),
                    model_tier="large",
                    suppress_output=True,
                )
            except subprocess.CalledProcessError:
                if not agent.crash:
                    raise

            if is_root:
                with self._lock:
                    self.active_roots -= 1
            if agent.crash:
                agent.meta["pid"] = 2_147_483_647
                write_agent_meta(str(agent.artifacts_dir), agent.meta)
            else:
                (agent.artifacts_dir / "done.json").write_text(
                    json.dumps({"outcome": "completed"}),
                    encoding="utf-8",
                )
                update_agent_artifact_index_for_marker_mutation(agent.artifacts_dir)
        except SystemExit as exc:
            if not agent.killed or exc.code != 128 + 15:
                with self._lock:
                    self._errors.append((agent.name, exc))
        except BaseException as exc:  # noqa: BLE001 - transported to test thread
            with self._lock:
                self._errors.append((agent.name, exc))

    def _prompt(self, agent: _Agent) -> str:
        failure = (
            "attempts:\n"
            "  - fail:\n"
            "      message: simulated crashed runner\n"
            "      retryable: false\n"
            if agent.crash
            else "reply: completed\n"
        )
        return (
            "Exercise the production runner-slot gate.\n"
            "```fakey\n"
            "version: 1\n"
            "steps:\n"
            f"  - signal: {agent.started}\n"
            "  - wait_for:\n"
            f"      path: {agent.release}\n"
            f"      timeout: {_FAKEY_RELEASE_TIMEOUT:g}\n"
            f"{failure}"
            "```\n"
        )

    def _diagnostics(self, agent: _Agent) -> str:
        waiting = agent.artifacts_dir / "waiting.json"
        return (
            f"agent={agent.name!r} started={agent.started.exists()} "
            f"parked={waiting.exists()} released={agent.release.exists()} "
            f"thread_alive={agent.thread is not None and agent.thread.is_alive()} "
            f"claim_order={self.claim_order!r} errors={self._errors!r}"
        )


def _wait_for_condition(
    predicate: object,
    description: str,
    *,
    diagnostics: object | None = None,
) -> None:
    deadline = time.monotonic() + _WAIT_TIMEOUT
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    suffix = f"; {diagnostics()}" if callable(diagnostics) else ""
    raise AssertionError(f"timed out waiting for {description}{suffix}")

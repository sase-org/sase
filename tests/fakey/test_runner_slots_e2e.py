"""End-to-end runner-slot lifecycle coverage with the fakey provider.

These scenarios exercise the production filesystem scan, global flock, marker
mutations, live config reload, and a real bundled ``fakey`` subprocess.  The
only shortened production behavior is the two-second parked-agent poll.
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

from sase.axe import run_agent_wait
from sase.axe.run_agent_markers import record_run_started_at, write_agent_meta
from sase.config import core as config_core
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.llm_provider.fakey import FakeyProvider


_TIMEOUT = 8.0


@dataclass
class _Agent:
    name: str
    artifacts_dir: Path
    meta: dict[str, object]
    started: Path
    release: Path
    wait_runners: int | None = None
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
        monkeypatch.setattr(run_agent_wait, "_RUNNER_SLOT_POLL_INTERVAL", 0.01)
        monkeypatch.setattr(run_agent_wait, "was_killed", self._was_killed)

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
        parent_timestamp: str | None = None,
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
        }
        if parent_timestamp is not None:
            meta["parent_timestamp"] = parent_timestamp
        write_agent_meta(str(artifacts_dir), meta)
        return _Agent(
            name=str(meta["name"]),
            artifacts_dir=artifacts_dir,
            meta=meta,
            started=self.root / "signals" / f"{timestamp}.started",
            release=self.root / "signals" / f"{timestamp}.release",
            wait_runners=wait_runners,
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

        _wait_until(started_or_failed, f"fakey agent {agent.name} to start")

    def wait_parked(self, agent: _Agent) -> None:
        waiting_path = agent.artifacts_dir / "waiting.json"

        def is_slot_waiter() -> bool:
            try:
                marker = json.loads(waiting_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return False
            return bool(marker.get("slot_requested_at"))

        _wait_until(is_slot_waiter, f"agent {agent.name} to park for a runner slot")

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
        agent.thread.join(_TIMEOUT)
        assert not agent.thread.is_alive(), f"agent {agent.name} did not finish"
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
            run_agent_wait.wait_for_runner_slot(
                str(agent.artifacts_dir),
                "fakey-slots",
                agent.artifacts_dir.name,
                agent.meta,
                wait_runners=agent.wait_runners,
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
            f"      timeout: {_TIMEOUT:g}\n"
            f"{failure}"
            "```\n"
        )


def _wait_until(predicate: object, description: str) -> None:
    deadline = time.monotonic() + _TIMEOUT
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {description}")


def test_fakey_agents_respect_cap_and_release_in_fifo_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    agents = [harness.create_agent(index) for index in range(5)]

    for agent in agents[:2]:
        harness.start(agent)
        harness.wait_started(agent)
    for agent in agents[2:]:
        harness.start(agent)
        harness.wait_parked(agent)

    for finished, admitted in zip(agents, agents[2:], strict=False):
        harness.release_agent(finished)
        harness.join(finished)
        harness.wait_started(admitted)

    for agent in agents[3:]:
        harness.release_agent(agent)
    harness.join_all(agents)

    assert harness.claim_order == [agent.name for agent in agents]
    assert harness.max_active_roots == 2


def test_fakey_drain_barrier_waits_for_later_eligible_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    barrier = harness.create_agent(1, name="barrier", wait_runners=0)
    later = harness.create_agent(2, name="later", wait_runners=25)

    harness.start(running)
    harness.wait_started(running)
    harness.start(barrier)
    harness.wait_parked(barrier)
    harness.start(later)
    harness.wait_started(later)
    later_meta = json.loads(
        (later.artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    barrier_meta = json.loads(
        (barrier.artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert isinstance(later_meta.get("run_started_at"), str)
    assert "run_started_at" not in barrier_meta

    harness.release_agent(running)
    harness.join(running)
    time.sleep(0.05)
    assert (barrier.artifacts_dir / "waiting.json").exists()
    assert not barrier.started.exists()

    harness.release_agent(later)
    harness.join(later)
    harness.wait_started(barrier)

    assert harness.claim_order == ["running", "later", "barrier"]
    barrier_meta = json.loads(
        (barrier.artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert isinstance(barrier_meta.get("run_started_at"), str)
    harness.release_agent(barrier)
    harness.join(barrier)


def test_live_config_raise_releases_fakey_waiter_without_axe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    waiter = harness.create_agent(1, name="config-waiter")

    harness.start(running)
    harness.wait_started(running)
    harness.start(waiter)
    harness.wait_parked(waiter)
    harness.write_cap(2)
    harness.wait_started(waiter)

    assert harness.claim_order == ["running", "config-waiter"]
    assert harness.max_active_roots == 2
    for agent in (running, waiter):
        harness.release_agent(agent)
    harness.join_all([running, waiter])


def test_killing_parked_fakey_agent_keeps_queue_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    killed = harness.create_agent(1, name="killed-waiter")
    survivor = harness.create_agent(2, name="survivor")

    harness.start(running)
    harness.wait_started(running)
    harness.start(killed)
    harness.wait_parked(killed)
    harness.start(survivor)
    harness.wait_parked(survivor)
    harness.kill_parked(killed)

    harness.release_agent(running)
    harness.join(running)
    harness.wait_started(survivor)
    harness.release_agent(survivor)
    harness.join(survivor)

    assert harness.claim_order == ["running", "survivor"]


def test_crashed_fakey_runner_frees_slot_without_done_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    crashed = harness.create_agent(0, name="crashed", crash=True)
    survivor = harness.create_agent(1, name="survivor")

    harness.start(crashed)
    harness.wait_started(crashed)
    harness.start(survivor)
    harness.wait_parked(survivor)
    harness.release_agent(crashed)
    harness.join(crashed)
    harness.wait_started(survivor)

    assert not (crashed.artifacts_dir / "done.json").exists()
    assert harness.claim_order == ["crashed", "survivor"]
    harness.release_agent(survivor)
    harness.join(survivor)


def test_child_is_exempt_while_repeat_roots_stay_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    parent = harness.create_agent(0, name="parent")
    child = harness.create_agent(
        1,
        name="parent.child",
        parent_timestamp=parent.artifacts_dir.name,
    )
    repeats = [harness.create_agent(index, name=f"repeat-{index}") for index in (2, 3)]

    harness.start(parent)
    harness.wait_started(parent)
    harness.start(child)
    harness.wait_started(child)
    for repeat in repeats:
        harness.start(repeat)
        harness.wait_parked(repeat)

    harness.release_agent(parent)
    harness.join(parent)
    harness.wait_started(repeats[0])
    harness.release_agent(repeats[0])
    harness.join(repeats[0])
    harness.wait_started(repeats[1])

    for agent in (child, repeats[1]):
        harness.release_agent(agent)
    harness.join_all([child, repeats[1]])

    assert harness.claim_order == ["parent", "parent.child", "repeat-2", "repeat-3"]
    assert harness.max_active_roots == 1

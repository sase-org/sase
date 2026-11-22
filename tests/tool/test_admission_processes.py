"""Multi-process acceptance tests for host admission of capped named tools.

Every test drives real ``sase tool run check`` wrappers against an isolated
``SASE_HOME`` and a fixture catalog whose ``check`` stamps its start and end
into a file and holds until the test creates a release file. The stamps give
the overlap; the release file keeps holders busy for exactly as long as the
test needs, however slowly a loaded host starts the wrappers.
"""

from __future__ import annotations

from collections.abc import Callable
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_show
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT


ROOT = Path(__file__).resolve().parents[2]
SASE = ROOT / ".venv" / "bin" / "sase"

pytestmark = pytest.mark.skipif(
    not SASE.exists(), reason="workspace sase executable missing"
)

# `$1` is the stamps file, `$2` the release file. The loop's own 60 s cap
# keeps a broken test from leaking a child forever.
_CHECK_SCRIPT = (
    'echo "start $$" >> "$1"; i=0; '
    'while [ ! -e "$2" ] && [ "$i" -lt 1200 ]; do sleep 0.05; i=$((i + 1)); done; '
    'echo "end $$" >> "$1"'
)
_NESTED_CHECK_SCRIPT = (
    'if [ "${SASE_ADMISSION_INNER:-}" = "1" ]; then '
    + _CHECK_SCRIPT
    + "; else export SASE_ADMISSION_INNER=1; exec "
    + shlex.quote(str(SASE))
    + " tool run check; fi"
)
_SCRUBBED_ENV = (
    "SASE_AGENT",
    "SASE_AGENT_NAME",
    "SASE_ARTIFACTS_DIR",
    "SASE_MONITOR_ID",
    "SASE_MONITOR_ARTIFACTS_DIR",
    "SASE_PROC_ID",
    "SASE_PROC_LOG_PATH",
    "SASE_TOOL_RUN_ID",
    "SASE_TOOL_RUN_AGENT_CHILD",
    "SASE_TOOL_RUN_EVENTS",
    "SASE_TOOL_RUN_AGENT",
    "SASE_BEAD_ID",
    "SASE_BEAD",
    "SASE_WORKSPACE_NUM",
    "SASE_PROVIDER_SYNC_CEILING_SECONDS",
)


@dataclass
class _World:
    root: Path
    env: dict[str, str]
    stamps: Path
    release: Path
    logs: Path
    procs: list[subprocess.Popen[bytes]]

    def _spawn(
        self, label: str, env: dict[str, str], *, tool_name: str = "check"
    ) -> subprocess.Popen[bytes]:
        out = (self.logs / f"{label}.log").open("wb")
        proc = subprocess.Popen(
            [str(SASE), "tool", "run", tool_name],
            cwd=self.root,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        out.close()
        self.procs.append(proc)
        return proc

    def start(
        self, label: str, *, tool_name: str = "check", **extra_env: str
    ) -> subprocess.Popen[bytes]:
        env = dict(self.env)
        env.update(extra_env)
        return self._spawn(label, env, tool_name=tool_name)

    def start_from_agent_launch(
        self, label: str, *, inherited_run_id: str, agent_name: str
    ) -> subprocess.Popen[bytes]:
        """Launch a check with the same ownership scrubs as a new agent."""
        from sase.agent.launch_spawn import (
            _remove_inherited_agent_identity_env,
            _remove_inherited_executor_ownership_env,
        )
        from sase.tool.ownership import agent_child_provenance

        env = dict(self.env)
        # Model the worst inherited case: a live parent id and a matching
        # marker carried by the parent agent before launch_spawn scrubs them.
        env.update(
            SASE_AGENT="1",
            SASE_AGENT_NAME=agent_name,
            SASE_TOOL_RUN_ID=inherited_run_id,
            SASE_TOOL_RUN_AGENT_CHILD=agent_child_provenance(
                inherited_run_id, agent_name
            ),
        )
        _remove_inherited_agent_identity_env(env)
        _remove_inherited_executor_ownership_env(env)
        env["SASE_AGENT"] = "1"
        env["SASE_AGENT_NAME"] = agent_name
        assert "SASE_TOOL_RUN_ID" not in env
        assert "SASE_TOOL_RUN_AGENT_CHILD" not in env
        return self._spawn(label, env)

    def output(self, label: str) -> str:
        return (self.logs / f"{label}.log").read_text(errors="replace")

    def stamp_lines(self) -> list[str]:
        if not self.stamps.exists():
            return []
        return self.stamps.read_text().splitlines()


@pytest.fixture
def world(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Any:  # Iterator[_World]; the factory takes the limit.
    created: list[_World] = []

    def make(
        limit: int, *, nested_check: bool = False, max_wait_seconds: int | None = None
    ) -> _World:
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("SASE_HOME", str(home))
        for key in _SCRUBBED_ENV:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        stamps = tmp_path / "stamps"
        release = tmp_path / "release"
        root = tmp_path / "project"
        (root / ".git").mkdir(parents=True, exist_ok=True)
        (root / "sase").mkdir(exist_ok=True)
        check_script = _NESTED_CHECK_SCRIPT if nested_check else _CHECK_SCRIPT
        admission_config: dict[str, Any] = {"max_concurrent": {"check": limit}}
        if max_wait_seconds is not None:
            admission_config["max_wait_seconds"] = max_wait_seconds
        config = {
            "tools": {
                "check": {
                    "argv": [
                        "sh",
                        "-c",
                        check_script,
                        "sh",
                        str(stamps),
                        str(release),
                    ],
                    "description": "admission fixture",
                    "args": "deny",
                    "inputs": [],
                    "env": [],
                    "fingerprint": {"repos": [], "toolchain": {}},
                }
            },
            "tool_runs": {"admission": admission_config},
        }
        (root / "sase" / "sase.yml").write_text(yaml.safe_dump(config), "utf-8")
        monkeypatch.chdir(root)
        clear_config_cache()
        logs = tmp_path / "logs"
        logs.mkdir(exist_ok=True)
        made = _World(
            root=root,
            env=dict(os.environ),
            stamps=stamps,
            release=release,
            logs=logs,
            procs=[],
        )
        created.append(made)
        return made

    yield make
    for made in created:
        made.release.touch()
        for proc in made.procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)


def _wait_for(
    predicate: Callable[[], Any], what: str, timeout: float = LOAD_TOLERANT_TIMEOUT
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)  # sase-test-wait: poll the store and stamps file
    raise AssertionError(f"timed out waiting for {what}")


def _runs() -> list[dict[str, Any]]:
    try:
        listed = tool_run_list({"schema_version": 1, "limit": 50})
        return [
            tool_run_show(str(row["run_id"]))["run"] for row in listed.get("runs") or ()
        ]
    except Exception:  # noqa: BLE001 - the first wrapper may still be creating the store.
        return []


def _record(run: dict[str, Any]) -> dict[str, Any] | None:
    return (run.get("demand") or {}).get("admission")


def _states(state: str) -> list[dict[str, Any]]:
    found = []
    for run in _runs():
        record = _record(run)
        if (
            record is not None
            and record.get("state") == state
            and run.get("state") in ("created", "running")
        ):
            found.append(run)
    return found


def _wrapper_run(pid: int) -> dict[str, Any] | None:
    for run in _runs():
        if run.get("wrapper_pid") == pid:
            return run
    return None


def _max_overlap(lines: list[str]) -> int:
    running = 0
    peak = 0
    for line in lines:
        kind = line.split()[0]
        running += 1 if kind == "start" else -1
        peak = max(peak, running)
    return peak


def _started_children(world: _World) -> list[int]:
    return [
        int(line.split()[1]) for line in world.stamp_lines() if line.startswith("start")
    ]


def _pid_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    try:
        status = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
    except OSError:
        return True
    return status == "Z"


def test_limit_two_with_four_runs_never_overlaps_more_than_two(world: Any) -> None:
    w: _World = world(2)
    procs = [w.start(f"run{index}") for index in range(4)]

    _wait_for(lambda: len(_states("admitted")) == 2, "two holders")
    _wait_for(lambda: len(_states("waiting")) == 2, "two waiters")
    assert len(_started_children(w)) == 2
    w.release.touch()

    codes = [proc.wait(timeout=LOAD_TOLERANT_TIMEOUT) for proc in procs]
    assert codes == [0, 0, 0, 0]
    lines = w.stamp_lines()
    assert len([line for line in lines if line.startswith("start")]) == 4
    assert _max_overlap(lines) <= 2
    records = [_record(run) for run in _runs()]
    assert all(record and record["state"] == "admitted" for record in records)
    waited = [record for record in records if record and record["wait_ms"] > 0]
    assert len(waited) >= 2
    outputs = "".join(w.output(f"run{index}") for index in range(4))
    assert outputs.count("sase: waiting for a check slot (limit 2: 2 running") == 2
    assert outputs.count("sase: check slot granted after ") == 2


def test_killed_holder_frees_its_slot_and_its_child_is_reaped(world: Any) -> None:
    w: _World = world(1)
    holder = w.start("holder")
    holder_child = _wait_for(lambda: _started_children(w), "holder child")[0]
    waiter = w.start("waiter")
    _wait_for(lambda: len(_states("waiting")) == 1, "a waiting run")

    holder.send_signal(signal.SIGKILL)
    holder.wait(timeout=10)
    killed_at = time.monotonic()
    _wait_for(lambda: len(_started_children(w)) == 2, "the waiter's child")
    granted_after = time.monotonic() - killed_at

    # The sweep runs at least every 5 s; allow a loaded host generous slack.
    assert granted_after < 30, granted_after
    _wait_for(lambda: _pid_gone(holder_child), "the lost holder's child to be reaped")
    lost = _wait_for(lambda: _wrapper_run(holder.pid), "the holder row")
    assert lost["state"] == "lost"
    w.release.touch()
    assert waiter.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    assert "sase: check slot granted after " in w.output("waiter")


def test_killed_waiter_ahead_does_not_wedge_the_queue(world: Any) -> None:
    w: _World = world(1)
    holder = w.start("holder")
    _wait_for(lambda: _started_children(w), "holder child")
    first = w.start("first")
    _wait_for(lambda: len(_states("waiting")) == 1, "the first waiter")
    second = w.start("second")
    _wait_for(lambda: len(_states("waiting")) == 2, "the second waiter")

    first.send_signal(signal.SIGKILL)
    first.wait(timeout=10)
    w.release.touch()

    assert holder.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    assert second.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    assert len(_started_children(w)) == 2
    dead = _wait_for(lambda: _wrapper_run(first.pid), "the killed waiter row")
    dead = _wait_for(
        lambda: (
            tool_run_show(dead["run_id"])["run"]
            if tool_run_show(dead["run_id"])["run"]["state"] == "lost"
            else None
        ),
        "the killed waiter to be reconciled lost",
    )
    assert _record(dead)["state"] == "abandoned"  # type: ignore[index]


def test_stopped_waiter_never_runs_and_the_queue_proceeds(world: Any) -> None:
    w: _World = world(1)
    holder = w.start("holder")
    _wait_for(lambda: _started_children(w), "holder child")
    stopped = w.start("stopped")
    waiting = _wait_for(lambda: _states("waiting"), "a waiting run")[0]
    behind = w.start("behind")
    _wait_for(lambda: len(_states("waiting")) == 2, "a second waiter")

    stop = subprocess.run(
        [str(SASE), "tool", "stop", waiting["run_id"]],
        cwd=w.root,
        env=w.env,
        capture_output=True,
        timeout=LOAD_TOLERANT_TIMEOUT,
        check=False,
    )
    assert stop.returncode == 0, stop.stderr.decode()
    assert stopped.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 143
    run = tool_run_show(waiting["run_id"])["run"]
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
    assert _record(run)["state"] == "abandoned"  # type: ignore[index]
    assert "command was not run" in w.output("stopped")
    assert len(_started_children(w)) == 1

    w.release.touch()
    assert holder.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    assert behind.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    assert len(_started_children(w)) == 2


def test_handoff_and_monitor_owned_runs_both_queue(
    world: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc
    from sase.tool.executor import ToolRunCliRequest, execute_tool_run

    w: _World = world(1)
    holder = w.start("holder")
    _wait_for(lambda: _started_children(w), "holder child")
    monitor_artifacts = tmp_path / "monitor-artifacts"
    monitor_artifacts.mkdir()
    monitored = w.start(
        "monitored",
        SASE_MONITOR_ID="mon-admission",
        SASE_MONITOR_ARTIFACTS_DIR=str(monitor_artifacts),
    )
    code = execute_tool_run(
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=("check",),
            hand_off=True,
        )
    )
    assert code == 0
    handoff_id = next(
        line.split("sase tool run ")[1].strip().split()[0]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("sase tool run ")
    )

    _wait_for(
        lambda: len(_states("waiting")) == 2,
        "the monitor-owned and hand-off runs to wait",
    )
    waiting = {run["run_id"]: run for run in _states("waiting")}
    assert waiting[handoff_id]["owner_kind"] == "proc"
    assert waiting[handoff_id]["launch_mode"] == "handoff"
    monitor_owned = [run for run in waiting.values() if run["run_id"] != handoff_id]
    assert [run["owner_kind"] for run in monitor_owned] == ["monitor"]
    assert len(_started_children(w)) == 1

    w.release.touch()
    assert holder.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    assert monitored.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    proc = read_procs(tag=f"tool-run:{handoff_id}")[0]
    wait_for_proc(proc.proc_id, timeout=LOAD_TOLERANT_TIMEOUT)
    settled = _wait_for(
        lambda: (
            tool_run_show(handoff_id)["run"]
            if tool_run_show(handoff_id)["run"]["state"] not in ("created", "running")
            else None
        ),
        "the hand-off run to settle",
    )
    assert settled["state"] == "succeeded"
    assert _record(settled)["state"] == "admitted"  # type: ignore[index]
    assert len(_started_children(w)) == 3
    assert _max_overlap(w.stamp_lines()) <= 1


def test_nested_agent_check_keeps_parent_and_never_queues(world: Any) -> None:
    w: _World = world(1, nested_check=True, max_wait_seconds=0)
    outer = w.start(
        "nested",
        SASE_AGENT="1",
        SASE_AGENT_NAME="fixture-agent",
        # There is no artifacts directory or agent_meta.json, so an attempted
        # inline escalation has no usable starter and falls back to foreground.
        SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS="8",
    )
    outer_run = _wait_for(lambda: _wrapper_run(outer.pid), "outer check wrapper")
    assert outer_run.get("parent_run_id") is None
    inner_run = _wait_for(
        lambda: next(
            (run for run in _runs() if run.get("parent_run_id") == outer_run["run_id"]),
            None,
        ),
        "inner check with a durable parent relationship",
    )
    assert _record(inner_run) is None
    assert len(_started_children(w)) == 1

    w.release.touch()
    assert outer.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    settled_inner = tool_run_show(inner_run["run_id"])["run"]
    assert settled_inner["state"] == "succeeded"
    assert _record(settled_inner) is None
    output = w.output("nested")
    assert "max_wait_seconds" not in output
    assert "admission unavailable" not in output


@pytest.mark.parametrize("settled_inherited", [False, True], ids=["live", "settled"])
def test_new_agent_launch_scrubs_inherited_run_before_admission(
    world: Any, settled_inherited: bool
) -> None:
    w: _World = world(1)
    inherited_run_id: str | None = None
    completed_children = 0
    if settled_inherited:
        historical = w.start("historical")
        _wait_for(lambda: _started_children(w), "historical check child")
        historical_run = _wrapper_run(historical.pid)
        assert historical_run is not None
        inherited_run_id = str(historical_run["run_id"])
        w.release.touch()
        assert historical.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
        completed_children = 1
        w.release.unlink()

    blocker = w.start("blocker")
    _wait_for(
        lambda: len(_started_children(w)) == completed_children + 1,
        "the live blocker check child",
    )
    blocker_run = _wrapper_run(blocker.pid)
    assert blocker_run is not None
    if inherited_run_id is None:
        inherited_run_id = str(blocker_run["run_id"])

    spawned_agent = w.start_from_agent_launch(
        "spawned-agent",
        inherited_run_id=inherited_run_id,
        agent_name="fixture-agent",
    )
    spawned_run = _wait_for(
        lambda: _wrapper_run(spawned_agent.pid), "spawned agent check wrapper"
    )
    waiting = _wait_for(
        lambda: next(
            (
                run
                for run in _states("waiting")
                if run.get("wrapper_pid") == spawned_agent.pid
            ),
            None,
        ),
        "spawned agent waiting behind the live holder",
    )
    assert spawned_run.get("parent_run_id") is None
    assert waiting.get("parent_run_id") is None
    assert len(_started_children(w)) == completed_children + 1

    w.release.touch()
    assert blocker.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    assert spawned_agent.wait(timeout=LOAD_TOLERANT_TIMEOUT) == 0
    settled_agent = tool_run_show(spawned_run["run_id"])["run"]
    assert settled_agent["state"] == "succeeded"
    assert _record(settled_agent)["state"] == "admitted"  # type: ignore[index]

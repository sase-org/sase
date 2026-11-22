"""Drive the real lean waiter as a subprocess against a fake runner.

The fake runner records what the waiter handed it (pid, argv, environment, and
the blocked signal mask) into a JSON file and exits, so a test can assert the
whole return-exec contract from the outside.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import sase.axe.run_agent_lean_wait as lean_wait_module
from sase.agent.process_tree import process_is_running
from sase.env_contracts import SASE_RUNNER_LEAN_WAIT_SPEC_ENV

WAITER_PATH = Path(lean_wait_module.__file__ or "")

FAKE_RUNNER = """\
import json, os, signal, sys
out = os.environ["FAKE_RUNNER_OUT"]
payload = {
    "pid": os.getpid(),
    "argv": sys.argv,
    "environ": dict(os.environ),
    "blocked": sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, [])),
}
tmp = out + ".tmp"
with open(tmp, "w") as handle:
    json.dump(payload, handle)
os.replace(tmp, out)
"""

# Runs the real waiter with its probe script swapped for a test stub, so probe
# behavior (release, failure, hang) is deterministic and countable.
STUB_PROBE_WRAPPER = """\
import os, sys
import sase.axe.run_agent_lean_wait as waiter
waiter.PROBE_SCRIPT = os.environ["LEAN_WAIT_TEST_PROBE"]
if "LEAN_WAIT_TEST_EXEC_RETRY_INTERVAL" in os.environ:
    waiter.EXEC_RETRY_INTERVAL_SECONDS = float(os.environ["LEAN_WAIT_TEST_EXEC_RETRY_INTERVAL"])
sys.exit(waiter.main())
"""

# Mirrors the runner's hop: SIGTERM is blocked and already pending when the
# waiter starts, so the waiter must install its handler before it unblocks.
PENDING_SIGTERM_WRAPPER = """\
import os, signal, sys
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
os.kill(os.getpid(), signal.SIGTERM)
os.execv(sys.executable, [sys.executable, sys.argv[1], "label"])
"""

PENDING_AT_RETURN_WRAPPER = """\
import os, signal, sys
import sase.axe.run_agent_lean_wait as waiter
real_execve = os.execve
def inject_sigterm(path, argv, env):
    os.kill(os.getpid(), signal.SIGTERM)
    real_execve(path, argv, env)
waiter.os.execve = inject_sigterm
sys.exit(waiter.main())
"""

PENDING_RETURN_RUNNER = """\
import json, os, signal
was_killed = False
def handle_sigterm(_signum, _frame):
    global was_killed
    was_killed = True
signal.signal(signal.SIGTERM, handle_sigterm)
blocked_before = sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, []))
signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})
payload = {
    "pid": os.getpid(),
    "environ": dict(os.environ),
    "blocked_before": blocked_before,
    "pending_kill_delivered": was_killed,
}
out = os.environ["FAKE_RUNNER_OUT"]
tmp = out + ".tmp"
with open(tmp, "w") as handle:
    json.dump(payload, handle)
os.replace(tmp, out)
"""

RUNNER_REENTRY_HARNESS = """\
import json, os, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sase.axe import run_agent_runner
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.agent import scope_sweep

artifacts = Path(os.environ['SASE_TEST_ARTIFACTS'])
events_path = Path(os.environ['SASE_TEST_EVENTS'])
continue_path = Path(os.environ['SASE_TEST_CONTINUE'])
meta = json.loads((artifacts / 'agent_meta.json').read_text())
state = RunnerRunState(
    cl_name='lean-reentry',
    project_file=str(artifacts.parents[2] / 'proj.sase'),
    prompt_file=str(artifacts / 'submitted_prompt.md'),
    output_path=str(artifacts / 'output.log'),
    workflow_name='ace(run)-20261122010101',
    timestamp='20261122010101',
    update_target='',
    is_home_mode=False,
    workspace_dir=str(artifacts / 'workspace'),
    workspace_num=0,
    project_name='proj',
    artifacts_timestamp='20261122010101',
    artifacts_dir=str(artifacts),
    current_artifacts_dir=str(artifacts),
    prompt='Do work',
    submitted_prompt='Do work',
    agent_name='worker.lean',
)
info = SimpleNamespace(
    wait_names=['dependency'], wait_identity_deps=[], wait_fork_sources=[],
    wait_beads=[], wait_hoods=[], wait_duration=None, wait_until=None,
    wait_for_epics_of=None, wait_runners=None, queue_capacity_multiplier=None,
    wait_priority=None, queue_weight=1.0, queue_weight_explicit=False,
    local_macros=None, hold=None,
)
bootstrap = SimpleNamespace(
    info=info, agent_meta=meta, has_dependency_wait=True, has_wait=True,
)

def wait_for_slot(*args, claim, **kwargs):
    started = claim()
    payload = {'slot_calls': 1, 'pid': os.getpid(), 'run_started_at': started}
    tmp = str(events_path) + '.tmp'
    Path(tmp).write_text(json.dumps(payload))
    os.replace(tmp, events_path)
    return started

def launch(current_state, current_bootstrap):
    payload = {
        'pid': os.getpid(),
        'run_started_at': current_state.run_started_at,
        'wait_completed_at': current_bootstrap.agent_meta.get('wait_completed_at'),
    }
    tmp = str(events_path) + '.launch.tmp'
    Path(tmp).write_text(json.dumps(payload))
    os.replace(tmp, str(events_path) + '.launch')
    deadline = time.monotonic() + 15
    while not continue_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not continue_path.exists():
        raise RuntimeError('test did not release runner continuation')
    current_state.success = True
    current_state.exec_outcome = 'completed'

with (
    patch.object(run_agent_runner, '_defer_start_across_code_swap'),
    patch.object(run_agent_runner, '_build_run_state', return_value=state),
    patch.object(run_agent_runner, 'bootstrap_agent_run', return_value=bootstrap),
    patch.object(run_agent_runner, 'expand_deferred_launch_macros', side_effect=lambda prompt, *args, **kwargs: prompt),
    patch.object(run_agent_runner, 'wait_for_runner_slot', side_effect=wait_for_slot),
    patch.object(run_agent_runner, 'launch_agent_run', side_effect=launch),
    patch.object(run_agent_runner, 'detect_repeat_stop', return_value=None),
    patch.object(run_agent_runner, 'finalize_runner_shutdown'),
    patch.object(run_agent_runner, 'record_completion_metrics'),
    patch.object(run_agent_runner, 'cleanup_launch_scratch'),
    patch.object(scope_sweep, 'sweep_own_agent_scope'),
    patch('sase.axe.run_agent_wait.update_agent_artifact_index_for_marker_mutation'),
):
    run_agent_runner.main()
"""

STUB_PROBE = """\
import json, os, sys, time
log = os.environ["LEAN_WAIT_TEST_PROBE_LOG"]
with open(log, "a") as handle:
    handle.write(json.dumps({
        "pid": os.getpid(),
        "argv": sys.argv[1:],
        "has_spec": "SASE_RUNNER_LEAN_WAIT_SPEC" in os.environ,
    }) + "\\n")
behavior = os.environ.get("LEAN_WAIT_TEST_PROBE_BEHAVIOR", "release")
if behavior == "hang":
    time.sleep(60)
if behavior == "fail":
    print("probe exploded", file=sys.stderr)
    sys.exit(3)
if behavior == "garbage":
    print("not json")
    sys.exit(0)
released = behavior == "release"
print(json.dumps({"released": released, "satisfied_at": 7.5 if released else None}))
"""


class LeanWaitRig:
    """Per-test artifacts dir, fake runner, stub probe, and spawned waiters."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.artifacts_dir = tmp_path / "artifacts"
        self.artifacts_dir.mkdir()
        self.runner_script = tmp_path / "fake_runner.py"
        self.runner_script.write_text(FAKE_RUNNER, encoding="utf-8")
        self.runner_out = tmp_path / "runner_out.json"
        self.probe_script = tmp_path / "stub_probe.py"
        self.probe_script.write_text(STUB_PROBE, encoding="utf-8")
        self.probe_log = tmp_path / "probe_log.jsonl"
        self.waiter_output = tmp_path / "waiter_output.txt"
        self.spawn_env: dict[str, str] = {}
        self.procs: list[subprocess.Popen[bytes]] = []

    @property
    def ready_path(self) -> Path:
        return self.artifacts_dir / "ready.json"

    @property
    def waiting_path(self) -> Path:
        return self.artifacts_dir / "waiting.json"

    def spec(self, **overrides: Any) -> dict[str, Any]:
        now = time.time()
        spec: dict[str, Any] = {
            "version": 1,
            "artifacts_dir": str(self.artifacts_dir),
            "project_name": None,
            "runner_argv": [sys.executable, str(self.runner_script), "--x", "stamp"],
            "mode": "dependency",
            "deadline_epoch": None,
            "heartbeat_path": None,
            "bead_sync_hint": False,
            "bead_sync_role": "beads",
            "blocked_since": now - 30,
            "handed_off_at": now,
        }
        spec.update(overrides)
        return spec

    def start(
        self,
        spec: dict[str, Any] | str,
        *,
        stub_probe: str | None = None,
        wrapper: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        """Start a waiter. ``stub_probe`` is a behavior name for the stub probe."""
        env = {
            **os.environ,
            "FAKE_RUNNER_OUT": str(self.runner_out),
            SASE_RUNNER_LEAN_WAIT_SPEC_ENV: (
                spec if isinstance(spec, str) else json.dumps(spec)
            ),
            **(extra_env or {}),
        }
        argv = [sys.executable, str(WAITER_PATH), "20261121120000"]
        if stub_probe is not None:
            env["LEAN_WAIT_TEST_PROBE"] = str(self.probe_script)
            env["LEAN_WAIT_TEST_PROBE_LOG"] = str(self.probe_log)
            env["LEAN_WAIT_TEST_PROBE_BEHAVIOR"] = stub_probe
            argv = [sys.executable, "-c", STUB_PROBE_WRAPPER]
        if wrapper is not None:
            argv = [sys.executable, "-c", wrapper, str(WAITER_PATH)]
        self.spawn_env = dict(env)
        output = self.waiter_output.open("ab")
        proc = subprocess.Popen(argv, env=env, stdout=output, stderr=output)
        output.close()
        self.procs.append(proc)
        return proc

    def waiter_text(self) -> str:
        return self.waiter_output.read_text(encoding="utf-8", errors="replace")

    def probe_runs(self) -> list[dict[str, Any]]:
        if not self.probe_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.probe_log.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def finish(
        self, proc: subprocess.Popen[bytes], timeout: float = 20.0
    ) -> dict[str, Any]:
        """Wait for the waiter to exec into the fake runner and return its dump."""
        proc.wait(timeout=timeout)
        return self.runner_dump()

    def runner_dump(self) -> dict[str, Any]:
        dump: dict[str, Any] = json.loads(self.runner_out.read_text(encoding="utf-8"))
        return dump

    def result(
        self, proc: subprocess.Popen[bytes], timeout: float = 20.0
    ) -> dict[str, Any]:
        """Finish the waiter and return the result it handed the fake runner."""
        dump = self.finish(proc, timeout)
        result: dict[str, Any] = json.loads(
            dump["environ"]["SASE_RUNNER_LEAN_WAIT_RESULT"]
        )
        return result

    def wait_for(self, predicate: Any, timeout: float = 15.0, what: str = "") -> None:
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, f"timed out waiting for {what}"
            time.sleep(0.05)  # sase-test-wait: polls a real child process

    def hold_for(self, seconds: float, proc: subprocess.Popen[bytes]) -> None:
        """Assert the waiter stays parked (alive, no runner dump) for *seconds*."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            assert proc.poll() is None, f"waiter left early:\n{self.waiter_text()}"
            assert not self.runner_out.exists()
            time.sleep(0.05)  # sase-test-wait: observes a parked child over a window

    def cleanup(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait(timeout=10)
        for run in self.probe_runs():
            if process_is_running(run["pid"]):
                try:
                    os.kill(run["pid"], signal.SIGKILL)
                except OSError:
                    pass


@pytest.fixture
def lean_rig(tmp_path: Path) -> Iterator[LeanWaitRig]:
    rig = LeanWaitRig(tmp_path)
    try:
        yield rig
    finally:
        rig.cleanup()

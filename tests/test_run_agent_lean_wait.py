"""Subprocess-level tests for the lean waiter against a fake runner.

Every test runs the real ``run_agent_lean_wait.py`` by path with the test
interpreter, the way the runner will ``exec`` it. The fake runner (see
``tests._lean_wait_helpers``) records what the waiter hands back across the
return ``exec``. Probe behavior is driven by a stub probe so releases, failures,
and hangs are deterministic; ``tests.test_run_agent_wait_probe`` covers the real
probe.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sase.agent.process_tree import process_is_running
from sase.env_contracts import (
    SASE_RUNNER_CODE_REFRESHED_ENV,
    SASE_RUNNER_LEAN_WAIT_RESULT_ENV,
    SASE_RUNNER_LEAN_WAIT_SPEC_ENV,
)
from tests._lean_wait_helpers import (
    PENDING_AT_RETURN_WRAPPER,
    PENDING_RETURN_RUNNER,
    PENDING_SIGTERM_WRAPPER,
    RUNNER_REENTRY_HARNESS,
    STUB_PROBE_WRAPPER,
    WAITER_PATH,
    LeanWaitRig,
    lean_rig,
)

__all__ = ["lean_rig"]

SIGTERM = int(signal.SIGTERM)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the lean waiter is POSIX-only"
)


def test_release_on_ready_json_hands_back_a_released_result(
    lean_rig: LeanWaitRig,
) -> None:
    proc = lean_rig.start(lean_rig.spec())
    lean_rig.hold_for(1.0, proc)
    before = time.time()
    lean_rig.ready_path.write_text(
        json.dumps({"released_by": "wait_checks", "dependencies_satisfied_at": 12.5}),
        encoding="utf-8",
    )

    result = lean_rig.result(proc)

    assert result["version"] == 1
    assert result["outcome"] == "released"
    assert result["artifacts_dir"] == str(lean_rig.artifacts_dir)
    assert result["release_source"] == "ready_json"
    assert result["dependencies_satisfied_at"] == 12.5
    assert before <= result["released_at"] <= time.time()
    assert result["killed_at"] is None
    assert "Parked in lean waiter" in lean_rig.waiter_text()
    assert f"pid {proc.pid}" in lean_rig.waiter_text()
    assert "mode dependency" in lean_rig.waiter_text()


def test_unwait_marker_releases_as_manual(lean_rig: LeanWaitRig) -> None:
    lean_rig.ready_path.write_text(
        json.dumps({"unwait": True, "released_by": "tui"}), encoding="utf-8"
    )

    result = lean_rig.result(lean_rig.start(lean_rig.spec()))

    assert result["outcome"] == "released"
    assert result["release_source"] == "manual"
    assert result["dependencies_satisfied_at"] is None
    assert result["released_at"] is not None


def test_cancelled_marker_is_ignored_and_removed(lean_rig: LeanWaitRig) -> None:
    lean_rig.ready_path.write_text(json.dumps({"cancelled": True}), encoding="utf-8")
    proc = lean_rig.start(lean_rig.spec())

    lean_rig.wait_for(lambda: not lean_rig.ready_path.exists(), what="marker removal")
    lean_rig.hold_for(1.0, proc)
    lean_rig.ready_path.write_text(json.dumps({"released_by": "x"}), encoding="utf-8")

    assert lean_rig.result(proc)["release_source"] == "ready_json"


def test_hijack_cancelled_waiting_marker_keeps_the_waiter_parked(
    lean_rig: LeanWaitRig,
) -> None:
    lean_rig.waiting_path.write_text(
        json.dumps({"cancelled_by_hijack": True}), encoding="utf-8"
    )
    lean_rig.ready_path.write_text(json.dumps({"released_by": "x"}), encoding="utf-8")
    proc = lean_rig.start(lean_rig.spec())

    lean_rig.hold_for(2.0, proc)
    lean_rig.waiting_path.write_text(json.dumps({}), encoding="utf-8")

    assert lean_rig.result(proc)["release_source"] == "ready_json"


@pytest.mark.parametrize("mode", ["duration", "until"])
def test_time_modes_release_as_timer_at_the_deadline(
    lean_rig: LeanWaitRig, mode: str
) -> None:
    started = time.time()
    proc = lean_rig.start(lean_rig.spec(mode=mode, deadline_epoch=started + 2.5))
    lean_rig.hold_for(1.0, proc)

    result = lean_rig.result(proc)

    assert time.time() >= started + 2.5
    assert result["outcome"] == "released"
    assert result["release_source"] == "timer"
    assert result["dependencies_satisfied_at"] is None
    # The in-process barrier stamps no release instant for pure time waits.
    assert result["released_at"] is None
    assert f"mode {mode}" in lean_rig.waiter_text()


def test_time_modes_ignore_ready_json(lean_rig: LeanWaitRig) -> None:
    lean_rig.ready_path.write_text(json.dumps({"released_by": "x"}), encoding="utf-8")
    proc = lean_rig.start(
        lean_rig.spec(mode="duration", deadline_epoch=time.time() + 2.5)
    )

    lean_rig.hold_for(1.0, proc)

    assert lean_rig.result(proc)["release_source"] == "timer"


def test_return_exec_preserves_pid_environment_and_blocks_sigterm(
    lean_rig: LeanWaitRig,
) -> None:
    lean_rig.ready_path.write_text(json.dumps({"released_by": "x"}), encoding="utf-8")
    spec = lean_rig.spec()

    proc = lean_rig.start(spec)
    dump = lean_rig.finish(proc)

    assert dump["pid"] == proc.pid
    assert dump["argv"] == spec["runner_argv"][1:]
    assert SIGTERM in dump["blocked"]
    environ = dump["environ"]
    spawn_env = dict(lean_rig.spawn_env)
    spawn_env.pop(SASE_RUNNER_LEAN_WAIT_SPEC_ENV)
    assert SASE_RUNNER_LEAN_WAIT_SPEC_ENV not in environ
    assert environ[SASE_RUNNER_CODE_REFRESHED_ENV] == "1"
    assert json.loads(environ[SASE_RUNNER_LEAN_WAIT_RESULT_ENV])["outcome"] == (
        "released"
    )
    # Everything else survives the round trip (Python may add LC_CTYPE).
    for key, value in spawn_env.items():
        assert environ.get(key) == value, key
    added = set(environ) - set(spawn_env)
    assert added <= {
        SASE_RUNNER_CODE_REFRESHED_ENV,
        SASE_RUNNER_LEAN_WAIT_RESULT_ENV,
        "LC_CTYPE",
    }


def test_sigterm_while_idle_hands_back_a_killed_result(lean_rig: LeanWaitRig) -> None:
    proc = lean_rig.start(lean_rig.spec())
    lean_rig.wait_for(lambda: "Parked in lean waiter" in lean_rig.waiter_text())
    before = time.time()
    os.kill(proc.pid, signal.SIGTERM)

    dump = lean_rig.finish(proc, timeout=10)
    result = json.loads(dump["environ"][SASE_RUNNER_LEAN_WAIT_RESULT_ENV])

    assert dump["pid"] == proc.pid
    assert SIGTERM in dump["blocked"]
    assert result["outcome"] == "killed"
    assert result["release_source"] is None
    assert result["released_at"] is None
    assert before <= result["killed_at"] <= time.time()


def test_sigterm_pending_across_the_hop_is_a_kill_on_arrival(
    lean_rig: LeanWaitRig,
) -> None:
    # Blocked and pending when the waiter starts: it must install the handler
    # before it unblocks, or the default action would kill it with no cleanup.
    proc = lean_rig.start(lean_rig.spec(), wrapper=PENDING_SIGTERM_WRAPPER)

    result = lean_rig.result(proc, timeout=10)

    assert result["outcome"] == "killed"


def test_sigterm_pending_at_return_is_delivered_to_runner_handler(
    lean_rig: LeanWaitRig,
) -> None:
    runner_script = lean_rig.tmp_path / "pending_return_runner.py"
    runner_script.write_text(PENDING_RETURN_RUNNER, encoding="utf-8")
    lean_rig.ready_path.write_text(json.dumps({"released_by": "wait_checks"}))
    spec = lean_rig.spec(runner_argv=[sys.executable, str(runner_script)])

    proc = lean_rig.start(spec, wrapper=PENDING_AT_RETURN_WRAPPER)
    dump = lean_rig.finish(proc)
    result = json.loads(dump["environ"][SASE_RUNNER_LEAN_WAIT_RESULT_ENV])

    assert dump["pid"] == proc.pid
    assert SIGTERM in dump["blocked_before"]
    assert dump["pending_kill_delivered"] is True
    # It was pending at the exec decision; the runner's installed handler owns it.
    assert result["outcome"] == "released"


def test_lean_waiter_reenters_runner_once_with_live_waiting_projection(
    lean_rig: LeanWaitRig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.running_listing import list_running_agents
    from sase.core.process_identity import process_identity_token

    sase_home = lean_rig.tmp_path / ".sase"
    artifacts = (
        sase_home / "projects" / "proj" / "artifacts" / "ace-run" / "20261122010101"
    )
    artifacts.mkdir(parents=True)
    lean_rig.artifacts_dir = artifacts
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    runner_script = lean_rig.tmp_path / "runner_reentry.py"
    runner_script.write_text(RUNNER_REENTRY_HARNESS, encoding="utf-8")
    state_path = lean_rig.tmp_path / "runner_state.json"
    continue_path = lean_rig.tmp_path / "continue_runner"
    spec = lean_rig.spec(
        project_name=None,
        runner_argv=[sys.executable, str(runner_script)],
    )
    proc = lean_rig.start(
        spec,
        extra_env={
            "SASE_HOME": str(sase_home),
            "SASE_TEST_ARTIFACTS": str(artifacts),
            "SASE_TEST_EVENTS": str(state_path),
            "SASE_TEST_CONTINUE": str(continue_path),
        },
    )
    (artifacts / "submitted_prompt.md").write_text("Do work", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "worker.lean",
                "pid": proc.pid,
                "process_identity": process_identity_token(proc.pid),
                "model": "@small",
                "llm_provider": "codex",
                "output_path": str(artifacts / "output.log"),
            }
        ),
        encoding="utf-8",
    )
    lean_rig.waiting_path.write_text(
        json.dumps(
            {
                "waiting_for": ["dependency"],
                "patch_name": "lean-reentry",
                "timestamp": "20261122010101",
            }
        ),
        encoding="utf-8",
    )

    def running_row() -> object | None:
        rows = list_running_agents(project="proj", index_freshness="revalidate")
        return next((row for row in rows if row.name == "worker.lean"), None)

    lean_rig.wait_for(lambda: running_row() is not None, what="WAITING projection")
    waiting = running_row()
    assert waiting is not None
    assert waiting.status == "WAITING"
    assert waiting.pid == proc.pid

    satisfied_at = time.time()
    lean_rig.ready_path.write_text(
        json.dumps(
            {
                "released_by": "test",
                "dependencies_satisfied_at": satisfied_at,
            }
        ),
        encoding="utf-8",
    )
    lean_rig.wait_for(
        lambda: Path(str(state_path) + ".launch").exists(),
        what="runner launch after waiter return",
    )

    started_meta = json.loads((artifacts / "agent_meta.json").read_text())
    launch_event = json.loads(Path(str(state_path) + ".launch").read_text())
    running = running_row()
    assert running is not None
    assert running.status == "RUNNING"
    assert running.pid == proc.pid == launch_event["pid"]
    assert started_meta["pid"] == proc.pid
    assert started_meta["wait_release_source"] == "ready_json"
    assert started_meta["wait_release_latency_s"] < 6
    assert started_meta["admission_latency_s"] < 6
    assert launch_event["run_started_at"] == started_meta["run_started_at"]
    assert json.loads(state_path.read_text())["slot_calls"] == 1

    continue_path.write_text("continue", encoding="utf-8")
    assert proc.wait(timeout=10) == 0
    assert not lean_rig.waiting_path.exists()
    assert not lean_rig.ready_path.exists()


def test_stale_or_missing_heartbeat_probes_at_the_short_interval(
    lean_rig: LeanWaitRig,
) -> None:
    proc = lean_rig.start(
        lean_rig.spec(project_name="proj", probe_interval_s=0.5),
        stub_probe="release",
    )

    result = lean_rig.result(proc)

    assert result["outcome"] == "released"
    assert result["release_source"] == "runner_fallback"
    assert result["dependencies_satisfied_at"] == 7.5
    assert result["released_at"] is not None
    runs = lean_rig.probe_runs()
    assert len(runs) == 1
    argv = runs[0]["argv"]
    assert argv[argv.index("--waiting-path") + 1] == str(lean_rig.waiting_path)
    assert argv[argv.index("--artifacts-dir") + 1] == str(lean_rig.artifacts_dir)
    assert argv[argv.index("--project-name") + 1] == "proj"
    assert "--bead-sync-hint" not in argv
    # The probe is a plain child: it never sees the waiter's spec.
    assert runs[0]["has_spec"] is False
    assert "Dependencies satisfied by runner fallback" in lean_rig.waiter_text()


@pytest.mark.parametrize("state", ["missing_file", "null_path", "old_stamp", "garbage"])
def test_every_stale_heartbeat_state_uses_the_short_interval(
    lean_rig: LeanWaitRig, state: str
) -> None:
    heartbeat = lean_rig.tmp_path / "heartbeat"
    heartbeat_path: str | None = str(heartbeat)
    if state == "null_path":
        heartbeat_path = None
    elif state == "old_stamp":
        heartbeat.write_text(f"{time.time() - 1000}\n", encoding="utf-8")
    elif state == "garbage":
        heartbeat.write_text("not a number", encoding="utf-8")

    proc = lean_rig.start(
        lean_rig.spec(
            project_name="proj",
            heartbeat_path=heartbeat_path,
            probe_interval_s=0.5,
            healthy_probe_interval_s=3600,
        ),
        stub_probe="release",
    )

    assert lean_rig.result(proc)["release_source"] == "runner_fallback"


def test_fresh_heartbeat_runs_no_probe_before_the_healthy_interval(
    lean_rig: LeanWaitRig,
) -> None:
    heartbeat = lean_rig.tmp_path / "heartbeat"
    heartbeat.write_text(f"{time.time()}\n", encoding="utf-8")
    proc = lean_rig.start(
        lean_rig.spec(
            project_name="proj",
            heartbeat_path=str(heartbeat),
            probe_interval_s=0.5,
            healthy_probe_interval_s=3600,
            heartbeat_fresh_s=300,
        ),
        stub_probe="release",
    )

    lean_rig.hold_for(3.0, proc)

    assert lean_rig.probe_runs() == []


def test_a_heartbeat_that_goes_stale_mid_wait_switches_to_the_short_interval(
    lean_rig: LeanWaitRig,
) -> None:
    heartbeat = lean_rig.tmp_path / "heartbeat"
    heartbeat.write_text(f"{time.time()}\n", encoding="utf-8")
    started = time.time()
    proc = lean_rig.start(
        lean_rig.spec(
            project_name="proj",
            heartbeat_path=str(heartbeat),
            probe_interval_s=0.5,
            healthy_probe_interval_s=3600,
            heartbeat_fresh_s=2,
        ),
        stub_probe="release",
    )

    result = lean_rig.result(proc)

    assert result["release_source"] == "runner_fallback"
    # No probe while the heartbeat was fresh, one as soon as it aged out.
    assert time.time() - started >= 1.9


def test_dependency_wait_without_a_project_never_probes(lean_rig: LeanWaitRig) -> None:
    proc = lean_rig.start(
        lean_rig.spec(project_name=None, probe_interval_s=0.5), stub_probe="release"
    )

    lean_rig.hold_for(2.0, proc)

    assert lean_rig.probe_runs() == []


@pytest.mark.parametrize("behavior", ["not_released", "fail", "garbage"])
def test_a_probe_that_does_not_release_keeps_the_waiter_parked(
    lean_rig: LeanWaitRig, behavior: str
) -> None:
    proc = lean_rig.start(
        lean_rig.spec(project_name="proj", probe_interval_s=0.5), stub_probe=behavior
    )

    lean_rig.wait_for(lambda: len(lean_rig.probe_runs()) >= 2, what="a second probe")

    assert proc.poll() is None
    assert not lean_rig.runner_out.exists()
    # A failed probe is reported on stderr, never silently swallowed.
    if behavior == "fail":
        assert "dependency probe exited 3" in lean_rig.waiter_text()
    if behavior == "garbage":
        assert "printed no result" in lean_rig.waiter_text()


def test_a_hung_probe_is_killed_at_the_timeout_and_counts_as_not_released(
    lean_rig: LeanWaitRig,
) -> None:
    proc = lean_rig.start(
        lean_rig.spec(project_name="proj", probe_interval_s=0.5, probe_timeout_s=1),
        stub_probe="hang",
    )

    lean_rig.wait_for(lambda: len(lean_rig.probe_runs()) >= 1)
    first_pid = lean_rig.probe_runs()[0]["pid"]
    lean_rig.wait_for(lambda: not process_is_running(first_pid), what="probe killed")
    lean_rig.wait_for(lambda: len(lean_rig.probe_runs()) >= 2, what="a later probe")

    assert proc.poll() is None
    assert "exceeded 1s" in lean_rig.waiter_text()


def test_sigterm_during_a_probe_stops_the_probe_and_hands_over_killed(
    lean_rig: LeanWaitRig,
) -> None:
    proc = lean_rig.start(
        lean_rig.spec(project_name="proj", probe_interval_s=0.5, probe_timeout_s=60),
        stub_probe="hang",
    )
    lean_rig.wait_for(lambda: len(lean_rig.probe_runs()) >= 1, what="probe start")
    probe_pid = lean_rig.probe_runs()[0]["pid"]
    assert process_is_running(probe_pid)

    os.kill(proc.pid, signal.SIGTERM)
    result = lean_rig.result(proc, timeout=10)

    assert result["outcome"] == "killed"
    assert not process_is_running(probe_pid)


def test_a_ready_marker_during_a_probe_stops_the_probe_and_releases(
    lean_rig: LeanWaitRig,
) -> None:
    proc = lean_rig.start(
        lean_rig.spec(project_name="proj", probe_interval_s=0.5, probe_timeout_s=60),
        stub_probe="hang",
    )
    lean_rig.wait_for(lambda: len(lean_rig.probe_runs()) >= 1, what="probe start")
    probe_pid = lean_rig.probe_runs()[0]["pid"]
    lean_rig.ready_path.write_text(json.dumps({"released_by": "x"}), encoding="utf-8")

    result = lean_rig.result(proc, timeout=10)

    assert result["release_source"] == "ready_json"
    assert not process_is_running(probe_pid)


def test_bead_sync_hint_rides_a_probe_at_most_every_600_seconds(
    lean_rig: LeanWaitRig,
) -> None:
    # The hint cadence is 600 s from handoff, so a handoff 700 s ago makes the
    # very first probe carry it; the next probe, moments later, must not.
    proc = lean_rig.start(
        lean_rig.spec(
            project_name="proj",
            probe_interval_s=0.5,
            bead_sync_hint=True,
            handed_off_at=time.time() - 700,
        ),
        stub_probe="not_released",
    )

    lean_rig.wait_for(lambda: len(lean_rig.probe_runs()) >= 2, what="two probes")
    os.kill(proc.pid, signal.SIGTERM)
    lean_rig.result(proc, timeout=10)

    runs = lean_rig.probe_runs()
    assert "--bead-sync-hint" in runs[0]["argv"]
    assert "--bead-sync-hint" not in runs[1]["argv"]


def test_no_bead_sync_hint_when_the_spec_does_not_ask(lean_rig: LeanWaitRig) -> None:
    proc = lean_rig.start(
        lean_rig.spec(
            project_name="proj",
            probe_interval_s=0.5,
            bead_sync_hint=False,
            handed_off_at=time.time() - 700,
        ),
        stub_probe="not_released",
    )

    lean_rig.wait_for(lambda: len(lean_rig.probe_runs()) >= 2, what="two probes")
    os.kill(proc.pid, signal.SIGTERM)
    lean_rig.result(proc, timeout=10)

    assert all("--bead-sync-hint" not in run["argv"] for run in lean_rig.probe_runs())


def test_a_failing_return_exec_retries_then_exits_one(lean_rig: LeanWaitRig) -> None:
    lean_rig.ready_path.write_text(json.dumps({"released_by": "x"}), encoding="utf-8")
    spec = lean_rig.spec(runner_argv=[str(lean_rig.tmp_path / "no-such-python")])

    proc = lean_rig.start(
        spec,
        stub_probe="not_released",
        extra_env={"LEAN_WAIT_TEST_EXEC_RETRY_INTERVAL": "0.05"},
    )

    assert proc.wait(timeout=20) == 1
    text = lean_rig.waiter_text()
    assert text.count("failed to exec runner") == 4
    assert "attempt 4 of 4" in text
    assert not lean_rig.runner_out.exists()


@pytest.mark.parametrize(
    "spec",
    ["not json", json.dumps({"version": 2}), json.dumps([1, 2])],
)
def test_an_invalid_spec_exits_70_without_waiting(
    lean_rig: LeanWaitRig, spec: str
) -> None:
    proc = lean_rig.start(spec)

    assert proc.wait(timeout=20) == 70
    assert "invalid handoff spec" in lean_rig.waiter_text()
    assert "Parked in lean waiter" not in lean_rig.waiter_text()


def test_a_missing_spec_exits_70() -> None:
    env = {k: v for k, v in os.environ.items() if k != SASE_RUNNER_LEAN_WAIT_SPEC_ENV}
    completed = subprocess.run(
        [sys.executable, str(WAITER_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 70
    assert SASE_RUNNER_LEAN_WAIT_SPEC_ENV in completed.stderr


@pytest.mark.skipif(not Path("/proc/self/status").exists(), reason="needs /proc")
def test_parked_waiter_stays_under_the_rss_budget(lean_rig: LeanWaitRig) -> None:
    proc = lean_rig.start(lean_rig.spec())
    lean_rig.hold_for(5.0, proc)

    status = Path(f"/proc/{proc.pid}/status").read_text(encoding="utf-8")
    fields: dict[str, Any] = dict(
        line.split(":", 1) for line in status.splitlines() if ":" in line
    )
    rss_kb = int(fields["VmRSS"].split()[0])
    thread_count = int(fields["Threads"].strip())

    assert rss_kb <= 40 * 1024, f"lean waiter RSS {rss_kb} kB"
    assert thread_count == 1


def test_stub_wrapper_and_pending_wrapper_are_valid_python() -> None:
    # The wrappers run inside child interpreters; a typo would otherwise show
    # up only as an inscrutable timeout in the tests above.
    compile(STUB_PROBE_WRAPPER, "stub_probe_wrapper", "exec")
    compile(PENDING_SIGTERM_WRAPPER, "pending_sigterm_wrapper", "exec")

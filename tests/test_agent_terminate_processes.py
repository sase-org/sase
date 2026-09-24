"""Real-process tests for verified agent process-tree termination."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from sase.agent.process_registry import ProcessRegistry, RegisteredSupervisor
from sase.agent.process_tree import (
    process_is_running,
    read_process_table,
    shielded_pids,
)
from sase.agent.user_kill import (
    DEFAULT_TERMINATE_GRACE_SECONDS,
    USER_KILL_INTENT_MARKER,
    live_verified_agent_pid,
    request_user_kill,
    terminate_agent_processes,
)
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV
from sase.tool.executor_process import TERM_ESCALATE_SECONDS

from tests._agent_process_tree_helpers import (
    CHILDREN as CHILDREN,
    SLEEPER,
    assert_dead,
    launch_runner,
    no_registry,
    reap as reap,
    scratch_key as scratch_key,
    wait_for_files,
    wait_until_gone,
    write_meta,
)


def test_default_grace_outlasts_tool_wrapper_escalation() -> None:
    assert DEFAULT_TERMINATE_GRACE_SECONDS >= TERM_ESCALATE_SECONDS + 1


def test_shield_covers_current_process_and_ancestors() -> None:
    shielded = shielded_pids(read_process_table())

    assert os.getpid() in shielded
    assert os.getppid() in shielded


def test_terminates_every_process_shape_and_verifies_death(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        registry_fn=no_registry,
    )

    assert result.success is True
    assert result.survivors == ()
    # The child that ignores SIGTERM forces the SIGKILL escalation.
    assert result.status == "force_killed"
    assert result.escalated is True
    assert_dead(pids)
    proc.wait(timeout=5)


def test_sweeps_orphans_after_the_runner_already_died(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)
    # The interactive stage's SIGTERM took the runner down; its children
    # (including the setsid one, reparented away from any group or session of
    # the runner) live on.
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)
    assert not process_is_running(proc.pid)

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        registry_fn=no_registry,
    )

    assert result.success is True
    assert result.survivors == ()
    assert_dead({name: pid for name, pid in pids.items() if name != "runner"})


def test_scratch_key_finds_a_setsid_orphan_that_left_the_session(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)
    # Kill everything except the setsid child, leaving only an orphan that is
    # in neither the runner's group nor its session.
    for name in ("same_group", "own_group", "ignores_term"):
        os.kill(pids[name], signal.SIGKILL)
    wait_until_gone(pids["same_group"], pids["own_group"], pids["ignores_term"])
    assert process_is_running(pids["setsid"])

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=1,
        registry_fn=no_registry,
    )

    assert result.success is True
    assert result.status == "killed"
    assert not process_is_running(pids["setsid"])


def test_older_agent_without_scratch_key_still_sweeps_group_session_and_ppid(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid)  # no launch_scratch_key recorded

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        registry_fn=no_registry,
    )

    # The setsid child is reachable through the live runner's ppid tree.
    assert result.success is True
    assert_dead(pids)


def test_older_agent_without_scratch_key_cannot_find_a_detached_orphan(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid)  # no launch_scratch_key recorded
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        registry_fn=no_registry,
    )

    assert result.success is True
    for name in ("same_group", "own_group", "ignores_term"):
        assert not process_is_running(pids[name])
    # Once the runner is gone only the scratch key can reach a setsid orphan,
    # which is exactly why launches now record it.
    assert process_is_running(pids["setsid"])


def test_gone_runner_with_nothing_left_is_already_stopped(tmp_path: Path) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    proc.wait(timeout=10)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.1,
        registry_fn=no_registry,
    )

    assert result.success is True
    assert result.status == "already_stopped"


def test_identity_mismatch_signals_nothing(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"pid": proc.pid, "process_identity": "other-boot:1"})
    )

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.1,
        registry_fn=no_registry,
    )

    assert result.success is True
    assert result.status == "identity_mismatch"
    assert all(process_is_running(pid) for pid in pids.values())


def test_recycled_pid_is_left_alone_while_scratch_key_orphans_die(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)
    # An unrelated process that now "owns" the recorded pid.
    ready = tmp_path / "decoy"
    decoy = subprocess.Popen(
        [sys.executable, "-c", SLEEPER.format(setup="pass"), str(ready)],
        start_new_session=True,
    )
    reap.append(decoy.pid)
    wait_for_files(tmp_path, ("decoy",))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"pid": decoy.pid, "process_identity": "other-boot:1"})
    )

    result = terminate_agent_processes(
        decoy.pid,
        artifacts_dir=artifacts,
        scratch_key=scratch_key,
        grace_seconds=0.3,
        registry_fn=no_registry,
    )

    assert result.success is True
    assert process_is_running(decoy.pid)
    assert_dead({name: pid for name, pid in pids.items() if name != "runner"})


def test_non_leader_runner_is_terminated_with_its_tree(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap, new_session=False)
    assert os.getpgid(proc.pid) != proc.pid
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        registry_fn=no_registry,
    )

    assert result.success is True
    assert result.status in {"killed", "force_killed"}
    assert_dead(pids)
    # Terminating a non-leader must never take the test process's own group.
    assert process_is_running(os.getpid())


def test_immediate_stage_signals_a_non_leader_and_its_tree(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap, new_session=False)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid)

    result = request_user_kill(
        proc.pid,
        artifacts_dir=artifacts,
        source="test",
        wait=False,
    )

    assert result.status == "killed"  # never "already_stopped" from killpg
    wait_until_gone(proc.pid)
    assert not process_is_running(proc.pid)
    assert not process_is_running(pids["same_group"])


def test_protected_pid_is_never_signalled(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)
    decoy_dir = tmp_path / "decoy"
    decoy = subprocess.Popen(
        [sys.executable, "-c", SLEEPER.format(setup="pass"), str(decoy_dir)],
        env={**os.environ, SASE_LAUNCH_SCRATCH_KEY_ENV: scratch_key},
        start_new_session=True,
    )
    reap.append(decoy.pid)
    wait_for_files(tmp_path, ("decoy",))

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        protected_pids=[decoy.pid],
        registry_fn=no_registry,
    )

    assert result.success is True
    assert process_is_running(decoy.pid)
    assert_dead(pids)


def test_registered_supervisor_stops_through_its_canonical_stop(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)
    stops: list[str] = []
    supervised = pids["setsid"]

    def stop() -> None:
        stops.append("stopped")
        os.kill(supervised, signal.SIGTERM)

    registry = ProcessRegistry(
        supervisors=(RegisteredSupervisor("proc test", frozenset({supervised}), stop),)
    )

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        registry_fn=lambda _pid: registry,
    )

    assert result.success is True
    assert stops == ["stopped"]
    assert_dead(pids)


def test_failed_canonical_stop_falls_back_to_plain_signalling(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    proc, pids = launch_runner(tmp_path, scratch_key, reap)
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, proc.pid, launch_scratch_key=scratch_key)

    def stop() -> None:
        raise RuntimeError("store unavailable")

    registry = ProcessRegistry(
        supervisors=(
            RegisteredSupervisor("proc test", frozenset({pids["setsid"]}), stop),
        )
    )

    result = terminate_agent_processes(
        proc.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.3,
        registry_fn=lambda _pid: registry,
    )

    assert result.success is True
    assert_dead(pids)


def test_survivors_are_reported_and_recorded(
    tmp_path: Path, scratch_key: str, reap: list[int]
) -> None:
    ready = tmp_path / "solo"
    ready.mkdir()
    solo = subprocess.Popen(
        [
            sys.executable,
            "-c",
            SLEEPER.format(setup="signal.signal(signal.SIGTERM, signal.SIG_IGN)"),
            str(ready / "solo"),
        ],
        start_new_session=True,
    )
    reap.append(solo.pid)
    wait_for_files(ready, ("solo",))
    artifacts = tmp_path / "artifacts"
    write_meta(artifacts, solo.pid)
    (artifacts / USER_KILL_INTENT_MARKER).write_text(json.dumps({"pid": solo.pid}))

    def kill(pid: int, sig: int) -> None:
        if sig != signal.SIGKILL:
            os.kill(pid, sig)

    def killpg(pgid: int, sig: int) -> None:
        if sig != signal.SIGKILL:
            os.killpg(pgid, sig)

    result = terminate_agent_processes(
        solo.pid,
        artifacts_dir=artifacts,
        grace_seconds=0.1,
        post_kill_seconds=0.2,
        kill=kill,
        killpg=killpg,
        registry_fn=no_registry,
    )

    assert result.success is False
    assert result.status == "survivors"
    assert result.survivors == (solo.pid,)
    recorded = json.loads((artifacts / USER_KILL_INTENT_MARKER).read_text())["result"]
    assert recorded["survivors"] == [solo.pid]
    assert recorded["status"] == "survivors"


def test_live_verified_agent_pid_requires_a_matching_recorded_identity(
    tmp_path: Path, reap: list[int]
) -> None:
    ready = tmp_path / "live"
    ready.mkdir()
    live = subprocess.Popen(
        [sys.executable, "-c", SLEEPER.format(setup="pass"), str(ready / "live")],
        start_new_session=True,
    )
    reap.append(live.pid)
    wait_for_files(ready, ("live",))
    artifacts = tmp_path / "artifacts"

    artifacts.mkdir()
    assert live_verified_agent_pid(live.pid, artifacts_dir=artifacts) is False

    write_meta(artifacts, live.pid)
    assert live_verified_agent_pid(live.pid, artifacts_dir=artifacts) is True

    (artifacts / "agent_meta.json").write_text(
        json.dumps({"pid": live.pid, "process_identity": "other-boot:1"})
    )
    assert live_verified_agent_pid(live.pid, artifacts_dir=artifacts) is False

    write_meta(artifacts, live.pid)
    os.kill(live.pid, signal.SIGKILL)
    live.wait(timeout=5)
    assert live_verified_agent_pid(live.pid, artifacts_dir=artifacts) is False

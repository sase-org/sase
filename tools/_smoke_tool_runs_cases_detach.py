"""Harness cases: starter-scoped detached runs (DoD-17 hermetic).

Each case drives the real ``sase`` CLI against an isolated ``SASE_HOME``.
The starter is a sacrificial ``sleep`` process named in a temporary
``agent_meta.json``; fault injection happens only at the filesystem/process
boundary.

Matrix mapping:

- accepted ``-d`` is observable at once and settles ... ``dod-17-detach-accept``
- ``-d`` misuse is refused before reserving ........... ``dod-17-detach-refusals``
- starter death stops the unjoined run ................ ``dod-17-detach-starter-death``
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import _smoke_tool_runs_cases_owners as owners
from _smoke_tool_runs_lib import (
    Harness,
    case,
    not_run,
    wait_for,
)


def _agent_env(
    h: Harness, world: dict[str, str], name: str
) -> tuple[dict[str, str], subprocess.Popen[str]]:
    """Agent env with a sacrificial sleeper as the runner PID."""

    artifacts = Path(world["SASE_HOME"]).parent / f"artifacts-{name}"
    artifacts.mkdir(parents=True, exist_ok=True)
    sleeper = subprocess.Popen(
        ["sleep", "300"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"pid": sleeper.pid, "name": name}), encoding="utf-8"
    )
    env = dict(
        world,
        SASE_AGENT="1",
        SASE_AGENT_NAME=name,
        SASE_ARTIFACTS_DIR=str(artifacts),
    )
    return env, sleeper


def _run_id_from_ack(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("sase tool run "):
            return line.split()[-1]
    return ""


def _run_id_from_streams(stdout: str, stderr: str) -> str:
    """The inline-escalation follower prints its id line to stderr."""

    for text in (stderr, stdout):
        for line in text.splitlines():
            if line.startswith("sase tool run "):
                return line.split()[-1]
    return ""


def _terminal(h: Harness, env: dict[str, str], run_id: str) -> dict[str, Any]:
    return h.show(run_id, env=env).get("run") or {}


def _wait_settled(
    h: Harness, env: dict[str, str], run_id: str, timeout: float = 60.0
) -> dict[str, Any]:
    def settled() -> bool:
        run = _terminal(h, env, run_id)
        return run.get("state") not in ("", "created", "running")

    wait_for(settled, timeout=timeout)
    return _terminal(h, env, run_id)


def detach_accept(h: Harness) -> dict[str, Any]:
    """An accepted detach carries its starter and settles normally."""

    env = h.world("detach-accept")
    agent_env, sleeper = _agent_env(h, env, "smoke-agent")
    try:
        proc = h.run(
            ["tool", "run", "-d", "--", "sh", "-c", "sleep 2; exit 3"],
            env=agent_env,
        )
        run_id = _run_id_from_ack(proc.stdout)
        early = _terminal(h, env, run_id) if run_id else {}
        procs = (
            json.loads(
                h.run(["proc", "list", "-j"], env=env, cwd=h.tmp).stdout or "{}"
            ).get("procs")
            or []
        )
        owned = [p for p in procs if f"tool-run:{run_id}" in (p.get("tags") or [])]
        tags = (owned[0].get("tags") or []) if owned else []
        waited = h.run(["tool", "wait", run_id], env=env, cwd=h.tmp, timeout=60.0)
        final = _terminal(h, env, run_id)
        h.note(run_id, "accepted detach settles under its proc", owner="proc")
        ok = (
            proc.returncode == 0
            and bool(run_id)
            and "detached: stopped when this agent's turn ends" in proc.stdout
            and f"sase monitor start -J {run_id}" in proc.stdout
            and early.get("state") in ("created", "running")
            and early.get("launch_mode") == "handoff"
            and (early.get("starter") or {}).get("agent") == "smoke-agent"
            and (early.get("starter") or {}).get("pid") == sleeper.pid
            and early.get("join") is None
            and len(owned) == 1
            and "tool-run-detached" in tags
            and waited.returncode == 3
            and final.get("state") == "failed"
            and final.get("exit_code") == 3
        )
        return case(
            "dod-17-detach-accept",
            ok,
            dod=["DoD-17"],
            run_ids=[run_id],
            early_state=early.get("state"),
            starter_agent=(early.get("starter") or {}).get("agent"),
            detached_tag="tool-run-detached" in tags,
            wait_exit=waited.returncode,
            final_state=final.get("state"),
            final_exit=final.get("exit_code"),
        )
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def detach_refusals(h: Harness) -> dict[str, Any]:
    """``-d`` misuse is refused before anything is reserved."""

    env = h.world("detach-refusals")
    agent_env, sleeper = _agent_env(h, env, "smoke-agent")
    try:
        human = h.run(["tool", "run", "-d", "--", "printf", "hi"], env=env)
        verbose = h.run(
            ["tool", "run", "-d", "-v", "--", "printf", "hi"], env=agent_env
        )
        tail = h.run(
            ["tool", "run", "-d", "-T", "5", "--", "printf", "hi"], env=agent_env
        )
        no_starter = dict(agent_env)
        del no_starter["SASE_ARTIFACTS_DIR"]
        unresolvable = h.run(
            ["tool", "run", "-d", "--", "printf", "hi"], env=no_starter
        )
        rows = h.runs(env=env)
        ok = (
            human.returncode == 2
            and "sase tool run -H" in human.stderr
            and verbose.returncode == 2
            and tail.returncode == 2
            and unresolvable.returncode == 1
            and "cannot identify the starting agent runner; nothing was started"
            in unresolvable.stderr
            and rows == []
        )
        return case(
            "dod-17-detach-refusals",
            ok,
            dod=["DoD-17"],
            human_exit=human.returncode,
            verbose_exit=verbose.returncode,
            tail_exit=tail.returncode,
            unresolvable_exit=unresolvable.returncode,
            rows=len(rows),
        )
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def inline_escalation(h: Harness) -> dict[str, Any]:
    """A plain agent run with a soft budget follows, then escalates at 124."""

    env = h.world("inline-escalation")
    agent_env, sleeper = _agent_env(h, env, "smoke-agent")
    budget_env = dict(agent_env, SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS="8")
    try:
        proc = h.run(
            ["tool", "run", "--", "sh", "-c", "sleep 20; exit 3"],
            env=budget_env,
        )
        run_id = _run_id_from_streams(proc.stdout, proc.stderr)
        early = _terminal(h, env, run_id) if run_id else {}
        waited = h.run(["tool", "wait", run_id], env=env, cwd=h.tmp, timeout=60.0)
        final = _terminal(h, env, run_id)
        rows = h.runs(env=env, cwd=h.tmp)
        h.note(run_id, "plain agent run escalates at the budget", owner="proc")
        ok = (
            proc.returncode == 124
            and bool(run_id)
            and "was not stopped" in proc.stderr
            and "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS" in proc.stderr
            and f"sase monitor start -J {run_id}" in proc.stderr
            and f"sase tool wait {run_id}" in proc.stderr
            and early.get("state") in ("created", "running")
            and early.get("launch_mode") == "handoff"
            and (early.get("starter") or {}).get("agent") == "smoke-agent"
            and waited.returncode == 3
            and final.get("state") == "failed"
            and final.get("exit_code") == 3
            and len(rows) == 1
        )
        return case(
            "dod-17-inline-escalation",
            ok,
            dod=["DoD-17"],
            run_ids=[run_id],
            follower_exit=proc.returncode,
            early_state=early.get("state"),
            wait_exit=waited.returncode,
            final_state=final.get("state"),
            final_exit=final.get("exit_code"),
            rows=len(rows),
        )
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def detach_join(h: Harness) -> dict[str, Any]:
    """Joining a detached run streams it and settles with the run's exit."""

    env = h.world("detach-join")
    agent_env, sleeper = _agent_env(h, env, "smoke-agent")
    try:
        proc = h.run(
            ["tool", "run", "-d", "--", "sh", "-c", "echo join-smoke; exit 3"],
            env=agent_env,
        )
        run_id = _run_id_from_ack(proc.stdout)
        join_env = dict(env, SASE_MONITOR_ID="mon-smoke-join")
        joined = h.run(["tool", "_join", run_id], env=join_env, cwd=h.tmp, timeout=60.0)
        final = _terminal(h, env, run_id) if run_id else {}
        h.note(run_id, "detached run joined and settled with its own exit")
        ok = (
            proc.returncode == 0
            and bool(run_id)
            and joined.returncode == 3
            and "join-smoke" in joined.stdout
            and "failed/3" in joined.stderr
            and final.get("state") == "failed"
            and final.get("exit_code") == 3
            and (final.get("join") or {}).get("id") == "mon-smoke-join"
        )
        return case(
            "dod-17-detach-join",
            ok,
            dod=["DoD-17"],
            run_ids=[run_id],
            join_exit=joined.returncode,
            final_state=final.get("state"),
            final_exit=final.get("exit_code"),
            join_id=(final.get("join") or {}).get("id"),
        )
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def live_escalate_join(h: Harness) -> dict[str, Any]:
    """Escalate-then-join over a real monitor: one id from detach to settlement.

    A detached run from a simulated agent is joined by a real
    ``sase monitor start -J`` whose runner kill targets the sacrificial
    starter process group. The run keeps one id end to end and the monitor
    mirrors the run's exit code.
    """

    if not h.live:
        return not_run(
            "dod-17-live-escalate-join",
            "live cases were not requested; pass --live",
            dod=["DoD-17"],
        )
    env, project = owners._owner_world(h, "escalate-join")
    # The join runs on the calling agent's lane, so the caller is the fixture
    # agent; its runner pid is a sacrificial sleeper so the monitor start's
    # runner kill targets that process group, never the harness.
    artifacts = owners.fixture_agent_artifacts(env, project)
    sleeper = subprocess.Popen(
        ["sleep", "300"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {"pid": sleeper.pid, "name": owners.FIXTURE_AGENT, "model": "test"}
        ),
        encoding="utf-8",
    )
    agent_env = dict(
        env,
        SASE_AGENT="1",
        SASE_AGENT_NAME=owners.FIXTURE_AGENT,
        SASE_ARTIFACTS_DIR=str(artifacts),
    )
    try:
        proc = h.run(
            [
                "tool",
                "run",
                "-d",
                "--",
                "sh",
                "-c",
                "sleep 25; echo escalate-live; exit 3",
            ],
            env=agent_env,
            cwd=project,
        )
        run_id = _run_id_from_ack(proc.stdout)
        if proc.returncode != 0 or not run_id:
            return case(
                "dod-17-live-escalate-join",
                False,
                dod=["DoD-17"],
                run_ids=[run_id],
                detach_exit=proc.returncode,
                detach_error=(proc.stderr or proc.stdout)[-400:],
            )
        joined = h.run(
            [
                "monitor",
                "start",
                "-J",
                run_id,
                "-p",
                "verify",
                "-r",
                "finish escalated run (joined run)",
                "-n",
                "read the joined run with sase tool show",
                "-j",
            ],
            env=agent_env,
            cwd=project,
            timeout=120.0,
        )
        try:
            envelope = json.loads(joined.stdout)
        except json.JSONDecodeError:
            envelope = {}
        monitor_id = str(owners._find_key(envelope, "monitor_id") or "")
        settled = bool(monitor_id) and wait_for(
            lambda: bool(
                owners._monitor_record(h, env, monitor_id, project).get("is_terminal")
            ),
            timeout=90.0,
            step=0.5,
        )
        try:
            sleeper.wait(timeout=10)
            runner_killed = True
        except subprocess.TimeoutExpired:
            runner_killed = False
        final = _terminal(h, env, run_id) if run_id else {}
        rows = h.runs(env=env, cwd=h.tmp)
        h.note(
            run_id,
            "escalated run joined by a live monitor; one id end to end",
            owner=f"monitor:{monitor_id}",
            kind="live",
        )
        ok = (
            joined.returncode == 0
            and bool(monitor_id)
            and settled
            and runner_killed
            and final.get("state") == "failed"
            and final.get("exit_code") == 3
            and (final.get("join") or {}).get("id") == monitor_id
            and [row.get("run_id") for row in rows] == [run_id]
        )
        return case(
            "dod-17-live-escalate-join",
            ok,
            dod=["DoD-17"],
            run_ids=[run_id],
            monitor_id=monitor_id,
            join_exit=joined.returncode,
            monitor_settled=settled,
            runner_killed=runner_killed,
            final_state=final.get("state"),
            final_exit=final.get("exit_code"),
            join_id=(final.get("join") or {}).get("id"),
            rows=len(rows),
        )
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def detach_starter_death(h: Harness) -> dict[str, Any]:
    """Killing the starter stops the unjoined run with the exact reason."""

    env = h.world("detach-starter-death")
    agent_env, sleeper = _agent_env(h, env, "smoke-agent")
    proc = h.run(
        ["tool", "run", "-d", "--", "sh", "-c", "sleep 60"],
        env=agent_env,
    )
    run_id = _run_id_from_ack(proc.stdout)
    assert proc.returncode == 0 and run_id, proc.stderr[-2000:]
    sleeper.kill()
    sleeper.wait(timeout=10)
    final = _wait_settled(h, env, run_id, timeout=60.0)
    stop = final.get("stop_request") or {}
    notified = h.run(["notify", "list", "-j"], env=env, cwd=h.tmp)
    try:
        rows = json.loads(notified.stdout)
    except json.JSONDecodeError:
        rows = None
    deliveries = (
        sum(
            1
            for row in rows
            if row.get("sender") == "tool-run"
            and (row.get("action_data") or {}).get("run_id") == run_id
        )
        if isinstance(rows, list)
        else -1
    )
    ok = (
        final.get("state") == "signaled"
        and final.get("terminal_cause") == "stop_requested"
        and stop.get("requested_by") == "sase"
        and stop.get("reason") == "starter agent smoke-agent ended without joining"
        and deliveries == 0
    )
    return case(
        "dod-17-detach-starter-death",
        ok,
        dod=["DoD-17"],
        run_ids=[run_id],
        final_state=final.get("state"),
        terminal_cause=final.get("terminal_cause"),
        requested_by=stop.get("requested_by"),
        reason=stop.get("reason"),
        deliveries=deliveries,
    )

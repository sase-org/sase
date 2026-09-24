"""Harness cases: the durable ToolRun hand-off contract (DoD-14 hermetic, DoD-15 live).

Each case maps one row of the E2 acceptance fault matrix to a black-box
report case. Every case drives the real ``sase`` CLI against an isolated
``SASE_HOME`` and a temporary git project with fixture commands only; fault
injection happens only at the filesystem/process boundary. Cases that need
the real proc/monitor supervisors to execute work are live-gated and report
``not-run`` without ``--live``.

Matrix mapping:

- caller exits right after an accepted ``-H`` ......... ``dod-14-handoff-accept``
- acknowledgement lost, request retried ............... ``dod-14-handoff-ack-retry``
- store cannot record the launch ...................... ``dod-14-handoff-fail-closed``
- submit fails after the reservation .................. ``dod-14-handoff-submit-fails``
- ``-H`` misuse is refused before reserving ........... ``dod-14-handoff-refusals``
- catalog edited after acceptance ..................... ``dod-14-handoff-frozen``
- owner log missing after settlement .................. ``dod-14-handoff-owner-log-missing``
- stop while starting, running, and completing ........ ``dod-14-live-handoff-stop``
- viewer Ctrl-C (``show -F``, ``wait``) ............... ``dod-14-live-handoff-viewers``
- worker crash while the owner is alive ............... ``dod-14-live-handoff-crash``
- settlement delivery ................................. ``dod-14-live-handoff-delivery``
- agent-style monitor hand-off (live) ................. ``dod-14-live-monitor-handoff``
"""

from __future__ import annotations

import json
import os
import signal
import stat
from pathlib import Path
from typing import Any

import _smoke_tool_runs_cases_owners as owners
from _smoke_tool_runs_lib import (
    Harness,
    case,
    not_run,
    wait_for,
)


def _ack_run_id(stdout: str) -> str:
    """The durable run id from the hand-off acknowledgement on stdout."""

    for line in stdout.splitlines():
        if line.startswith("sase tool run "):
            return line.split()[-1]
    return ""


def _handoff(args: list[str], h: Harness, env: dict[str, str]) -> Any:
    return h.run(["tool", "run", "-H", *args], env=env)


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


def accept(h: Harness) -> dict[str, Any]:
    """An accepted hand-off is observable at once and settles normally."""

    env = h.world("handoff-accept")
    proc = _handoff(["--", "sh", "-c", "sleep 3; exit 7"], h, env)
    run_id = _ack_run_id(proc.stdout)
    # The caller is already gone (``run`` returned) while the command runs:
    # the reservation is durable before the acknowledgement.
    early = _terminal(h, env, run_id)
    procs = json.loads(
        h.run(["proc", "list", "-j"], env=env, cwd=h.tmp).stdout or "{}"
    ).get("procs") or []
    owned = [p for p in procs if f"tool-run:{run_id}" in (p.get("tags") or [])]
    worker_argv = (owned[0].get("argv") or []) if owned else []
    waited = h.run(["tool", "wait", run_id], env=env, cwd=h.tmp, timeout=60.0)
    final = _terminal(h, env, run_id)
    h.note(run_id, "accepted hand-off settles under its proc", owner="proc")
    ok = (
        proc.returncode == 0
        and bool(run_id)
        and early.get("state") in ("created", "running")
        and early.get("launch_mode") == "handoff"
        and early.get("owner_kind") == "proc"
        and bool(early.get("owner_id"))
        and len(owned) == 1
        and worker_argv[-2:] == ["_adopt", run_id]
        and waited.returncode == 7
        and final.get("state") == "failed"
        and final.get("exit_code") == 7
        and final.get("terminal_cause") == "exited"
    )
    return case(
        "dod-14-handoff-accept",
        ok,
        dod=["DoD-14"],
        run_ids=[run_id],
        early_state=early.get("state"),
        launch_mode=early.get("launch_mode"),
        owner_kind=early.get("owner_kind"),
        owner_proc_count=len(owned),
        wait_exit=waited.returncode,
        final_state=final.get("state"),
        final_exit=final.get("exit_code"),
    )


def ack_retry(h: Harness) -> dict[str, Any]:
    """A lost acknowledgement is a retry, not a replay: two runs, each once."""

    env = h.world("handoff-retry")
    first = _handoff(["--", "true"], h, env)
    second = _handoff(["--", "true"], h, env)
    first_id = _ack_run_id(first.stdout)
    second_id = _ack_run_id(second.stdout)
    h.run(["tool", "wait", first_id], env=env, cwd=h.tmp, timeout=60.0)
    h.run(["tool", "wait", second_id], env=env, cwd=h.tmp, timeout=60.0)
    rows = [r for r in h.runs(env=env) if r.get("run_id") in (first_id, second_id)]
    states = {r.get("run_id"): r.get("state") for r in rows}
    h.note(first_id, "first run stays discoverable after ack loss", owner="proc")
    h.note(second_id, "retry is a separate run", owner="proc")
    ok = (
        first.returncode == 0
        and second.returncode == 0
        and bool(first_id)
        and bool(second_id)
        and first_id != second_id
        and len(rows) == 2
        and states.get(first_id) == "succeeded"
        and states.get(second_id) == "succeeded"
    )
    return case(
        "dod-14-handoff-ack-retry",
        ok,
        dod=["DoD-14"],
        run_ids=[first_id, second_id],
        distinct=first_id != second_id,
        settled=list(states.values()),
    )


def launch_failures(h: Harness) -> list[dict[str, Any]]:
    """Crash at reserve and at submit: typed uncertainty, nothing replayed."""

    env = h.world("handoff-launch-fail")
    home = Path(env["SASE_HOME"])
    # Reserve cannot commit: the store directory is a file. Filesystem-boundary
    # fault only; no store surgery.
    (home / "tools").write_text("not-a-directory", encoding="utf-8")
    refused = _handoff(["--", "printf", "hi"], h, env)
    procs = json.loads(
        h.run(["proc", "list", "-j"], env=env, cwd=h.tmp).stdout or "{}"
    ).get("procs") or []
    # Foreground stays fail-open in the same broken state.
    foreground = h.run(["tool", "run", "--", "printf", "hi"], env=env)
    (home / "tools").unlink()
    reserve_ok = (
        refused.returncode == 1
        and "nothing was started" in refused.stderr
        and not [p for p in procs if "tool-run" in (p.get("tags") or [])]
        and foreground.returncode == 0
        and foreground.stdout == "hi"
    )

    # Submit fails after the reservation: the proc store is read-only, so the
    # owner can never start and the run settles launch_failed.
    warmup = _handoff(["--", "printf", "warm"], h, env)
    warm_id = _ack_run_id(warmup.stdout)
    h.run(["tool", "wait", warm_id], env=env, cwd=h.tmp, timeout=60.0)
    runtime = home / "procs"
    runtime.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        submit = _handoff(["--", "printf", "hi"], h, env)
        submit_id = ""
        for line in submit.stderr.splitlines():
            if "could not start proc for" in line:
                submit_id = line.split("could not start proc for ")[1].split()[0]
                break
        submit_run = _terminal(h, env, submit_id) if submit_id else {}
        diagnostics = " ".join(
            str(d.get("message") if isinstance(d, dict) else d)
            for d in (submit_run.get("diagnostics") or ())
        )
    finally:
        runtime.chmod(stat.S_IRWXU)
    h.note(submit_id, "submit failure settles launch_failed", owner="proc")
    submit_ok = (
        submit.returncode == 1
        and bool(submit_id)
        and submit_run.get("state") == "failed"
        and submit_run.get("terminal_cause") == "launch_failed"
        and "command was not run" in diagnostics
    )
    return [
        case(
            "dod-14-handoff-fail-closed",
            reserve_ok,
            dod=["DoD-14"],
            refuse_exit=refused.returncode,
            nothing_started="nothing was started" in refused.stderr,
            foreground_exit=foreground.returncode,
            foreground_out=foreground.stdout,
        ),
        case(
            "dod-14-handoff-submit-fails",
            submit_ok,
            dod=["DoD-14"],
            run_ids=[submit_id],
            submit_exit=submit.returncode,
            final_state=submit_run.get("state"),
            terminal_cause=submit_run.get("terminal_cause"),
        ),
    ]


def refusals(h: Harness) -> dict[str, Any]:
    """``-H`` misuse is refused before anything is reserved."""

    env = h.world("handoff-refusals")
    agent_env = dict(env, SASE_AGENT="1")
    agent_proc = _handoff(["--", "printf", "hi"], h, agent_env)
    verbose = h.run(
        ["tool", "run", "-H", "-v", "--", "printf", "hi"], env=env
    )
    tail = h.run(
        ["tool", "run", "-H", "-T", "5", "--", "printf", "hi"], env=env
    )
    rows = h.runs(env=env)
    ok = (
        agent_proc.returncode == 2
        and "sase monitor start" in agent_proc.stderr
        and verbose.returncode == 2
        and tail.returncode == 2
        and rows == []
    )
    return case(
        "dod-14-handoff-refusals",
        ok,
        dod=["DoD-14"],
        agent_exit=agent_proc.returncode,
        verbose_exit=verbose.returncode,
        tail_exit=tail.returncode,
        runs_recorded=len(rows),
    )


def frozen_and_missing(h: Harness) -> list[dict[str, Any]]:
    """Frozen argv survives a catalog edit; a missing owner log is named."""

    env = h.world("handoff-frozen")
    project = h.make_project(
        "handoff-frozen-proj",
        {"emit": {"argv": ["sh", "-c", "echo ORIG"], "description": "x", "args": "deny"}},
    )
    accepted = h.run(["tool", "run", "-H", "emit"], env=env, cwd=project)
    run_id = _ack_run_id(accepted.stdout)
    (project / "sase" / "sase.yml").write_text(
        json.dumps(
            {
                "tools": {
                    "emit": {
                        "argv": ["sh", "-c", "echo CHANGED"],
                        "description": "x",
                        "args": "deny",
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    h.run(["tool", "wait", run_id], env=env, cwd=h.tmp, timeout=60.0)
    replay = h.run(["tool", "show", run_id, "-l"], env=env, cwd=project)
    h.note(run_id, "frozen argv runs under the original id", owner="proc")
    frozen_ok = (
        accepted.returncode == 0
        and bool(run_id)
        and "ORIG" in replay.stdout
        and "CHANGED" not in replay.stdout
    )

    missing_env = h.world("handoff-missing-log")
    launched = _handoff(["--", "printf", "hi"], h, missing_env)
    missing_id = _ack_run_id(launched.stdout)
    h.run(["tool", "wait", missing_id], env=missing_env, cwd=h.tmp, timeout=60.0)
    shown = h.show(missing_id, env=missing_env)
    owner_id = (shown.get("run") or {}).get("owner_id") or ""
    proc_shown = h.run(
        ["proc", "show", owner_id, "-f", "json"], env=missing_env, cwd=h.tmp
    )
    try:
        log_path = (json.loads(proc_shown.stdout).get("proc") or {}).get("log_path")
    except json.JSONDecodeError:
        log_path = ""
    if log_path:
        Path(str(log_path)).unlink(missing_ok=True)
    # Rotated/expired segments go with the log: drop the whole owner log set.
    if log_path:
        for sibling in Path(str(log_path)).parent.glob(f"{owner_id}.log*"):
            sibling.unlink(missing_ok=True)
    replay_missing = h.run(
        ["tool", "show", missing_id, "-l"], env=missing_env, cwd=h.tmp
    )
    summary = _terminal(h, missing_env, missing_id)
    replay_text = replay_missing.stdout + replay_missing.stderr
    missing_ok = (
        launched.returncode == 0
        and bool(missing_id)
        and bool(log_path)
        and summary.get("state") == "succeeded"
        and ("no longer retained" in replay_text
             or "missing or expired" in replay_text)
        and str(log_path) in replay_text
    )
    return [
        case(
            "dod-14-handoff-frozen",
            frozen_ok,
            dod=["DoD-14"],
            run_ids=[run_id],
            replay_has_orig="ORIG" in replay.stdout,
            replay_has_changed="CHANGED" in replay.stdout,
        ),
        case(
            "dod-14-handoff-owner-log-missing",
            missing_ok,
            dod=["DoD-14"],
            run_ids=[missing_id],
            summary_state=summary.get("state"),
            replay_exit=replay_missing.returncode,
        ),
    ]


def live_stop(h: Harness) -> dict[str, Any]:
    """Stop while starting, running, and completing; strangers never signaled."""

    if not h.live:
        return not_run(
            "dod-14-live-handoff-stop",
            "live cases were not requested; pass --live",
            dod=["DoD-15"],
        )
    env = h.world("handoff-stop")
    slow = _handoff(["--", "sh", "-c", "sleep 120"], h, env)
    slow_id = _ack_run_id(slow.stdout)
    assert slow.returncode == 0 and slow_id
    starting = _handoff(["--", "sh", "-c", "sleep 120"], h, env)
    starting_id = _ack_run_id(starting.stdout)
    stopped_early = h.run(["tool", "stop", starting_id], env=env, cwd=h.tmp)
    finishing = _handoff(["--", "sh", "-c", "sleep 1"], h, env)
    finishing_id = _ack_run_id(finishing.stdout)
    raced = h.run(["tool", "stop", finishing_id], env=env, cwd=h.tmp)
    raced_wait = h.run(["tool", "wait", finishing_id], env=env, cwd=h.tmp, timeout=60.0)

    # Still unsettled (claim timing is supervisor-scheduled: created or
    # running); the stop below covers both the starting and running paths.
    # No waiting here: slow outlives every later step by minutes.
    settled_slow = _terminal(h, env, slow_id)
    assert settled_slow.get("state") in ("created", "running")
    stranger = h.run(["proc", "run", "-s", "none", "--", "sleep", "120"], env=env)
    stranger_id = stranger.stdout.split()[0] if stranger.stdout.strip() else ""
    stopped = h.run(["tool", "stop", slow_id], env=env, cwd=h.tmp)
    waited = h.run(["tool", "wait", slow_id], env=env, cwd=h.tmp, timeout=60.0)
    final = _terminal(h, env, slow_id)
    early_final = _wait_settled(h, env, starting_id)
    raced_final = _terminal(h, env, finishing_id)
    already = h.run(["tool", "stop", slow_id], env=env, cwd=h.tmp)
    stranger_shown = h.run(
        ["proc", "show", stranger_id, "-f", "json"], env=env, cwd=h.tmp
    )
    try:
        stranger_state = (json.loads(stranger_shown.stdout).get("proc") or {}).get(
            "status"
        )
    except json.JSONDecodeError:
        stranger_state = ""
    h.run(["proc", "stop", stranger_id], env=env, cwd=h.tmp)
    h.note(slow_id, "stop while running settles stop_requested", owner="proc")
    ok = (
        stopped_early.returncode == 0
        and early_final.get("state") == "signaled"
        and early_final.get("terminal_cause") == "stop_requested"
        and raced.returncode == 0
        and raced_wait.returncode in (0, 1)
        and raced_final.get("state") in ("succeeded", "failed", "signaled")
        and stopped.returncode == 0
        and waited.returncode == 1
        and final.get("state") == "signaled"
        and final.get("terminal_cause") == "stop_requested"
        and already.returncode == 0
        and "already" in (already.stdout + already.stderr)
        and stranger_state == "running"
    )
    return case(
        "dod-14-live-handoff-stop",
        ok,
        dod=["DoD-15"],
        run_ids=[slow_id, starting_id, finishing_id],
        early_final=early_final.get("state"),
        raced_wait_exit=raced_wait.returncode,
        raced_final=raced_final.get("state"),
        final_state=final.get("state"),
        stranger_state=stranger_state,
    )


def live_viewers(h: Harness) -> dict[str, Any]:
    """Killing the viewer never kills the run: Ctrl-C detaches at 130."""

    if not h.live:
        return not_run(
            "dod-14-live-handoff-viewers",
            "live cases were not requested; pass --live",
            dod=["DoD-15"],
        )
    import time

    env = h.world("handoff-viewers")
    launched = _handoff(["--", "sh", "-c", "sleep 15"], h, env)
    run_id = _ack_run_id(launched.stdout)
    assert launched.returncode == 0 and run_id
    _wait_settled(h, env, run_id, timeout=5.0)
    follow = h.spawn(["tool", "show", run_id, "-F"], env=env, cwd=h.tmp)
    waiter = h.spawn(["tool", "wait", run_id], env=env, cwd=h.tmp)
    time.sleep(4)
    follow.send_signal(signal.SIGINT)
    waiter.send_signal(signal.SIGINT)
    try:
        follow.wait(timeout=20)
    except Exception:  # noqa: BLE001 - a stuck viewer fails the case below.
        pass
    try:
        waiter.wait(timeout=20)
    except Exception:  # noqa: BLE001 - a stuck viewer fails the case below.
        pass
    mid = _terminal(h, env, run_id)
    waited = h.run(["tool", "wait", run_id], env=env, cwd=h.tmp, timeout=60.0)
    final = _terminal(h, env, run_id)
    h.note(run_id, "viewers detached; the run continued", owner="proc")
    ok = (
        follow.returncode == 130
        and waiter.returncode == 130
        and mid.get("state") in ("created", "running")
        and waited.returncode == 0
        and final.get("state") == "succeeded"
    )
    return case(
        "dod-14-live-handoff-viewers",
        ok,
        dod=["DoD-15"],
        run_ids=[run_id],
        follow_exit=follow.returncode,
        wait_exit=waiter.returncode,
        mid_state=mid.get("state"),
        final_state=final.get("state"),
    )


def live_crash(h: Harness) -> dict[str, Any]:
    """SIGKILL the worker while the owner lives: owner truth, no replay."""

    if not h.live:
        return not_run(
            "dod-14-live-handoff-crash",
            "live cases were not requested; pass --live",
            dod=["DoD-15"],
        )
    env = h.world("handoff-crash")
    marker = h.tmp / "handoff-crash.marker"
    launched = _handoff(
        ["--", "sh", "-c", f"echo MARK >> {marker}; sleep 60"], h, env
    )
    run_id = _ack_run_id(launched.stdout)
    assert launched.returncode == 0 and run_id
    running = _wait_settled(h, env, run_id, timeout=5.0)
    worker_pid = int(running.get("wrapper_pid") or 0)
    assert worker_pid > 0
    os.kill(worker_pid, signal.SIGKILL)
    final = _wait_settled(h, env, run_id, timeout=90.0)
    diagnostics = " ".join(
        str(d.get("message") if isinstance(d, dict) else d)
        for d in (final.get("diagnostics") or ())
    )
    marks = (
        marker.read_text(encoding="utf-8").split().count("MARK")
        if marker.exists()
        else -1
    )
    h.note(run_id, "worker crash settles from the owner result", owner="proc")
    ok = (
        final.get("state") in ("failed", "lost", "signaled")
        and final.get("state") != "succeeded"
        and bool(final.get("terminal_cause"))
        and marks == 1
    )
    return case(
        "dod-14-live-handoff-crash",
        ok,
        dod=["DoD-15"],
        run_ids=[run_id],
        final_state=final.get("state"),
        terminal_cause=final.get("terminal_cause"),
        settled_by=final.get("settled_by"),
        diagnostics_tail=diagnostics[-200:],
        marker_marks=marks,
    )


def live_delivery(h: Harness) -> dict[str, Any]:
    """Exactly one notification per proc-owned hand-off, however it settles."""

    if not h.live:
        return not_run(
            "dod-14-live-handoff-delivery",
            "live cases were not requested; pass --live",
            dod=["DoD-15"],
        )
    env = h.world("handoff-delivery")
    launched = _handoff(["--", "true"], h, env)
    run_id = _ack_run_id(launched.stdout)
    assert launched.returncode == 0 and run_id
    h.run(["tool", "wait", run_id], env=env, cwd=h.tmp, timeout=60.0)

    def deliveries() -> int:
        listed = h.run(["notify", "list", "-j"], env=env, cwd=h.tmp)
        try:
            rows = json.loads(listed.stdout)
        except json.JSONDecodeError:
            return -1
        return sum(
            1
            for row in rows
            if row.get("sender") == "tool-run"
            and (row.get("action_data") or {}).get("run_id") == run_id
        )

    first = deliveries()
    # Reconcile passes must not deliver again.
    h.run(["tool", "wait", run_id], env=env, cwd=h.tmp, timeout=60.0)
    h.runs(env=env)
    second = deliveries()
    h.note(run_id, "proc-owned hand-off delivered exactly once", owner="proc")
    ok = first == 1 and second == 1
    return case(
        "dod-14-live-handoff-delivery",
        ok,
        dod=["DoD-15"],
        run_ids=[run_id],
        deliveries_after_settle=first,
        deliveries_after_reconcile=second,
    )


def live_monitor_handoff(h: Harness) -> dict[str, Any]:
    """Agent-style monitor hand-off: id first, then follow, wait, and stop."""

    if not h.live:
        return not_run(
            "dod-14-live-monitor-handoff",
            "live cases were not requested; pass --live",
            dod=["DoD-15"],
        )
    env, project = owners._owner_world(h, "handoff-monitor")
    started = h.run(
        [
            "monitor",
            "start",
            "-a",
            owners.FIXTURE_AGENT,
            "-r",
            "harness hand-off fixture",
            "-s",
            "TESTING",
            "-S",
            "TESTED",
            "-t",
            "120s",
            "-j",
            "--",
            h.sase,
            "tool",
            "run",
            "check",
        ],
        env=env,
        cwd=project,
    )
    if started.returncode != 0:
        return case(
            "dod-14-live-monitor-handoff",
            False,
            dod=["DoD-15"],
            error=(started.stderr or started.stdout)[-400:],
        )
    try:
        envelope = json.loads(started.stdout)
    except json.JSONDecodeError:
        envelope = {}
    monitor_id = str(owners._find_key(envelope, "monitor_id") or "")
    run_id = str(owners._find_key(envelope, "tool_run_id") or "")
    named_in_output = run_id and run_id in started.stdout
    settled = wait_for(
        lambda: bool(
            owners._monitor_record(h, env, monitor_id, project).get("is_terminal")
        ),
        timeout=90.0,
        step=0.5,
    )
    run = _terminal(h, env, run_id) if run_id else {}
    listed = h.run(["notify", "list", "-j"], env=env, cwd=h.tmp)
    try:
        monitor_deliveries = sum(
            1
            for row in json.loads(listed.stdout)
            if row.get("sender") == "tool-run"
            and (row.get("action_data") or {}).get("run_id") == run_id
        )
    except json.JSONDecodeError:
        monitor_deliveries = -1
    h.note(
        run_id,
        "monitor-owned hand-off; delivery rides the monitor",
        owner=f"monitor:{monitor_id}",
        kind="live",
    )
    ok = (
        bool(monitor_id)
        and bool(run_id)
        and named_in_output
        and settled
        and run.get("owner_kind") == "monitor"
        and run.get("owner_id") == monitor_id
        and run.get("launch_mode") == "handoff"
        and run.get("state") == "failed"
        and run.get("exit_code") == 3
        and monitor_deliveries == 0
    )
    return case(
        "dod-14-live-monitor-handoff",
        ok,
        dod=["DoD-15"],
        run_ids=[run_id],
        monitor_id=monitor_id,
        named_before_handoff=named_in_output,
        owner_kind=run.get("owner_kind"),
        final_state=run.get("state"),
        monitor_deliveries=monitor_deliveries,
    )

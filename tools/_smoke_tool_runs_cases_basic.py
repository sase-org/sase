"""Harness cases: catalog, exact execution, signals, lost runs, and fail-open."""

from __future__ import annotations

import json
import os
import resource
import signal
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from _smoke_tool_runs_lib import (
    ROOT,
    Harness,
    case,
    group_alive,
    kill_tree,
    redact_run,
    redact_show,
    run_id_from,
    wait_for,
)


FIVE_TOOLS = ["check", "check-full", "install", "test", "test-visual"]
LOST_REASON = "runner exited without settling"


def core_round_trip(h: Harness) -> dict[str, Any]:
    env = h.world("core-round-trip")
    try:
        result = h.helper("core-round-trip", env=env)
    except Exception as exc:  # noqa: BLE001 - reported as a failed case.
        return case("core-ledger-round-trip", False, dod=["DoD-10"], error=str(exc))
    return case(
        "core-ledger-round-trip",
        bool(result.get("ok")),
        dod=["DoD-10"],
        run_ids=[result.get("run_id", "")],
        **{k: v for k, v in result.items() if k not in {"ok", "run_id"}},
    )


def catalog(h: Harness) -> list[dict[str, Any]]:
    bare = h.run(["tool"], cwd=ROOT)
    bare_text = bare.stdout + bare.stderr
    listed = h.run(["tool", "list", "-j"], cwd=ROOT)
    helped = h.run(["tool", "-h"], cwd=ROOT)
    payload: dict[str, Any] = {}
    if listed.returncode == 0:
        payload = json.loads(listed.stdout)
    tools = payload.get("tools") or []
    names = [item.get("name") for item in tools]
    sase_ok = (
        bare.returncode == 0
        and "delegating to 'sase tool list'" in bare_text
        and all(name in bare.stdout for name in FIVE_TOOLS)
        and "—" in bare.stdout
        and names == FIVE_TOOLS
        and payload.get("schema_version") == 1
        and all(
            t.get("last") is None and t.get("typical_duration_ms") is None
            for t in tools
        )
        and "{list,run,runs,show}" in helped.stdout
    )

    h.snapshots["catalog"] = {
        "schema_version": payload.get("schema_version"),
        "tools": [
            {
                key: item.get(key)
                for key in (
                    "name",
                    "digest",
                    "args",
                    "stages",
                    "typical_sample_count",
                    "typical_duration_ms",
                )
            }
            | {"last": item.get("last")}
            for item in tools
        ],
    }
    fixture = h.run(["tool", "list", "-j"])
    fixture_payload = json.loads(fixture.stdout) if fixture.returncode == 0 else {}
    fixture_names = [t.get("name") for t in fixture_payload.get("tools") or ()]
    fixture_ok = fixture_names == ["check", "quick", "test"]

    marker_dir = h.tmp / "malformed-marker"
    marker_dir.mkdir()
    marker = marker_dir / "spawned"
    bad = h.make_project(
        "malformed-project",
        {
            "ping": {
                "argv": ["sh", "-c", f"printf x >> {marker}"],
                "description": "bad",
                "shell": True,
            },
        },
    )
    empty = h.make_project(
        "empty-argv-project",
        {"empty": {"argv": [], "description": "empty"}},
    )
    bad_list = h.run(["tool", "list", "-j"], cwd=bad)
    bad_run = h.run(["tool", "run", "ping"], cwd=bad)
    empty_list = h.run(["tool", "list", "-j"], cwd=empty)
    empty_run = h.run(["tool", "run", "empty"], cwd=empty)
    bad_text = bad_list.stderr + bad_list.stdout
    run_text = bad_run.stderr + bad_run.stdout
    empty_text = empty_run.stderr + empty_run.stdout
    malformed_ok = (
        bad_list.returncode == 2
        and "tools.ping" in bad_text
        and "shell" in bad_text
        and bad_run.returncode == 2
        and "tools.ping" in run_text
        and "shell" in run_text
        and empty_list.returncode == 2
        and empty_run.returncode == 2
        and "tools.empty" in empty_text
        and "argv" in empty_text
        and not marker.exists()
    )
    unknown = h.run(["tool", "run", "no-such-tool"])
    unknown_ok = unknown.returncode == 2 and "no-such-tool" in (
        unknown.stderr + unknown.stdout
    )
    return [
        case(
            "dod-1-catalog-sase",
            sase_ok,
            dod=["DoD-1"],
            names=names,
            delegation_notice="delegating to 'sase tool list'" in bare_text,
            schema_version=payload.get("schema_version"),
        ),
        case(
            "dod-1-catalog-fixture",
            fixture_ok and unknown_ok,
            dod=["DoD-1"],
            names=fixture_names,
            unknown_tool_exit=unknown.returncode,
        ),
        case(
            "dod-1-malformed",
            malformed_ok,
            dod=["DoD-1"],
            list_exit=bad_list.returncode,
            run_exit=bad_run.returncode,
            empty_argv_exit=empty_run.returncode,
            spawned=marker.exists(),
            diagnostic=bad_text[-300:],
        ),
    ]


def exact_execution(h: Harness) -> list[dict[str, Any]]:
    proc = h.run(
        ["tool", "run", "--", "sh", "-c", "printf out; printf err >&2; exit 3"]
    )
    run_id = run_id_from(proc.stderr)
    shown = h.show(run_id) if run_id else {}
    run = shown.get("run") or {}
    logs = run.get("logs") or {}
    replay = h.run(["tool", "show", run_id, "-l"]) if run_id else None
    tools_root = h.home / "tools"
    modes_ok = False
    try:
        modes_ok = (
            stat.S_IMODE(tools_root.stat().st_mode) == 0o700
            and stat.S_IMODE((tools_root / "runs.sqlite").stat().st_mode) == 0o600
            and stat.S_IMODE(Path(str(logs.get("stdout_path"))).stat().st_mode) == 0o600
        )
    except OSError:
        modes_ok = False
    exact_ok = (
        proc.returncode == 3
        and proc.stdout == "out"
        and "err" in proc.stderr
        and proc.stderr.startswith("sase tool run ")
        and run.get("state") == "failed"
        and run.get("exit_code") == 3
        and bool(logs.get("stdout_path"))
        and bool(logs.get("stderr_path"))
        and replay is not None
        and replay.returncode == 0
        and replay.stdout == "out"
        and replay.stderr == "err"
        and modes_ok
    )
    h.note(run_id, "exact stdout/stderr/exit passthrough")
    h.snapshots["show"] = redact_show(shown)
    h.snapshots["runs"] = [redact_run(r) for r in h.runs()[:3]]

    argv_tokens = ["a b", "", "$HOME `x` ; *", "--", "-n", "'q'", "\t tab", "é"]
    literal = h.run(
        [
            "tool",
            "run",
            "--",
            sys.executable,
            "-c",
            "import sys; sys.stdout.write(repr(sys.argv[1:]))",
            *argv_tokens,
        ]
    )
    literal_ok = literal.returncode == 0 and literal.stdout == repr(argv_tokens)
    h.note(run_id_from(literal.stderr), "literal argv tokens survive unchanged")

    missing = h.run(["tool", "run", "--", "definitely-not-an-executable"])
    plain = h.tmp / "not-executable.txt"
    plain.write_text("echo nope\n", encoding="utf-8")
    plain.chmod(0o644)
    denied = h.run(["tool", "run", "--", str(plain)])
    # A launch error never printed a durable id, so find the rows by their argv.
    recorded = {tuple(r.get("display_argv") or ()): r for r in h.runs()}
    missing_show = recorded.get(("definitely-not-an-executable",)) or {}
    denied_show = recorded.get((str(plain),)) or {}
    launch_ok = (
        missing.returncode == 127
        and "executable not found" in missing.stderr
        and missing_show.get("state") == "failed"
        and missing_show.get("exit_code") == 127
        and denied.returncode == 126
        and "not executable" in denied.stderr
        and denied_show.get("state") == "failed"
        and denied_show.get("exit_code") == 126
    )
    return [
        case(
            "dod-2-exact-execution",
            exact_ok,
            dod=["DoD-2"],
            run_ids=[run_id],
            exit=proc.returncode,
            stdout=proc.stdout,
            stderr_tail=proc.stderr[-200:],
            state=run.get("state"),
            exit_code=run.get("exit_code"),
            replay_stdout=replay.stdout if replay else None,
            replay_stderr=replay.stderr if replay else None,
            private_modes=modes_ok,
        ),
        case(
            "dod-2-literal-argv",
            literal_ok,
            dod=["DoD-2"],
            exit=literal.returncode,
            stdout=literal.stdout,
        ),
        case(
            "dod-2-launch-errors",
            launch_ok,
            dod=["DoD-2"],
            missing_exit=missing.returncode,
            not_executable_exit=denied.returncode,
        ),
    ]


def signals(h: Harness) -> dict[str, Any]:
    outcomes: dict[str, Any] = {}
    ok = True
    for name, signum, exit_code, state in (
        ("sigterm", signal.SIGTERM, 143, "signaled"),
        ("sigint", signal.SIGINT, 130, "interrupted"),
    ):
        proc = h.spawn(["tool", "run", "--", "sleep", "30"])
        result = _signal_run(h, proc, signum, exit_code, state)
        outcomes[name] = result
        ok = ok and bool(result["ok"])
    return case(
        "dod-3-signals",
        ok,
        dod=["DoD-3"],
        run_ids=[outcomes[k].get("run_id", "") for k in outcomes],
        **outcomes,
    )


def _signal_run(
    h: Harness,
    proc: subprocess.Popen[str],
    signum: int,
    expected_exit: int,
    expected_state: str,
) -> dict[str, Any]:
    def running() -> dict[str, Any] | None:
        for item in h.runs("-s", "running"):
            if item.get("wrapper_pid") == proc.pid:
                return item
        return None

    if not wait_for(lambda: running() is not None):
        kill_tree(proc)
        return {"ok": False, "reason": "running row never appeared"}
    row = running() or {}
    os.kill(proc.pid, signum)
    try:
        code = proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        return {"ok": False, "reason": "wrapper did not exit after the signal"}
    if code < 0:
        code = 128 - code
    shown = (h.show(str(row.get("run_id"))).get("run")) or {}
    pgid = shown.get("child_pgid")
    survivors = not wait_for(lambda: not group_alive(pgid), timeout=5.0)
    ok = (
        code == expected_exit and shown.get("state") == expected_state and not survivors
    )
    h.note(str(row.get("run_id")), f"wrapper {expected_state} by signal")
    return {
        "ok": ok,
        "run_id": row.get("run_id"),
        "exit": code,
        "state": shown.get("state"),
        "child_group_survived": survivors,
    }


def lost(h: Harness) -> dict[str, Any]:
    pid_file = h.tmp / "lost-child.pid"
    script = h.tmp / "lost-child.py"
    script.write_text(
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    proc = h.spawn(["tool", "run", "--", sys.executable, str(script)])
    child_pid: int | None = None
    try:
        if not wait_for(
            lambda: any(
                r.get("wrapper_pid") == proc.pid for r in h.runs("-s", "running")
            )
        ):
            return case(
                "dod-4-lost", False, dod=["DoD-4"], error="running row never appeared"
            )
        wait_for(pid_file.exists, timeout=10.0)
        child_pid = int(pid_file.read_text(encoding="utf-8"))
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        row = next((r for r in h.runs() if r.get("wrapper_pid") == proc.pid), {})
        again = next((r for r in h.runs() if r.get("wrapper_pid") == proc.pid), {})
        ok = (
            row.get("state") == "lost"
            and again.get("state") == "lost"
            and row.get("lost_reason") == LOST_REASON
            and row.get("duration_ms") is None
            and row.get("exit_code") is None
        )
        h.note(str(row.get("run_id")), "wrapper SIGKILLed; reported lost")
        return case(
            "dod-4-lost",
            ok,
            dod=["DoD-4"],
            run_ids=[str(row.get("run_id"))],
            state=row.get("state"),
            lost_reason=row.get("lost_reason"),
            duration_ms=row.get("duration_ms"),
            exit_code=row.get("exit_code"),
        )
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except OSError:
                pass


def liveness(h: Harness) -> dict[str, Any]:
    boot_file = Path("/proc/sys/kernel/random/boot_id")
    if not boot_file.exists():
        return case("dod-4-liveness", True, dod=["DoD-4"], skipped="no /proc boot id")
    env = h.world("liveness")
    sleeper = subprocess.Popen(
        ["sleep", "120"], start_new_session=True, stdout=subprocess.DEVNULL
    )
    h.children.append(sleeper)  # type: ignore[arg-type]
    seeded = h.helper(
        "seed-liveness",
        {
            "boot_id": boot_file.read_text(encoding="utf-8").strip(),
            "alive_pid": sleeper.pid,
            "project": "liveness-fixture",
        },
        env=env,
    )
    ids = seeded["run_ids"]
    rows = {r["run_id"]: r for r in h.runs(env=env)}
    again = {r["run_id"]: r for r in h.runs(env=env)}

    def facts(label: str) -> dict[str, Any]:
        row = rows.get(ids[label]) or {}
        return {"state": row.get("state"), "reason": row.get("lost_reason")}

    observed = {label: facts(label) for label in ids}
    ok = (
        observed["alive"]["state"] == "running"
        and observed["unknown"]["state"] == "running"
        and observed["boot-changed"] == {"state": "lost", "reason": LOST_REASON}
        and observed["pid-reused"] == {"state": "lost", "reason": LOST_REASON}
        and (again.get(ids["boot-changed"]) or {}).get("state") == "lost"
        and all(
            (rows.get(ids[k]) or {}).get("exit_code") is None
            and (rows.get(ids[k]) or {}).get("duration_ms") is None
            for k in ("boot-changed", "pid-reused")
        )
    )
    return case(
        "dod-4-liveness",
        ok,
        dod=["DoD-4"],
        run_ids=list(ids.values()),
        **observed,
    )


_PROBE_ENV = (
    "import os, sys; "
    "sys.stdout.write(repr((os.environ.get('SASE_TOOL_RUN_ID'), "
    "os.environ.get('SASE_TOOL_RUN_EVENTS'))))"
)


def fail_open(h: Harness) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # An unwritable store: `tools` is a regular file, so no ledger can be created.
    blocked = h.world("blocked")
    (Path(blocked["SASE_HOME"]) / "tools").write_text(
        "not-a-directory", encoding="utf-8"
    )
    stale = dict(
        blocked,
        SASE_TOOL_RUN_ID="stale-parent",
        SASE_TOOL_RUN_EVENTS="/nonexistent/e.jsonl",
    )
    marker = h.tmp / "fail-open-marker"
    proc = h.run(
        [
            "tool",
            "run",
            "--",
            sys.executable,
            "-c",
            f"open({str(marker)!r}, 'a').write('x'); {_PROBE_ENV}",
        ],
        env=stale,
    )
    hi = h.run(["tool", "run", "--", "echo", "hi"], env=blocked)
    ok = (
        proc.returncode == 0
        and proc.stdout == "(None, None)"
        and proc.stderr.count("run not recorded") == 1
        and "sase tool run " not in proc.stderr
        and marker.read_text(encoding="utf-8") == "x"
        and hi.returncode == 0
        and hi.stdout == "hi\n"
        and hi.stderr.count("run not recorded") == 1
    )
    cases.append(
        case(
            "dod-5-fail-open",
            ok,
            dod=["DoD-5"],
            exit=hi.returncode,
            stdout=hi.stdout,
            child_env_cleared=proc.stdout,
            executions=len(marker.read_text(encoding="utf-8")),
            warnings=hi.stderr.count("run not recorded"),
        )
    )

    # A store locked by another writer: begin fails after the bounded busy wait.
    env = h.world("locked")
    h.run(["tool", "run", "--", "true"], env=env)
    store = Path(env["SASE_HOME"]) / "tools" / "runs.sqlite"
    lock_marker = h.tmp / "lock-marker"
    connection = sqlite3.connect(store, isolation_level=None, timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        locked = h.run(
            [
                "tool",
                "run",
                "--",
                "sh",
                "-c",
                f"printf hi; printf x >> {lock_marker}; exit 5",
            ],
            env=env,
        )
    finally:
        connection.execute("ROLLBACK")
        connection.close()
    recovered = h.run(["tool", "run", "--", "true"], env=env)
    lock_ok = (
        locked.returncode == 5
        and locked.stdout == "hi"
        and locked.stderr.count("run not recorded") == 1
        and "sase tool run " not in locked.stderr
        and lock_marker.read_text(encoding="utf-8") == "x"
        and bool(run_id_from(recovered.stderr))
    )
    cases.append(
        case(
            "dod-5-lock",
            lock_ok,
            dod=["DoD-5"],
            exit=locked.returncode,
            executions=len(lock_marker.read_text(encoding="utf-8")),
            warnings=locked.stderr.count("run not recorded"),
            recovers_after_release=bool(run_id_from(recovered.stderr)),
        )
    )

    # The store becomes unwritable after a healthy begin: finish cannot commit.
    env = h.world("mid-write")
    home = env["SASE_HOME"]
    mid_marker = h.tmp / "mid-marker"
    script = (
        f"chmod 000 {home}/tools/runs.sqlite*; chmod 500 {home}/tools; "
        f"printf x >> {mid_marker}; printf mid; exit 7"
    )
    mid = h.run(["tool", "run", "--", "sh", "-c", script], env=env)
    subprocess.run(["chmod", "-R", "u+rwX", home], check=False)
    row = next(iter(h.runs(env=env)), {})
    mid_ok = (
        mid.returncode == 7
        and mid.stdout == "mid"
        and mid.stderr.count("recording incomplete") == 1
        and mid_marker.read_text(encoding="utf-8") == "x"
        and row.get("state") in {"running", "lost"}
        and row.get("exit_code") is None
    )
    h.note(str(row.get("run_id")), "finish could not commit; never settled by guess")
    cases.append(
        case(
            "dod-5-mid-write",
            mid_ok,
            dod=["DoD-5"],
            run_ids=[str(row.get("run_id"))],
            exit=mid.returncode,
            executions=len(mid_marker.read_text(encoding="utf-8")),
            durable_state=row.get("state"),
            durable_exit_code=row.get("exit_code"),
        )
    )

    # Retained-log writes fail (RLIMIT_FSIZE) while the child is still streamed.
    env = h.world("log-failure")

    def limit_file_size() -> None:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))

    payload = 3 << 20
    logfail = h.run(
        [
            "tool",
            "run",
            "--",
            sys.executable,
            "-c",
            f"import sys; sys.stdout.write('x' * {payload}); sys.exit(4)",
        ],
        env=env,
        preexec=limit_file_size,
    )
    logfail_id = run_id_from(logfail.stderr)
    logfail_run = h.show(logfail_id, env=env).get("run") or {}
    log_ok = (
        logfail.returncode == 4
        and len(logfail.stdout) == payload
        and logfail.stderr.count("recording incomplete") == 1
        and logfail_run.get("state") == "failed"
        and logfail_run.get("exit_code") == 4
    )
    h.note(logfail_id, "retained-log write failure kept exact execution")
    cases.append(
        case(
            "dod-5-log-failure",
            log_ok,
            dod=["DoD-5"],
            run_ids=[logfail_id],
            exit=logfail.returncode,
            streamed_bytes=len(logfail.stdout),
            state=logfail_run.get("state"),
        )
    )
    return cases


def handshake(h: Harness) -> dict[str, Any]:
    marker = h.tmp / "handshake-state"
    counter = h.tmp / "handshake-count"
    script = h.tmp / "handshake.py"
    script.write_text(
        "import os, sqlite3\n"
        "from pathlib import Path\n"
        "run_id = os.environ['SASE_TOOL_RUN_ID']\n"
        "store = Path(os.environ['SASE_HOME']) / 'tools' / 'runs.sqlite'\n"
        "row = sqlite3.connect(store).execute(\n"
        "    'select state from runs where run_id = ?', (run_id,)\n"
        ").fetchone()\n"
        f"Path({str(marker)!r}).write_text(row[0] if row else 'missing')\n"
        f"open({str(counter)!r}, 'a').write('x')\n",
        encoding="utf-8",
    )
    proc = h.run(["tool", "run", "--", sys.executable, str(script)])
    state = marker.read_text(encoding="utf-8") if marker.exists() else "absent"
    executions = len(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    run_id = run_id_from(proc.stderr)
    ok = proc.returncode == 0 and state == "running" and executions == 1
    h.note(run_id, "child observed its own durable running row")
    return case(
        "dod-5-running-before-spawn",
        ok,
        dod=["DoD-5"],
        run_ids=[run_id],
        state_seen_by_child=state,
        executions=executions,
    )

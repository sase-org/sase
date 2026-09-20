"""Harness cases: timelines, evidence, cohorts, samples, and agent-facing output."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from _smoke_tool_runs_lib import (
    Harness,
    case,
    run_id_from,
    standard_catalog,
    standard_files,
)


def _evidence_project(h: Harness, name: str = "evidence-project") -> Path:
    return h.make_project(name, standard_catalog(), standard_files())


def _dirty_paths(fingerprint: dict[str, Any]) -> list[str]:
    return [
        str(item.get("path"))
        for repo in fingerprint.get("repos") or ()
        for item in repo.get("dirty_paths") or ()
    ]


def _human_field(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.startswith(label):
            return line[len(label) :].strip()
    return ""


def timeline_and_evidence(h: Harness) -> list[dict[str, Any]]:
    project = _evidence_project(h)
    env = h.world("timeline")
    (project / "dirty.txt").write_text("untracked\n", encoding="utf-8")

    proc = h.run(["tool", "run", "check"], env=env, cwd=project)
    run_id = run_id_from(proc.stderr)
    shown = h.show(run_id, env=env)
    run = shown.get("run") or {}
    stages = shown.get("stages") or []
    names = [stage.get("description") for stage in stages]
    ids = [stage.get("stage_id") for stage in stages]
    human = h.run(["tool", "show", run_id], env=env, cwd=project)
    unattributed = shown.get("unattributed_ms")
    duration = run.get("duration_ms")
    before = run.get("fingerprint_before") or {}
    after = run.get("fingerprint_after") or {}
    toolchain = (after.get("toolchain") or {}).get("python") or {}
    samples = shown.get("samples") or []
    h.note(run_id, "named staged check fixture")

    compact = h.run(["tool", "run", "-q", "check"], env=env, cwd=project)
    compact_id = run_id_from(compact.stderr)
    compact_shown = h.show(compact_id, env=env)
    compact_names = [
        line.split("  ")[0]
        for line in compact.stderr.splitlines()
        if re.match(r"^(alpha|beta|gamma)  ", line)
    ]
    compact_unattrib = next(
        (
            line.split("  ", 1)[1]
            for line in compact.stderr.splitlines()
            if line.startswith("unattrib  ")
        ),
        "",
    )
    h.note(compact_id, "compact footer parity with show")

    timeline_ok = (
        proc.returncode == 3
        and run.get("tool_name") == "check"
        and run.get("state") == "failed"
        and run.get("exit_code") == 3
        and names == ["alpha", "alpha", "beta"]
        and len(set(ids)) == 3
        and all(type(stage.get("elapsed_ms")) is int for stage in stages)
        and stages[2].get("exit_code") == 3
        and stages[2].get("elapsed_ms", 0) >= 200
        and all(stage.get("incomplete") is False for stage in stages)
        and type(unattributed) is int
        and type(duration) is int
        and 0 <= unattributed <= duration
        and human.returncode == 0
        and "STAGES" in human.stdout
        and "gamma" not in human.stdout
        and _human_field(human.stdout, "UNATTRIB").split()[0] != ""
        and compact.returncode == 3
        and compact_names
        == [s.get("description") for s in compact_shown.get("stages") or ()]
        and compact_unattrib
        and compact_unattrib
        == _human_field(
            h.run(["tool", "show", compact_id], env=env, cwd=project).stdout, "UNATTRIB"
        )
    )
    evidence_ok = (
        before.get("schema_version") == 1
        and after.get("schema_version") == 1
        and (before.get("completeness") or {}).get("complete") is True
        and (after.get("completeness") or {}).get("complete") is True
        and "dirty.txt" in _dirty_paths(before)
        and "dirty.txt" in _dirty_paths(after)
        and run.get("mutated_input") is False
        and (run.get("evidence_completeness") or {}).get("complete") is True
        and str(toolchain.get("output") or "").startswith("Python ")
        and len(samples) >= 2
        and _human_field(human.stdout, "DIRTY") == "1 -> 1"
        and _human_field(human.stdout, "TOOLCHAIN").startswith("python=Python")
    )

    mutate = h.run(
        ["tool", "run", "--", "sh", "-c", "printf x >> dirty.txt"], env=env, cwd=project
    )
    mutate_id = run_id_from(mutate.stderr)
    mutated = h.show(mutate_id, env=env).get("run") or {}
    h.note(mutate_id, "input mutated during execution")

    # Two checkouts with identical contents at different physical paths.
    twin_root = h.tmp / "twin"
    twin_root.mkdir()
    twin_a = h.make_project("twin-a", standard_catalog(), standard_files())
    twin_b = twin_root / "twin-a"
    shutil.copytree(twin_a, twin_b, symlinks=True)
    fp_a = (
        h.show(
            run_id_from(h.run(["tool", "run", "quick"], env=env, cwd=twin_a).stderr),
            env=env,
        ).get("run")
        or {}
    ).get("fingerprint_before")
    fp_b = (
        h.show(
            run_id_from(h.run(["tool", "run", "quick"], env=env, cwd=twin_b).stderr),
            env=env,
        ).get("run")
        or {}
    ).get("fingerprint_before")

    # Missing observations are typed facts, never guesses.
    incomplete_project = h.make_project(
        "incomplete-project",
        {
            "probe": {
                "argv": [sys.executable, "-c", "print('ran')"],
                "description": "Fixture with unobservable evidence.",
                "fingerprint": {
                    "toolchain": {
                        "absent": ["definitely-not-a-probe-binary", "--version"],
                        "slow": ["sleep", "5"],
                        "failing": [sys.executable, "-c", "raise SystemExit(3)"],
                    }
                },
            }
        },
    )
    probe = h.run(["tool", "run", "probe"], env=env, cwd=incomplete_project)
    probe_id = run_id_from(probe.stderr)
    probe_run = h.show(probe_id, env=env).get("run") or {}
    missing = (probe_run.get("evidence_completeness") or {}).get("missing") or []
    incomplete_ok = (
        probe.returncode == 0
        and probe.stdout == "ran\n"
        and (probe_run.get("evidence_completeness") or {}).get("complete") is False
        and len(missing) >= 3
        and any("exited 3" in item for item in missing)
        and probe_run.get("mutated_input") is None
    )
    h.note(probe_id, "unobservable probes reported as incomplete evidence")

    return [
        case(
            "dod-6-timeline",
            timeline_ok,
            dod=["DoD-6"],
            run_ids=[run_id, compact_id],
            stages=names,
            unattributed_ms=unattributed,
            duration_ms=duration,
            compact_stage_lines=compact_names,
            compact_unattrib=compact_unattrib,
        ),
        case(
            "dod-6-evidence",
            evidence_ok and mutated.get("mutated_input") is True,
            dod=["DoD-6"],
            run_ids=[run_id, mutate_id],
            dirty_before=_dirty_paths(before),
            dirty_after=_dirty_paths(after),
            toolchain=toolchain.get("output"),
            sample_count=len(samples),
            mutated_input_when_mutating=mutated.get("mutated_input"),
        ),
        case(
            "dod-6-path-independence",
            bool(fp_a) and fp_a == fp_b,
            dod=["DoD-6"],
            identical=fp_a == fp_b,
        ),
        case(
            "dod-6-incomplete-evidence",
            incomplete_ok,
            dod=["DoD-6"],
            run_ids=[probe_id],
            missing=missing,
            mutated_input=probe_run.get("mutated_input"),
        ),
    ]


def typical_cohorts(h: Harness) -> dict[str, Any]:
    catalog = standard_catalog()
    project = h.make_project("typical-project", {"quick": catalog["quick"]})
    env = h.world("typical")
    ids = [
        run_id_from(h.run(["tool", "run", "quick"], env=env, cwd=project).stderr)
        for _ in range(3)
    ]

    def quick() -> dict[str, Any]:
        listed = json.loads(h.run(["tool", "list", "-j"], env=env, cwd=project).stdout)
        return next(t for t in listed["tools"] if t["name"] == "quick")

    baseline = quick()
    with_args = h.run(["tool", "run", "quick", "--", "--extra"], env=env, cwd=project)
    adhoc = h.run(
        ["tool", "run", "--", sys.executable, "-c", "print('q')"], env=env, cwd=project
    )
    after_args = quick()
    changed = json.loads((project / "sase" / "sase.yml").read_text(encoding="utf-8"))
    changed["tools"]["quick"]["argv"] = [sys.executable, "-c", "print('q2')"]
    (project / "sase" / "sase.yml").write_text(json.dumps(changed), encoding="utf-8")
    after_change = quick()
    ok = (
        baseline.get("typical_sample_count") == 3
        and type(baseline.get("typical_duration_ms")) is int
        and baseline.get("typical_status_breakdown") == {"succeeded": 3}
        and with_args.returncode == 0
        and adhoc.returncode == 0
        and after_args.get("typical_sample_count") == 3
        and after_args["last"]["display_argv"][-1] == "--extra"
        and after_change.get("typical_sample_count") in (0, None)
        and after_change.get("typical_duration_ms") is None
        and after_change.get("digest") != baseline.get("digest")
    )
    return case(
        "dod-6-typical",
        ok,
        dod=["DoD-6"],
        run_ids=ids,
        samples=baseline.get("typical_sample_count"),
        typical_ms=baseline.get("typical_duration_ms"),
        breakdown=baseline.get("typical_status_breakdown"),
        samples_after_extra_args=after_args.get("typical_sample_count"),
        samples_after_definition_change=after_change.get("typical_sample_count"),
    )


def samples(h: Harness) -> dict[str, Any]:
    env = h.world("samples")
    proc = h.run(["tool", "run", "--", "sleep", "21"], env=env)
    run_id = run_id_from(proc.stderr)
    shown = h.show(run_id, env=env)
    rows = shown.get("samples") or []
    elapsed = [row.get("elapsed_ms") for row in rows]
    pressure = Path("/proc/pressure/cpu").exists()
    psi_ok = all(
        not (
            row.get("psi_cpu_some") == 0
            and "unavailable" in " ".join(row.get("availability") or ())
        )
        and (row.get("psi_cpu_some") is not None or not pressure)
        for row in rows
    )
    numeric = [value for value in elapsed if type(value) is int]
    ok = (
        proc.returncode == 0
        and len(numeric) == len(elapsed) >= 3
        and numeric[0] < 2000
        and any(8000 <= value <= 12500 for value in numeric)
        and numeric[-1] >= 20000
        and psi_ok
    )
    h.note(run_id, "21-second child proving initial, periodic and final samples")
    return case(
        "dod-6-samples",
        ok,
        dod=["DoD-6"],
        run_ids=[run_id],
        elapsed_ms=elapsed,
        psi_available=pressure,
        first_availability=rows[0].get("availability") if rows else None,
    )


def agent_output(h: Harness) -> list[dict[str, Any]]:
    project = h.project()
    env = h.world("agent-output")
    failing = str(project / "failing.txt")
    proc = h.run(
        ["tool", "run", "-q", "-T", "5", "test", "--", failing], env=env, cwd=project
    )
    run_id = run_id_from(proc.stderr)
    tail = [
        line
        for line in proc.stderr.splitlines()
        if re.match(r"^(case \d+|FAIL: boom)$", line)
    ]
    replay = h.run(["tool", "show", run_id, "-l"], env=env, cwd=project)
    expected_full = (project / "failing.txt").read_text(encoding="utf-8")
    compact_ok = (
        proc.returncode == 1
        and proc.stdout == ""
        and "failed/1" in proc.stderr
        and tail == ["case 27", "case 28", "case 29", "case 30", "FAIL: boom"]
        and f"sase tool show {run_id} -l" in proc.stderr
        and replay.returncode == 0
        and replay.stdout == expected_full
    )
    h.note(run_id, "agent-style compact failure with five retained lines")

    agent_env = dict(env, SASE_AGENT_NAME="agent-fixture")
    default_agent = h.run(
        ["tool", "run", "test", "--", failing], env=agent_env, cwd=project
    )
    verbose_agent = h.run(
        ["tool", "run", "-v", "test", "--", failing], env=agent_env, cwd=project
    )
    human = h.run(["tool", "run", "test", "--", failing], env=env, cwd=project)
    modes_ok = (
        default_agent.returncode == 1
        and default_agent.stdout == ""
        and "failed/1" in default_agent.stderr
        and verbose_agent.returncode == 1
        and verbose_agent.stdout == expected_full
        and human.returncode == 1
        and human.stdout == expected_full
    )

    # No retained-output sink: degrade to passthrough with one warning.
    nosink = h.world("no-sink")
    tools_root = Path(nosink["SASE_HOME"]) / "tools"
    tools_root.mkdir(mode=0o700)
    (tools_root / "logs").write_text("not-a-directory", encoding="utf-8")
    degraded = h.run(
        ["tool", "run", "-q", "--", "sh", "-c", "printf hi; exit 2"],
        env=nosink,
        cwd=project,
    )
    sink_ok = (
        degraded.returncode == 2
        and degraded.stdout == "hi"
        and degraded.stderr.count("retained-output sink unavailable") == 1
    )

    # Argument validation fails before anything executes.
    marker = h.tmp / "validation-marker"
    both = h.run(
        ["tool", "run", "-q", "-v", "--", "sh", "-c", f"printf x >> {marker}"],
        env=env,
        cwd=project,
    )
    negative = h.run(
        ["tool", "run", "-T", "-1", "--", "sh", "-c", f"printf x >> {marker}"],
        env=env,
        cwd=project,
    )
    bad_limit = h.run(["tool", "runs", "-n", "0"], env=env, cwd=project)
    bad_state = h.run(["tool", "runs", "-s", "bogus"], env=env, cwd=project)
    missing_run = h.run(["tool", "show", "does-not-exist"], env=env, cwd=project)
    validation_ok = (
        both.returncode == 2
        and negative.returncode == 2
        and bad_limit.returncode == 2
        and bad_state.returncode == 2
        and missing_run.returncode == 2
        and not marker.exists()
    )

    # An enclosing owner controls presentation: -q conflicts, -v and agent runs pass through.
    owned = dict(agent_env, SASE_MONITOR_ID="mon-fixture")
    quiet_owned = h.run(
        ["tool", "run", "-q", "--", "printf", "x"], env=owned, cwd=project
    )
    verbose_owned = h.run(
        ["tool", "run", "-v", "--", "printf", "out"], env=owned, cwd=project
    )
    agent_owned = h.run(["tool", "run", "--", "printf", "out"], env=owned, cwd=project)
    owner_ok = (
        quiet_owned.returncode == 2
        and "controls presentation" in quiet_owned.stderr
        and verbose_owned.returncode == 0
        and verbose_owned.stdout == "out"
        and agent_owned.returncode == 0
        and agent_owned.stdout == "out"
    )
    return [
        case(
            "dod-7-agent-output",
            compact_ok,
            dod=["DoD-7"],
            run_ids=[run_id],
            exit=proc.returncode,
            stdout=proc.stdout,
            retained_failure_lines=tail,
            show_pointer=f"sase tool show {run_id} -l" in proc.stderr,
            replay_matches_full_output=replay.stdout == expected_full,
        ),
        case(
            "dod-7-modes",
            modes_ok and sink_ok and validation_ok,
            dod=["DoD-7"],
            agent_default_compact=default_agent.stdout == "",
            verbose_streams=verbose_agent.stdout == expected_full,
            human_streams=human.stdout == expected_full,
            no_sink_passthrough=sink_ok,
            usage_errors_exit_2=validation_ok,
        ),
        case(
            "dod-7-owner-precedence",
            owner_ok,
            dod=["DoD-7", "DoD-8"],
            quiet_conflict_exit=quiet_owned.returncode,
            verbose_owned_stdout=verbose_owned.stdout,
            agent_owned_stdout=agent_owned.stdout,
        ),
    ]


def truncation(h: Harness) -> dict[str, Any]:
    env = h.world("truncation", user_config="tool_runs:\n  run_log_max_bytes: 4096\n")
    project = h.project()
    body = "import sys\nfor i in range(1, 3001):\n    print(f'line {i}')\nsys.exit(1)\n"
    script = h.tmp / "flood.py"
    script.write_text(body, encoding="utf-8")
    compact = h.run(
        ["tool", "run", "-q", "-T", "5", "--", sys.executable, str(script)],
        env=env,
        cwd=project,
    )
    run_id = run_id_from(compact.stderr)
    replay = h.run(["tool", "show", run_id, "-l"], env=env, cwd=project)
    shown = h.show(run_id, env=env)
    streamed = h.run(
        ["tool", "run", "-v", "--", sys.executable, str(script)], env=env, cwd=project
    )
    tail = [
        line for line in compact.stderr.splitlines() if re.match(r"^line \d+$", line)
    ]
    ok = (
        compact.returncode == 1
        and tail == [f"line {i}" for i in range(2996, 3001)]
        and "retained output truncated" in compact.stderr
        and 0 < len(replay.stdout) <= 4096
        and replay.stdout.startswith("line 1\nline 2\n")
        and "retained output truncated" in replay.stderr
        and "run_log_max_bytes=4096" in replay.stderr
        and bool(shown.get("output_truncation"))
        and streamed.returncode == 1
        and streamed.stdout.endswith("line 3000\n")
        and streamed.stdout.count("\n") == 3000
        and "dropped=" in streamed.stderr
    )
    h.note(run_id, "run_log_max_bytes overflow reported explicitly")
    return case(
        "dod-7-truncation",
        ok,
        dod=["DoD-7"],
        run_ids=[run_id],
        retained_bytes=len(replay.stdout),
        replay_notice=replay.stderr.strip(),
        compact_tail=tail,
        streamed_lines=streamed.stdout.count("\n"),
    )


def concurrency(h: Harness) -> dict[str, Any]:
    project = _evidence_project(h, "concurrent-project")
    env = h.world("concurrent")
    results: list[subprocess.CompletedProcess[str]] = []
    guard = threading.Lock()

    def worker() -> None:
        proc = h.run(["tool", "run", "check"], env=env, cwd=project)
        with guard:
            results.append(proc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ids = [run_id_from(item.stderr) for item in results]
    shows = [h.show(run_id, env=env) for run_id in ids]
    listed = {item["run_id"]: item for item in h.runs(env=env)}
    stage_ids = [
        stage["stage_id"] for shown in shows for stage in shown.get("stages") or ()
    ]
    ok = (
        len(results) == 4
        and all(item.returncode == 3 for item in results)
        and len(set(ids)) == 4
        and all(
            [stage["description"] for stage in shown.get("stages") or ()]
            == ["alpha", "alpha", "beta"]
            for shown in shows
        )
        and len(stage_ids) == len(set(stage_ids)) == 12
        and all(
            all(stage["run_id"] == run_id for stage in shown.get("stages") or ())
            and shown["schema_version"] == 1
            and (shown.get("run") or {}).get("run_id") == run_id
            and listed[run_id]["state"] == shown["run"]["state"]
            and listed[run_id]["definition_digest"] == shown["run"]["definition_digest"]
            for run_id, shown in zip(ids, shows, strict=True)
        )
        and len(
            {
                (shown.get("run") or {}).get("logs", {}).get("events_path")
                for shown in shows
            }
        )
        == 4
    )
    for run_id in ids:
        h.note(run_id, "concurrent staged run with an independent event file")
    return case(
        "dod-10-concurrent",
        ok,
        dod=["DoD-10"],
        run_ids=ids,
        exits=[item.returncode for item in results],
        distinct_stage_ids=len(set(stage_ids)),
    )


def torn_replay(h: Harness) -> dict[str, Any]:
    env = h.world("torn")
    events = h.tmp / "torn-events.jsonl"
    events.write_text("", encoding="utf-8")
    dead = subprocess.Popen(["true"])
    dead.wait()
    seeded = h.helper(
        "seed-torn",
        {"events_path": str(events), "dead_pid": dead.pid, "project": "torn-fixture"},
        env=env,
    )
    run_id = seeded["run_id"]

    def record(kind: str, event_id: str, stage_id: str, **extra: Any) -> str:
        base = {
            "schema_version": 1,
            "kind": kind,
            "run_id": extra.pop("run_id", run_id),
            "stage_id": stage_id,
            "event_id": event_id,
            "description": stage_id,
            "started_ts": 1000,
        }
        if kind == "finished":
            base.update(finished_ts=1200, elapsed_ms=200, exit_code=0, output_bytes=0)
        return json.dumps({**base, **extra})

    lines = [
        record("started", "ev-a-start", "stage-a"),
        record("finished", "ev-a-finish", "stage-a"),
        record("finished", "ev-a-finish", "stage-a"),  # replayed
        "not-json",
        record("finished", "ev-x-finish", "stage-x", run_id="some-other-run"),
        record("started", "ev-b-start", "stage-b"),  # never finishes
    ]
    events.write_text(
        "\n".join(lines) + '\n{"schema_version":1,"kind":"finished"', encoding="utf-8"
    )
    first = h.runs(env=env)
    shown = h.show(run_id, env=env)
    second_stages = h.show(run_id, env=env).get("stages") or []
    row = next((r for r in first if r["run_id"] == run_id), {})
    stages = {stage["stage_id"]: stage for stage in shown.get("stages") or ()}
    ok = (
        row.get("state") == "lost"
        and (shown.get("run") or {}).get("exit_code") is None
        and (shown.get("run") or {}).get("duration_ms") is None
        and sorted(stages) == ["stage-a", "stage-b"]
        and stages["stage-a"].get("incomplete") is False
        and stages["stage-a"].get("elapsed_ms") == 200
        and stages["stage-b"].get("incomplete") is True
        and stages["stage-b"].get("elapsed_ms") is None
        and stages["stage-b"].get("exit_code") is None
        and len(second_stages) == 2
    )
    h.note(run_id, "torn, replayed and cross-run events recovered without fabrication")
    return case(
        "dod-10-torn-replay",
        ok,
        dod=["DoD-10"],
        run_ids=[run_id],
        state=row.get("state"),
        stages=sorted(stages),
        start_only_stage_incomplete=(stages.get("stage-b") or {}).get("incomplete"),
    )

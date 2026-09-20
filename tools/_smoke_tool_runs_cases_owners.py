"""Harness cases: enclosing owners, disk retention, and cold-start overhead."""

from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from _smoke_tool_runs_lib import (
    Harness,
    case,
    not_run,
    run_id_from,
    wait_for,
)


OVERHEAD_PAIRS = 7
OVERHEAD_TARGET_SECONDS = 0.5
FIXTURE_AGENT = "fixture-agent"


def enclosing_owner(h: Harness) -> dict[str, Any]:
    """An inherited monitor id is recorded as the owner and output passes through."""

    env = h.world("enclosing")
    owned = dict(env, SASE_MONITOR_ID="mon-fixture")
    proc = h.run(["tool", "run", "--", "printf", "out"], env=owned)
    run_id = run_id_from(proc.stderr)
    run = h.show(run_id, env=owned).get("run") or {}
    logs = run.get("logs") or {}
    both = h.run(
        ["tool", "run", "--", "printf", "x"],
        env=dict(owned, SASE_PROC_ID="proc-fixture"),
    )
    both_run = h.show(run_id_from(both.stderr), env=owned).get("run") or {}
    # An agent launched by a monitored command inherits that monitor's id after it
    # settled; a terminal owner captures nothing and must not own the output.
    settled_dir = h.tmp / "settled-monitor"
    settled_dir.mkdir()
    (settled_dir / "done.json").write_text("{}", encoding="utf-8")
    stale = dict(
        env,
        SASE_MONITOR_ID="mon-settled",
        SASE_MONITOR_ARTIFACTS_DIR=str(settled_dir),
        SASE_AGENT_NAME="agent-fixture",
    )
    stale_proc = h.run(
        ["tool", "run", "--", "sh", "-c", "printf out; exit 2"], env=stale
    )
    stale_run = h.show(run_id_from(stale_proc.stderr), env=stale).get("run") or {}
    stale_logs = stale_run.get("logs") or {}
    h.note(
        run_id, "inherited monitor id recorded as owner", owner="monitor:mon-fixture"
    )
    ok = (
        proc.returncode == 0
        and proc.stdout == "out"
        and run.get("owner_kind") == "monitor"
        and run.get("owner_id") == "mon-fixture"
        and not logs.get("stdout_path")
        and not logs.get("stderr_path")
        and bool(logs.get("events_path"))
        and both_run.get("owner_kind") == "monitor"
        and stale_proc.returncode == 2
        and stale_proc.stdout == ""
        and "failed/2" in stale_proc.stderr
        and not stale_run.get("owner_kind")
        and bool(stale_logs.get("stdout_path"))
    )
    return case(
        "dod-8-enclosing-owner",
        ok,
        dod=["DoD-8"],
        run_ids=[run_id],
        owner_kind=run.get("owner_kind"),
        owner_id=run.get("owner_id"),
        has_stdout_log=bool(logs.get("stdout_path")),
        monitor_beats_proc=both_run.get("owner_kind") == "monitor",
        settled_monitor_ignored=not stale_run.get("owner_kind"),
        settled_monitor_agent_output_compact=stale_proc.stdout == "",
    )


def nested_runs(h: Harness) -> dict[str, Any]:
    env = h.world("nested")
    outer = h.run(
        ["tool", "run", "--", h.sase, "tool", "run", "--", "printf", "inner-out"],
        env=env,
    )
    ids = [
        line.split()[-1]
        for line in outer.stderr.splitlines()
        if line.startswith("sase tool run ")
    ]
    outer_id, inner_id = (ids + ["", ""])[:2]
    outer_run = h.show(outer_id, env=env).get("run") or {}
    inner_run = h.show(inner_id, env=env).get("run") or {}
    inner_logs = inner_run.get("logs") or {}
    outer_logs = outer_run.get("logs") or {}
    replay = h.run(["tool", "show", outer_id, "-l"], env=env)
    inner_replay = h.run(["tool", "show", inner_id, "-l"], env=env)
    h.note(outer_id, "outer foreground run owning the output")
    h.note(inner_id, "nested run linked to its parent", owner=f"tool_run:{outer_id}")
    ok = (
        len(ids) == 2
        and outer.returncode == 0
        and outer.stdout == "inner-out"
        and inner_run.get("parent_run_id") == outer_id
        and not outer_run.get("parent_run_id")
        and not inner_logs.get("stdout_path")
        and not inner_logs.get("stderr_path")
        and bool(outer_logs.get("stdout_path"))
        and inner_logs.get("events_path") != outer_logs.get("events_path")
        and bool(inner_logs.get("events_path"))
        and "inner-out" in replay.stdout
        and outer_id in inner_replay.stderr
    )
    return case(
        "dod-8-nested",
        ok,
        dod=["DoD-8"],
        run_ids=[outer_id, inner_id],
        inner_parent_matches_outer=inner_run.get("parent_run_id") == outer_id,
        separate_events=inner_logs.get("events_path") != outer_logs.get("events_path"),
        inner_has_output_logs=bool(inner_logs.get("stdout_path")),
    )


def _owner_world(h: Harness, name: str) -> tuple[dict[str, str], Path]:
    """A world whose fixture project and agent exist, so a real monitor can start."""

    env = h.world(name)
    project = h.project()
    project_dir = Path(env["SASE_HOME"]) / "projects" / project.name
    stamp = "20260920120000"
    artifacts = project_dir / "artifacts" / "ace-run" / stamp[:6] / stamp[6:8] / stamp
    artifacts.mkdir(parents=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": FIXTURE_AGENT, "model": "test"}), encoding="utf-8"
    )
    (project_dir / f"{project.name}.gp").write_text(
        f"WORKSPACE_DIR: {project}\nNAME: Fixture\nDESCRIPTION:\n  x\n"
        "PARENT: None\nPR: None\nSTATUS: Ready\n",
        encoding="utf-8",
    )
    return env, project


def _find_key(value: object, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for item in value.values():
            found = _find_key(item, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def _monitor_record(
    h: Harness, env: dict[str, str], monitor_id: str, project: Path
) -> dict[str, Any]:
    proc = h.run(["monitor", "list", "--all", "--format", "json"], env=env, cwd=project)
    try:
        monitors = json.loads(proc.stdout).get("monitors") or []
    except json.JSONDecodeError:
        return {}
    return next((m for m in monitors if m.get("monitor_id") == monitor_id), {})


def live_monitor(h: Harness) -> dict[str, Any]:
    if not h.live:
        return not_run(
            "dod-8-live-monitor",
            "live cases were not requested; pass --live",
            dod=["DoD-8"],
        )
    env, project = _owner_world(h, "live-monitor")
    started = h.run(
        [
            "monitor",
            "start",
            "-a",
            FIXTURE_AGENT,
            "-r",
            "harness owner fixture",
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
            "dod-8-live-monitor",
            False,
            dod=["DoD-8"],
            error=(started.stderr or started.stdout)[-400:],
        )
    monitor_id = str(_find_key(json.loads(started.stdout), "monitor_id") or "")
    settled = wait_for(
        lambda: bool(_monitor_record(h, env, monitor_id, project).get("is_terminal")),
        timeout=90.0,
        step=0.5,
    )
    record = _monitor_record(h, env, monitor_id, project)
    if not settled:
        h.run(["monitor", "stop", monitor_id], env=env, cwd=project)
    rows = [
        r
        for r in h.runs(env=env)
        if r.get("owner_kind") == "monitor" and r.get("owner_id") == monitor_id
    ]
    run = rows[0] if len(rows) == 1 else {}
    run_id = str(run.get("run_id") or "")
    shown = h.show(run_id, env=env) if run_id else {}
    logs = (shown.get("run") or {}).get("logs") or {}
    log_dir = Path(str(logs.get("events_path") or "")).parent
    files = sorted(p.name for p in log_dir.iterdir()) if log_dir.is_dir() else []
    replay = (
        h.run(["tool", "show", run_id, "-l"], env=env, cwd=project) if run_id else None
    )
    stages = [s.get("description") for s in shown.get("stages") or ()]
    h.note(
        run_id,
        "check fixture run under a real monitor",
        owner=f"monitor:{monitor_id}",
        kind="live",
    )
    ok = (
        settled
        and len(rows) == 1
        and record.get("exit_code") == 3
        and run.get("state") == "failed"
        and run.get("exit_code") == 3
        and files == ["events.jsonl"]
        and not logs.get("stdout_path")
        and stages == ["alpha", "alpha", "beta"]
        and len(shown.get("samples") or ()) >= 2
        and replay is not None
        and "alpha" in replay.stdout
    )
    return case(
        "dod-8-live-monitor",
        ok,
        dod=["DoD-8"],
        run_ids=[run_id],
        monitor_id=monitor_id,
        monitor_exit_code=record.get("exit_code"),
        owner_kind=run.get("owner_kind"),
        run_dir_files=files,
        stages=stages,
        replay_from_monitor_log=bool(replay and "alpha" in replay.stdout),
    )


def live_proc(h: Harness) -> dict[str, Any]:
    if not h.live:
        return not_run(
            "dod-8-live-proc",
            "live cases were not requested; pass --live",
            dod=["DoD-8"],
        )
    env, project = _owner_world(h, "live-proc")
    proc = h.run(
        [
            "proc",
            "run",
            "-w",
            "-s",
            "none",
            "--",
            h.sase,
            "tool",
            "run",
            "--",
            "printf",
            "out-proc",
        ],
        env=env,
        cwd=project,
    )
    rows = [r for r in h.runs(env=env) if r.get("owner_kind") == "proc"]
    run = rows[0] if len(rows) == 1 else {}
    run_id = str(run.get("run_id") or "")
    logs = run.get("logs") or {}
    replay = (
        h.run(["tool", "show", run_id, "-l"], env=env, cwd=project) if run_id else None
    )
    h.note(
        run_id,
        "ad-hoc run under a real proc",
        owner=f"proc:{run.get('owner_id')}",
        kind="live",
    )
    ok = (
        proc.returncode == 0
        and "out-proc" in proc.stdout
        and len(rows) == 1
        and bool(run.get("owner_id"))
        and not logs.get("stdout_path")
        and replay is not None
        and "out-proc" in replay.stdout
    )
    return case(
        "dod-8-live-proc",
        ok,
        dod=["DoD-8"],
        run_ids=[run_id],
        owner_kind=run.get("owner_kind"),
        owner_id=run.get("owner_id"),
        has_stdout_log=bool(logs.get("stdout_path")),
    )


def _tree(root: Path) -> dict[str, int]:
    return {
        str(p.relative_to(root)): p.stat().st_size
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }


def disk_retention(h: Harness) -> list[dict[str, Any]]:
    env = h.world("disk")
    outside = h.tmp / "disk-outside"
    seeded = h.helper("seed-retention", {"outside_dir": str(outside)}, env=env)
    logs_root = Path(env["SASE_HOME"]) / "tools" / "logs"
    before_tree = _tree(logs_root)

    listed = json.loads(h.run(["disk", "list", "-j"], env=env, cwd=h.tmp).stdout)
    row = next(
        (r for r in listed.get("rows") or () if r.get("owner") == "tool_run_retention"),
        {},
    )
    preview_proc = h.run(["disk", "reap", "-j"], env=env, cwd=h.tmp)
    preview = json.loads(preview_proc.stdout)
    step = next(
        (
            s
            for s in preview.get("steps") or ()
            if s.get("owner") == "tool_run_retention"
        ),
        {},
    )
    untouched = _tree(logs_root) == before_tree
    h.snapshots["disk"] = {
        "row": {
            key: row.get(key)
            for key in ("owner", "status", "coverage", "horizon", "reclaim", "name")
        },
        "preview_step": {
            "owner": step.get("owner"),
            "mode": step.get("mode"),
            "summary": step.get("summary"),
            "changed": step.get("changed"),
        },
    }
    list_ok = (
        row.get("status") == "owned"
        and str(row.get("path", "")).startswith(env["SASE_HOME"])
        and step.get("mode") == "dry_run"
        and (step.get("details") or {}).get("summary_rows") == 1
        and untouched
        and preview.get("apply") is False
    )

    result = h.helper("retention", {"apply": True}, env=env)
    after_tree = result["after_tree"]
    removed = {k: v for k, v in before_tree.items() if k not in after_tree}
    expected_removed = {
        "seed-old-summary/stdout.log",
        "seed-old-summary/stderr.log",
        "seed-old-summary/events.jsonl",
        "seed-old-detail/stdout.log",
        "seed-old-detail/events.jsonl",
        "seed-old-logs/stdout.log",
        "seed-old-logs/events.jsonl",
        "seed-symlink/events.jsonl",
        "seed-monitor-owned/events.jsonl",
    }
    survivors = {
        "seed-recent/stdout.log",
        "seed-recent/events.jsonl",
        "seed-unsettled/stdout.log",
        "seed-unsettled/events.jsonl",
    }
    stats_after = result["after_stats"]
    remaining = {
        r["run_id"]: r["state"] for r in h.helper("list-runs", env=env)["runs"]
    }
    escape = Path(seeded["outside"]["escape_target"])
    owner_log = Path(seeded["outside"]["owner_log"])
    link = logs_root / "seed-symlink" / "stdout.log"
    pruned = h.show("seed-old-detail", env=env)
    retention_ok = (
        set(removed) == expected_removed
        and survivors <= set(after_tree)
        and result["reclaimed_bytes"] == sum(removed.values())
        and result["byte_accounting_complete"] is True
        and result["exit_code"] is None
        and escape.exists()
        and escape.stat().st_size == 321
        and owner_log.exists()
        and owner_log.stat().st_size == 654
        and link.is_symlink()
        and "seed-old-summary" not in remaining
        and remaining.get("seed-old-detail") == "succeeded"
        and pruned.get("stages") == []
        and (pruned.get("detail_retention") or {}).get("detail_may_be_pruned") is True
        and remaining.get("seed-unsettled") == "running"
        and stats_after["stage_count"] == result["before_stats"]["stage_count"] - 1
        and stats_after["db_size_bytes"] >= result["before_stats"]["db_size_bytes"]
    )

    missing_env = h.world("disk-missing")
    missing = h.helper("retention", {"apply": True}, env=missing_env)
    missing_ok = (
        missing["mode"] == "apply"
        and missing["store_exists"] is False
        and missing["tools_dir_exists"] is False
        and missing["reclaimed_bytes"] == 0
        and missing["exit_code"] is None
    )
    return [
        case(
            "dod-9-disk-list",
            list_ok,
            dod=["DoD-9"],
            owner=row.get("owner"),
            horizon=row.get("horizon"),
            preview_mode=step.get("mode"),
            preview_left_files_untouched=untouched,
        ),
        case(
            "dod-9-retention",
            retention_ok and missing_ok,
            dod=["DoD-9"],
            removed=sorted(removed),
            preview_summary=step.get("summary"),
            applied_summary=result["summary"],
            reclaimed_bytes=result["reclaimed_bytes"],
            files_before_bytes=sum(before_tree.values()),
            files_after_bytes=sum(after_tree.values()),
            db_bytes_before=result["before_stats"]["db_size_bytes"],
            db_bytes_after=stats_after["db_size_bytes"],
            lifecycle_survives_detail_pruning=remaining.get("seed-old-detail"),
            pruned_detail_identified=(pruned.get("detail_retention") or {}).get(
                "detail_may_be_pruned"
            ),
            unsettled_survived="seed-unsettled/stdout.log" in after_tree,
            symlink_target_survived=escape.exists(),
            owner_log_survived=owner_log.exists(),
            missing_store_created_anything=missing["tools_dir_exists"],
        ),
    ]


def aggregate_cap(h: Harness) -> dict[str, Any]:
    """The aggregate ``log_max_bytes`` target deletes oldest settled logs first."""

    outcomes: dict[str, Any] = {}
    ok = True
    for name, cap, expect_removed, expect_over in (
        ("fits", 2500, {"seed-cap-oldest", "seed-cap-middle"}, 0),
        (
            "protected-over-target",
            1000,
            {"seed-cap-oldest", "seed-cap-middle", "seed-cap-newest"},
            100,
        ),
    ):
        env = h.world(
            f"cap-{name}",
            user_config=f"tool_runs:\n  log_max_bytes: {cap}\n  run_log_max_bytes: 1000\n",
        )
        h.helper("seed-cap", env=env)
        result = h.helper("retention", {"apply": True}, env=env)
        before = set(result["before_tree"])
        after = set(result["after_tree"])
        gone = {p.split("/")[0] for p in before - after}
        details = result["details"]
        step_ok = (
            gone == expect_removed
            and "seed-cap-live/stdout.log" in after
            and "seed-cap-live/events.jsonl" in after
            and details.get("protected_bytes") == 1100
            and details.get("over_target_bytes") == expect_over
            and result["reclaimed_bytes"]
            == sum(result["before_tree"][p] for p in before - after)
        )
        outcomes[name] = {
            "removed": sorted(gone),
            "protected_bytes": details.get("protected_bytes"),
            "over_target_bytes": details.get("over_target_bytes"),
            "ok": step_ok,
        }
        ok = ok and step_ok
    return case("dod-9-aggregate-cap", ok, dod=["DoD-9"], **outcomes)


def overhead(h: Harness) -> dict[str, Any]:
    if not h.live:
        return not_run(
            "dod-13-overhead",
            "host-dependent timing is a live measurement; pass --live",
            dod=["DoD-13"],
        )
    env = h.world("overhead")
    project = h.project()

    def timed(args: list[str]) -> float:
        started = time.monotonic()
        h.run(args, env=env, cwd=project)
        return time.monotonic() - started

    baseline: list[float] = []
    wrapper: list[float] = []
    for _ in range(OVERHEAD_PAIRS):
        baseline.append(timed(["proc", "list"]))
        wrapper.append(timed(["tool", "run", "--", "true"]))
    delta = statistics.median(wrapper) - statistics.median(baseline)
    return case(
        "dod-13-overhead",
        delta <= OVERHEAD_TARGET_SECONDS,
        dod=["DoD-13"],
        loadavg_1=round(os.getloadavg()[0], 2),
        cpu_count=os.cpu_count(),
        baseline_samples=[round(x, 3) for x in baseline],
        wrapper_samples=[round(x, 3) for x in wrapper],
        median_delta_seconds=round(delta, 3),
        target_seconds=OVERHEAD_TARGET_SECONDS,
    )

"""Attributed TUI startup capture for sase-132 and later phases.

Reproduces the baseline-phase recipe in ``docs/perf_runbook.md``:

- standalone ``bench_agent_load_tiering.py --sase-home`` labeled quiet/busy
- live traced ``sase tui`` startups (tmux) plus an optional ``--profile`` run
- ``python -X importtime`` of the TUI app module

Store outputs under ``~/.sase/perf/`` with the epic prefix. Example::

    .venv/bin/python tests/perf/capture_tui_startup.py all --output-dir ~/.sase/perf
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"ERROR: {exc}"


def core_revision() -> str:
    path = _REPO_ROOT / "sase-core-revision.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return f"ERROR: {exc}"


def pgrep_count(pattern: str) -> int:
    result = subprocess.run(
        ["pgrep", "-fc", pattern],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        return -1
    try:
        return int((result.stdout or "0").strip() or "0")
    except ValueError:
        return -1


def host_snapshot() -> dict[str, Any]:
    loadavg = list(os.getloadavg()) if hasattr(os, "getloadavg") else None
    runners = pgrep_count("run_agent_runner.py")
    pytest_n = pgrep_count("pytest")
    load1 = float(loadavg[0]) if loadavg else 0.0
    if load1 < 4.0 and runners == 0:
        state = "quiet"
    else:
        state = "busy"
    return {
        "utc": utc_now(),
        "host": os.uname().nodename,
        "loadavg": loadavg,
        "cpu_count": os.cpu_count(),
        "agent_runner_processes": runners,
        "pytest_processes": pytest_n,
        "host_state": state,
        "git_sha": git_sha(),
        "sase_core_revision": core_revision(),
        "python": sys.executable,
        "workspace": str(_REPO_ROOT),
    }


def _run_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _jsonl_len(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def cmd_bench(args: argparse.Namespace) -> int:
    host = host_snapshot()
    run_id = _run_id(f"sase-132.1_agent_load_tiering_{host['host_state']}")
    outdir = Path(args.output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    output = outdir / f"{run_id}.json"
    metadata_path = outdir / f"{run_id}.meta.json"
    log_path = outdir / f"{run_id}.log"
    cmd = [
        sys.executable,
        str(_REPO_ROOT / "tests/perf/bench_agent_load_tiering.py"),
        "--sase-home",
        str(Path(args.sase_home).expanduser()),
        "--output",
        str(output),
    ]
    _write_json(metadata_path, {"command": cmd, "host": host, "started_utc": utc_now()})
    print(json.dumps({"bench_start": str(output), "host_state": host["host_state"]}))
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    ended = host_snapshot()
    _write_json(
        metadata_path,
        {
            "command": cmd,
            "host_start": host,
            "host_end": ended,
            "returncode": result.returncode,
            "output": str(output),
            "log": str(log_path),
            "ended_utc": utc_now(),
        },
    )
    print(
        json.dumps(
            {
                "bench_done": str(output),
                "returncode": result.returncode,
                "host_state": host["host_state"],
            }
        )
    )
    return result.returncode


def _pane_alive(target: str) -> bool:
    return (
        subprocess.run(
            ["tmux", "display-message", "-p", "-t", target, "#{pane_pid}"],
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _send_key(target: str, key: str) -> None:
    subprocess.run(["tmux", "send-keys", "-t", target, key], check=False)


def _wait_startup_record(
    *,
    startup_path: Path,
    baseline_count: int,
    pid: int,
    timeout_s: float,
) -> dict[str, Any] | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = _read_jsonl(startup_path)
        new_rows = [
            row for row in rows[baseline_count:] if row.get("event") == "tui_startup"
        ]
        for row in new_rows:
            if row.get("pid") == pid:
                return row
        if new_rows:
            return new_rows[-1]
        time.sleep(0.25)  # sase-test-wait: poll tui_startup.jsonl for new record
    return None


def cmd_live(args: argparse.Namespace) -> int:
    from sase.logs import tui_startup_jsonl_path
    from sase.main.ace_tmux import create_agent_tmux_window, release_tmux_window_claim

    host = host_snapshot()
    run_id = _run_id(f"sase-132.1_live_{host['host_state']}")
    outdir = Path(args.output_dir).expanduser() / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    startup_path = tui_startup_jsonl_path()
    summary: dict[str, Any] = {
        "run_id": run_id,
        "outdir": str(outdir),
        "host": host,
        "runs": [],
    }
    profile_done = False
    rc = 0
    for index in range(int(args.runs)):
        want_profile = (
            bool(args.profile) and not profile_done and index == int(args.runs) - 1
        )
        trace_path = outdir / f"tui_trace_{index + 1}.jsonl"
        profile_path = outdir / "ace_profile.txt" if want_profile else None
        tui_argv = [
            sys.executable,
            "-m",
            "sase",
            "tui",
            "-x",
            "-t",
            "agents",
        ]
        if want_profile and profile_path is not None:
            tui_argv.extend(["--profile", str(profile_path)])
        extra_env = {
            "SASE_TUI_TRACE": "1",
            "SASE_TUI_TRACE_PATH": str(trace_path),
            "SASE_TUI_LOADER_LOG_THRESHOLD_SECONDS": "0.05",
        }
        baseline = _jsonl_len(startup_path)
        cmd = "exec " + shlex.join(tui_argv)
        window = create_agent_tmux_window(cmd, extra_env=extra_env)
        record: dict[str, Any] = {
            "index": index + 1,
            "pane_pid": window.pane_pid,
            "target": window.target,
            "trace": str(trace_path),
            "profile": str(profile_path) if profile_path else None,
            "started_utc": utc_now(),
        }
        try:
            startup_row = _wait_startup_record(
                startup_path=startup_path,
                baseline_count=baseline,
                pid=window.pane_pid,
                timeout_s=float(args.timeout),
            )
            record["startup_record"] = startup_row
            record["startup_found"] = startup_row is not None
            _send_key(window.target, "q")
            wait_s = 45.0 if want_profile else 8.0
            deadline = time.time() + wait_s
            while time.time() < deadline:
                if (
                    want_profile
                    and profile_path is not None
                    and profile_path.exists()
                    and profile_path.stat().st_size > 0
                ):
                    break
                if not _pane_alive(window.target) and not want_profile:
                    break
                if (
                    not _pane_alive(window.target)
                    and want_profile
                    and profile_path is not None
                    and profile_path.exists()
                ):
                    break
                time.sleep(0.25)  # sase-test-wait: poll TUI quit and profile write
            if _pane_alive(window.target):
                subprocess.run(
                    ["tmux", "kill-window", "-t", window.target],
                    check=False,
                )
        finally:
            release_tmux_window_claim(window.screenshot_dir)
        record["ended_utc"] = utc_now()
        record["trace_bytes"] = trace_path.stat().st_size if trace_path.exists() else 0
        if startup_row is None:
            rc = 1
        if want_profile:
            profile_done = True
        summary["runs"].append(record)
        print(
            json.dumps(
                {"live_run": record["index"], "startup_found": record["startup_found"]}
            )
        )
    summary["ended_utc"] = utc_now()
    _write_json(outdir / "summary.json", summary)
    print(json.dumps({"live_summary": str(outdir / "summary.json"), "returncode": rc}))
    return rc


def cmd_importtime(args: argparse.Namespace) -> int:
    host = host_snapshot()
    run_id = _run_id("sase-132.1_importtime")
    outdir = Path(args.output_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    output = outdir / f"{run_id}.txt"
    cmd = [
        sys.executable,
        "-X",
        "importtime",
        "-c",
        "from sase.ace.tui.app import AceApp",
    ]
    result = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output.write_text(result.stderr, encoding="utf-8")
    import_lines = [
        line for line in result.stderr.splitlines() if line.startswith("import time:")
    ]
    meta = {
        "command": cmd,
        "host": host,
        "returncode": result.returncode,
        "output": str(output),
        "import_line_count": len(import_lines),
        "stderr_bytes": len(result.stderr.encode("utf-8")),
        "ended_utc": utc_now(),
    }
    _write_json(outdir / f"{run_id}.meta.json", meta)
    print(
        json.dumps(
            {
                "importtime": str(output),
                "import_line_count": len(import_lines),
                "returncode": result.returncode,
            }
        )
    )
    return result.returncode


def cmd_all(args: argparse.Namespace) -> int:
    rc = 0
    args.profile = True
    for fn in (cmd_importtime, cmd_bench, cmd_live):
        result = fn(args)
        if result:
            rc = result
    return rc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--output-dir",
        default=str(Path.home() / ".sase" / "perf"),
        help="Directory for capture files (default: ~/.sase/perf)",
    )
    common.add_argument(
        "--sase-home",
        default=str(Path.home() / ".sase"),
        help="Archive to bench (default: ~/.sase)",
    )
    common.add_argument("--runs", type=int, default=3, help="Live traced startups")
    common.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for a tui_startup.jsonl record per live run",
    )
    common.add_argument(
        "--profile",
        action="store_true",
        help="Run the last live startup under sase tui --profile",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "bench",
        parents=[common],
        help="Real-archive loader bench labeled quiet/busy",
    )
    sub.add_parser(
        "live",
        parents=[common],
        help="Traced live TUI startups in tmux",
    )
    sub.add_parser(
        "importtime",
        parents=[common],
        help="python -X importtime of AceApp",
    )
    sub.add_parser(
        "all",
        parents=[common],
        help="importtime + bench + live",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "bench":
        return cmd_bench(args)
    if args.command == "live":
        return cmd_live(args)
    if args.command == "importtime":
        return cmd_importtime(args)
    if args.command == "all":
        return cmd_all(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

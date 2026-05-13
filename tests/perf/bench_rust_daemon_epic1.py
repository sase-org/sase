"""Epic 1 daemon-readiness performance baseline harness.

This harness is intentionally inert: it measures current direct CLI startup
costs and mocked local-daemon request framing without starting a daemon or
rerouting production commands.

Run directly:

    python -m tests.perf.bench_rust_daemon_epic1 \
      --runs 5 \
      --output tests/perf/baselines/rust_daemon_epic1_current.json

By default the CLI scenarios run against a temporary HOME/SASE_HOME populated
from ``tests/fixtures/rust_daemon_epic1``. Use ``--real-home`` only when you
explicitly want timings against local developer state.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SOURCES = REPO_ROOT / "tests" / "fixtures" / "rust_daemon_epic1" / "sources"
DEFAULT_TARGETS_MS = {
    "warm_daemon_cli_editor_common_reads": {"low": 5.0, "high": 30.0},
    "ace_shell_first_useful_paint": {"high": 100.0},
    "active_indexed_data_large_histories": {"high": 250.0},
    "event_driven_no_change_refresh": {"target": 0.0},
}


@dataclass(frozen=True)
class _CommandScenario:
    name: str
    argv: tuple[str, ...]
    stdin: str | None = None
    cwd: Path | None = None


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _summarize(values: Iterable[float]) -> dict[str, float]:
    vals = sorted(values)
    if not vals:
        return {"count": 0.0}
    return {
        "count": float(len(vals)),
        "min_ms": vals[0] * 1000.0,
        "p50_ms": statistics.median(vals) * 1000.0,
        "p95_ms": _percentile(vals, 0.95) * 1000.0,
        "max_ms": vals[-1] * 1000.0,
    }


def _time_call(fn: Callable[[], object]) -> float:
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


def _base_env(*, home: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    pythonpath_parts = [str(REPO_ROOT / "src")]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    if home is not None:
        env["HOME"] = str(home)
        env["SASE_HOME"] = str(home / ".sase")
    env.pop("SASE_AGENT_NAME", None)
    env.pop("SASE_AGENT_TIMESTAMP", None)
    env.pop("SASE_ARTIFACTS_DIR", None)
    return env


def _copy_fixture_file(source_rel: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_SOURCES / source_rel, destination)


def _prepare_hermetic_workspace(root: Path) -> tuple[Path, Path]:
    home = root / "home"
    workspace = root / "workspace"
    workspace.mkdir(parents=True)

    project_dir = home / ".sase" / "projects" / "demo"
    _copy_fixture_file("changespec/demo.sase", project_dir / "demo.sase")
    _copy_fixture_file(
        "changespec/demo-archive.sase", project_dir / "demo-archive.sase"
    )
    _copy_fixture_file(
        "notifications/notifications.jsonl",
        home / ".sase" / "notifications" / "notifications.jsonl",
    )
    _copy_fixture_file(
        "history/file_reference_history.json",
        home / ".sase" / "history" / "file_reference_history.json",
    )
    shutil.copytree(FIXTURE_SOURCES / "beads", workspace / "sdd" / "beads")
    return home, workspace


def _sase_entry_command(*args: str) -> tuple[str, ...]:
    return (sys.executable, "-m", "sase.main.entry", *args)


def _command_scenarios(workspace: Path) -> list[_CommandScenario]:
    request = json.dumps({"project": "demo", "limit": 20})
    return [
        _CommandScenario(
            "python_startup",
            (sys.executable, "-c", "pass"),
            cwd=workspace,
        ),
        _CommandScenario(
            "import_sase_entry",
            (sys.executable, "-c", "import sase.main.entry"),
            cwd=workspace,
        ),
        _CommandScenario("sase_help", _sase_entry_command("--help"), cwd=workspace),
        _CommandScenario(
            "changespec_search_plain",
            _sase_entry_command("changespec", "search", "demo", "-f", "plain"),
            cwd=workspace,
        ),
        _CommandScenario(
            "notify_list_json",
            _sase_entry_command("notify", "list", "-j", "--all", "-l", "20"),
            cwd=workspace,
        ),
        _CommandScenario(
            "notify_show_json",
            _sase_entry_command("notify", "show", "-i", "notif-unread", "-f", "json"),
            cwd=workspace,
        ),
        _CommandScenario(
            "bead_list",
            _sase_entry_command("bead", "list"),
            cwd=workspace,
        ),
        _CommandScenario(
            "bead_show",
            _sase_entry_command("bead", "show", "daemon-1"),
            cwd=workspace,
        ),
        _CommandScenario(
            "bead_ready",
            _sase_entry_command("bead", "ready"),
            cwd=workspace,
        ),
        _CommandScenario(
            "editor_xprompt_catalog",
            _sase_entry_command("editor", "helper-bridge", "xprompt-catalog"),
            stdin=request,
            cwd=workspace,
        ),
    ]


def _run_subprocess(
    scenario: _CommandScenario,
    *,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(scenario.argv),
        cwd=scenario.cwd or REPO_ROOT,
        env=env,
        input=scenario.stdin,
        text=True,
        capture_output=True,
        check=True,
        timeout=timeout,
    )


def _display_argv(argv: tuple[str, ...]) -> list[str]:
    if argv and argv[0] == sys.executable:
        return ["python", *argv[1:]]
    return list(argv)


def _bench_command_startup(
    *,
    runs: int,
    env: dict[str, str],
    workspace: Path,
    timeout: float,
) -> dict[str, Any]:
    scenarios = _command_scenarios(workspace)
    results: dict[str, Any] = {}
    for scenario in scenarios:
        timings: list[float] = []
        last_output_bytes = 0
        for _ in range(runs):
            started = time.perf_counter()
            completed = _run_subprocess(scenario, env=env, timeout=timeout)
            timings.append(time.perf_counter() - started)
            last_output_bytes = len(completed.stdout.encode()) + len(
                completed.stderr.encode()
            )
        results[scenario.name] = {
            **_summarize(timings),
            "argv": _display_argv(scenario.argv),
            "output_bytes": last_output_bytes,
        }
    return results


def _frame_payload(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return len(body).to_bytes(4, "big") + body


def _unframe_payload(frame: bytes) -> dict[str, Any]:
    size = int.from_bytes(frame[:4], "big")
    return json.loads(frame[4 : 4 + size])


def _mock_daemon_payloads() -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    items = [
        {
            "id": f"daemon-{idx}",
            "title": f"Fixture row {idx}",
            "status": "open" if idx % 3 else "closed",
            "updated_at": f"2026-05-13T09:{idx % 60:02d}:00Z",
        }
        for idx in range(250)
    ]
    return {
        "local_request_json": (
            {
                "schema_version": 1,
                "request_id": "bench-local-json",
                "method": "beads.list",
                "params": {"project": "demo", "limit": 50},
            },
            {"ok": True, "count": 50},
        ),
        "health_round_trip": (
            {"schema_version": 1, "request_id": "bench-health", "method": "health"},
            {
                "schema_version": 1,
                "request_id": "bench-health",
                "ok": True,
                "daemon": {"status": "mocked", "version": "epic1"},
            },
        ),
        "paged_list_round_trip": (
            {
                "schema_version": 1,
                "request_id": "bench-page",
                "method": "beads.list",
                "params": {"cursor": None, "limit": 50},
            },
            {
                "schema_version": 1,
                "request_id": "bench-page",
                "ok": True,
                "snapshot_id": "snap-20260513T090000Z",
                "cursor": "cursor-2",
                "items": items[:50],
                "total_count": len(items),
            },
        ),
        "delta_event_round_trip": (
            {
                "schema_version": 1,
                "request_id": "bench-delta",
                "method": "events.delta",
                "params": {"after": "cursor-1"},
            },
            {
                "schema_version": 1,
                "request_id": "bench-delta",
                "ok": True,
                "events": [
                    {
                        "cursor": f"evt-{idx}",
                        "kind": "notification.updated",
                        "id": f"notif-{idx}",
                        "fields": {"read": bool(idx % 2)},
                    }
                    for idx in range(100)
                ],
            },
        ),
    }


def _bench_mock_daemon(*, runs: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, (request, response) in _mock_daemon_payloads().items():
        timings: list[float] = []
        frame_bytes = 0

        def _round_trip(
            request: dict[str, Any] = request,
            response: dict[str, Any] = response,
        ) -> None:
            nonlocal frame_bytes
            request_frame = _frame_payload(request)
            decoded_request = _unframe_payload(request_frame)
            response_frame = _frame_payload(
                {**response, "request_id": decoded_request["request_id"]}
            )
            decoded_response = _unframe_payload(response_frame)
            if decoded_response["request_id"] != request["request_id"]:
                raise AssertionError("mocked daemon request_id mismatch")
            frame_bytes = len(request_frame) + len(response_frame)

        for _ in range(runs):
            timings.append(_time_call(_round_trip))
        results[name] = {**_summarize(timings), "frame_bytes": frame_bytes}
    return results


def _related_harnesses() -> dict[str, str]:
    return {
        "ace_first_paint_jk_refresh_large_history": (
            "python -m tests.perf.bench_tui_trace "
            "--output tests/perf/baselines/rust_daemon_epic1_ace.json"
        ),
        "agent_launch_fanout_fake_spawn_parent_sleeps": (
            "python tests/perf/bench_agent_launch.py "
            "--runs 5 --output tests/perf/baselines/rust_daemon_epic1_agent_launch.json"
        ),
        "notification_action_latency": (
            "python tests/perf/bench_notification_store.py "
            "--runs 5 --output tests/perf/baselines/rust_daemon_epic1_notifications.json"
        ),
    }


def run_benchmark(
    *,
    runs: int,
    real_home: bool,
    timeout: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sase_daemon_epic1_perf_") as td:
        root = Path(td)
        if real_home:
            home = None
            workspace = REPO_ROOT
        else:
            home, workspace = _prepare_hermetic_workspace(root)
        env = _base_env(home=home)
        return {
            "version": 1,
            "phase": "sase-3e.1.3",
            "runs": runs,
            "hermetic": not real_home,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
            "advisory_daemon_targets_ms": DEFAULT_TARGETS_MS,
            "command_startup": _bench_command_startup(
                runs=runs,
                env=env,
                workspace=workspace,
                timeout=timeout,
            ),
            "mock_daemon_round_trip": _bench_mock_daemon(runs=runs),
            "related_harnesses": _related_harnesses(),
            "handoff": {
                "complete": (
                    "Hermetic command startup and mocked daemon framing baselines "
                    "are captured by this harness."
                ),
                "deferred": (
                    "Real daemon transport, production command routing, and stable "
                    "regression floors are intentionally deferred to later epics."
                ),
                "validation": (
                    "pytest -q -m slow tests/perf/bench_rust_daemon_epic1.py"
                ),
            },
        }


def test_benchmark_shape_smoke() -> None:
    report = run_benchmark(runs=1, real_home=False, timeout=15.0)
    assert "python_startup" in report["command_startup"]
    assert "bead_ready" in report["command_startup"]
    assert "editor_xprompt_catalog" in report["command_startup"]
    assert "health_round_trip" in report["mock_daemon_round_trip"]
    assert "paged_list_round_trip" in report["mock_daemon_round_trip"]
    for section in ("command_startup", "mock_daemon_round_trip"):
        for summary in report[section].values():
            assert "p50_ms" in summary
            assert "p95_ms" in summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--real-home", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    report = run_benchmark(
        runs=args.runs,
        real_home=args.real_home,
        timeout=args.timeout,
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

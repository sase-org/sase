"""Demand runtime: child reaping, child env, recorded runs, and grants."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_show
from sase.tool import demand as demand_module
from sase.tool.argv import ResolvedToolArgv
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.executor_process import (
    DEMAND_FILE_NAME,
    TOOL_RUN_DEMAND_ENV,
    ChildExit,
    child_env,
    wait_child,
)
from sase.tool.executor_signals import SignalState


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_AGENT_LLM_PROVIDER",
        "SASE_LLM_PROVIDER",
        "SASE_AGENT_PROVIDER",
        "SASE_ARTIFACTS_DIR",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_DEMAND",
        "SASE_TOOL_RUN_AGENT",
        "SASE_TOOL_RUN_PROVIDER",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS",
        "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _adhoc_resolved(*argv: str) -> ResolvedToolArgv:
    from sase.tool.argv import resolve_run_argv

    return resolve_run_argv(("--", *argv))


def _spawn(*argv: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(list(argv))


def test_wait_child_reaps_exit_code_and_sets_returncode() -> None:
    proc = _spawn("sh", "-c", "exit 3")
    signals = SignalState()
    result = wait_child(proc, signals, escalate=False)
    assert isinstance(result, ChildExit)
    assert result.code == 3
    assert result.rusage is not None
    # The status is stored immediately, so a later poll cannot ECHILD into 0.
    assert proc.returncode == 3
    assert proc.poll() == 3


def test_wait_child_reports_signals_as_negative_codes() -> None:
    proc = _spawn("sh", "-c", "kill -TERM $$")
    signals = SignalState()
    result = wait_child(proc, signals, escalate=False)
    assert result.code is not None and result.code < 0
    assert proc.returncode == result.code
    assert proc.poll() == result.code


def test_wait_child_captures_cpu_for_a_burning_child() -> None:
    proc = _spawn(
        sys.executable,
        "-c",
        "import time; deadline = time.monotonic() + 0.3; n = 0\n"
        "while time.monotonic() < deadline:\n"
        "    n += 1\n",
    )
    signals = SignalState()
    result = wait_child(proc, signals, escalate=False)
    assert result.code == 0
    assert result.rusage is not None
    assert float(result.rusage.ru_utime) > 0


def test_wait_child_falls_back_on_child_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _spawn("true")
    assert proc.wait(timeout=10) == 0

    def _reaped(_pid: int, _options: int) -> object:
        raise ChildProcessError(10, "No child processes")

    monkeypatch.setattr(os, "wait4", _reaped)
    result = wait_child(proc, SignalState(), escalate=False)
    assert result.code == 0
    assert result.rusage is None


def test_wait_child_escalation_kills_an_ignored_term_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.tool.executor_process.TERM_ESCALATE_SECONDS", 0.05)
    # Its own session: the escalation SIGKILL must reach only this tree,
    # never the pytest worker's process group.
    proc = subprocess.Popen(
        ["sh", "-c", "trap '' TERM; exec sleep 60"], start_new_session=True
    )
    signals = SignalState()
    signals.bind_pgid(os.getpgid(proc.pid))
    signals.sigterm = True
    started = time.monotonic()
    result = wait_child(proc, signals, escalate=True)
    assert time.monotonic() - started < 5.0
    assert result.code is not None and result.code < 0
    proc.wait(timeout=10)


def _named_resolved() -> ResolvedToolArgv:
    return ResolvedToolArgv(
        tool_name="check",
        argv=("true",),
        extra_args=(),
        display_argv=("true",),
        private_argv=None,
        definition={},
        digest=None,
        cwd="/repo/root",
        adhoc=False,
    )


def test_child_env_sets_demand_channel_with_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    env = child_env(
        recorded=True,
        run_id="run-1",
        events_path=tmp_path / "run-1" / "events.jsonl",
        resolved=_named_resolved(),
    )
    assert env[TOOL_RUN_DEMAND_ENV] == str(tmp_path / "run-1" / DEMAND_FILE_NAME)


def test_child_env_omits_demand_channel_without_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    env = child_env(
        recorded=True, run_id="run-1", events_path=None, resolved=_named_resolved()
    )
    assert "SASE_TOOL_RUN_EVENTS" not in env
    assert TOOL_RUN_DEMAND_ENV not in env


def test_child_env_pops_demand_channel_when_unrecorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv(TOOL_RUN_DEMAND_ENV, "stale-channel")
    env = child_env(
        recorded=False, run_id=None, events_path=None, resolved=_named_resolved()
    )
    assert TOOL_RUN_DEMAND_ENV not in env


_CPU_GRANT_SNIPPET = "\n".join(
    [
        "import json, os, time",
        "deadline = time.monotonic() + 0.3",
        "n = 0",
        "while time.monotonic() < deadline:",
        "    n += 1",
        "demand_path = os.environ['SASE_TOOL_RUN_DEMAND']",
        "run_id = os.environ['SASE_TOOL_RUN_ID']",
        "grant = {'grant_id': 'g1', 'source': 'pytest',"
        " 'observed_ts_ms': 1700000000000, 'lane': 'fast', 'path': 'lease',"
        " 'requested_floor': 2, 'requested_ceiling': 8, 'granted': 3,"
        " 'budget': 12, 'wait_ms': 50,"
        " 'selected_files': None, 'escalated_from': None}",
        "record = {'schema_version': 1, 'kind': 'worker_grant',"
        " 'run_id': run_id, 'grant': grant}",
        "with open(demand_path, 'a', encoding='utf-8') as handle:",
        "    handle.write(json.dumps(record) + chr(10))",
    ]
)


def _agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # No SASE_AGENT: the run stays on the plain foreground path (no inline
    # refusal, no inline escalation), while provider and ceilings still come
    # from the harness environment.
    monkeypatch.setenv("SASE_AGENT_NAME", "fixture.agent")
    monkeypatch.setenv("SASE_AGENT_LLM_PROVIDER", "pytest-provider")
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "600")
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "300")


def _run_snippet() -> int:
    return execute_tool_run(
        ToolRunCliRequest(
            quiet=True,
            verbose=False,
            tail_lines=50,
            words=("--", sys.executable, "-c", _CPU_GRANT_SNIPPET),
        )
    )


def _latest_run_id() -> str:
    from sase.core.tool_run import tool_run_list

    runs = tool_run_list({"schema_version": 1, "limit": 1})["runs"]
    return str(runs[0]["run_id"])


def test_foreground_run_records_context_usage_and_grant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch)
    assert _run_snippet() == 0
    capsys.readouterr()
    shown = tool_run_show(_latest_run_id())
    demand = shown["run"].get("demand")
    assert isinstance(demand, dict)
    assert demand.get("context") == {
        "provider": "pytest-provider",
        "sync_ceiling_seconds": 600,
        "sync_soft_ceiling_seconds": 300,
    }
    usage = demand.get("usage")
    assert isinstance(usage, dict)
    assert usage["cpu_user_ms"] > 0
    assert usage["max_process_rss_kib"] > 0
    assert usage["tree_rss_samples"] >= 1
    assert usage["peak_tree_rss_kib"] > 0
    grants = demand.get("worker_grants")
    assert isinstance(grants, list) and len(grants) == 1
    assert grants[0]["granted"] == 3
    assert grants[0]["lane"] == "fast"


def test_demand_recording_failure_keeps_the_run_green(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch)
    monkeypatch.setattr(demand_module, "_warned_no_demand", False)

    def _boom(_request: object) -> object:
        raise RuntimeError("store gone")

    monkeypatch.setattr(demand_module, "tool_run_record_demand", _boom)
    assert _run_snippet() == 0
    captured = capsys.readouterr()
    # Context plus usage writes both fail, but the warning fires once.
    assert captured.err.count("sase: run demand not recorded") == 1


def test_adopt_worker_never_writes_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool.adopt import execute_adopted_run
    from sase.tool.handoff import reserve_handoff_run

    _clean_env(monkeypatch, tmp_path)
    # Reserved in a clean env, so the reservation records no context either.
    reservation = reserve_handoff_run(
        _adhoc_resolved("true"),
        owner_kind="monitor",
        owner_id="mon-1",
        agent="adopt.agent",
    )
    assert reservation.reserved
    # The worker runs with a provider and ceilings: if it wrote context, the
    # record would appear here.
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-1")
    monkeypatch.setenv("SASE_TOOL_RUN_PROVIDER", "adopt-provider")
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "999")
    assert execute_adopted_run(reservation.run_id) == 0
    shown = tool_run_show(reservation.run_id)
    demand = shown["run"].get("demand") or {}
    assert demand.get("context") is None
    usage = demand.get("usage") or {}
    assert usage.get("max_process_rss_kib", 0) > 0


def test_handoff_reservation_without_starter_records_provider_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool.handoff import reserve_handoff_run

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch)
    reservation = reserve_handoff_run(
        _adhoc_resolved("true"),
        owner_kind="monitor",
        owner_id="mon-1",
        agent="handoff.agent",
    )
    assert reservation.reserved
    shown = tool_run_show(reservation.run_id)
    context = (shown["run"].get("demand") or {}).get("context")
    assert context is not None
    assert context.get("provider") == "pytest-provider"
    assert "sync_ceiling_seconds" not in context
    assert "sync_soft_ceiling_seconds" not in context


def test_detached_reservation_with_starter_records_ceilings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool.handoff import reserve_handoff_run

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch)
    reservation = reserve_handoff_run(
        _adhoc_resolved("true"),
        owner_kind="proc",
        owner_id="proc-1",
        agent="detach.agent",
        starter={"agent": "detach.agent", "pid": os.getpid()},
    )
    assert reservation.reserved
    shown = tool_run_show(reservation.run_id)
    context = (shown["run"].get("demand") or {}).get("context")
    assert context is not None
    assert context.get("provider") == "pytest-provider"
    assert context.get("sync_ceiling_seconds") == 600
    assert context.get("sync_soft_ceiling_seconds") == 300


def test_tool_run_provider_overlay_from_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.monitor.start_launch import _tool_run_agent_overlay

    _clean_env(monkeypatch, tmp_path)
    assert _tool_run_agent_overlay("starter.agent") == {
        "SASE_TOOL_RUN_AGENT": "starter.agent"
    }
    monkeypatch.setenv("SASE_AGENT_LLM_PROVIDER", "claude")
    assert _tool_run_agent_overlay("starter.agent") == {
        "SASE_TOOL_RUN_AGENT": "starter.agent",
        "SASE_TOOL_RUN_PROVIDER": "claude",
    }
    assert _tool_run_agent_overlay(None) == {"SASE_TOOL_RUN_PROVIDER": "claude"}


def test_print_show_renders_demand_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool._query_shared import print_show

    print_show(
        {
            "run": {
                "run_id": "abc",
                "duration_ms": 600000,
                "demand": {
                    "context": {
                        "provider": "claude",
                        "sync_ceiling_seconds": 14400,
                    },
                    "usage": {
                        "cpu_user_ms": 2470000,
                        "cpu_system_ms": 12000,
                        "max_process_rss_kib": 1127,
                        "peak_tree_rss_kib": 10276045,
                        "tree_rss_samples": 54,
                        "availability": [],
                    },
                    "worker_grants": [
                        {
                            "grant_id": "g1",
                            "source": "pytest",
                            "lane": "fast",
                            "path": "lease",
                            "requested_floor": 4,
                            "requested_ceiling": 14,
                            "granted": 12,
                            "budget": 24,
                            "wait_ms": 182000,
                            "escalated_from": "scoped",
                        }
                    ],
                },
            }
        }
    )
    out = capsys.readouterr().out
    assert "CONTEXT   provider claude · ceiling 4h · soft —" in out
    assert (
        "DEMAND    cpu 41m 22s (4.1 cores) · max process RSS 1.1 MiB · "
        "tree RSS peak 9.8 GiB (54 samples)" in out
    )
    assert (
        "WORKERS   pytest lease 12 of 4–14 · budget 24 · "
        "waited 3m 2s · from scoped" in out
    )


def test_print_show_omits_demand_lines_when_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool._query_shared import print_show

    print_show({"run": {"run_id": "abc"}})
    out = capsys.readouterr().out
    assert "CONTEXT" not in out
    assert "DEMAND" not in out
    assert "WORKERS" not in out

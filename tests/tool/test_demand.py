"""Per-run demand recording: context, rusage, tree RSS, and grants."""

from __future__ import annotations

import json
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
from sase.tool.demand import (
    build_resource_usage,
    demand_context,
    demand_file_path,
    format_ceiling_seconds,
    format_cpu_cores,
    read_demand_grants,
    record_run_demand,
    tree_rss_kib,
)
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.executor_process import (
    DEMAND_FILE_NAME,
    TOOL_RUN_DEMAND_ENV,
    ChildExit,
    child_env,
    wait_child,
)
from sase.tool.executor_signals import SignalState
from sase.tool.render import format_kib
from sase.tool.sample import LoadSampler


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


# --- demand_context --------------------------------------------------------


def test_demand_context_from_env_provider_and_ceilings() -> None:
    env = {
        "SASE_AGENT_LLM_PROVIDER": "claude",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS": "600",
        "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS": "300",
    }
    assert demand_context(env) == {
        "provider": "claude",
        "sync_ceiling_seconds": 600,
        "sync_soft_ceiling_seconds": 300,
    }


def test_demand_context_falls_back_to_provider_overlay() -> None:
    env = {"SASE_TOOL_RUN_PROVIDER": "muse"}
    assert demand_context(env) == {"provider": "muse"}


def test_demand_context_without_starter_records_provider_only() -> None:
    env = {
        "SASE_AGENT_LLM_PROVIDER": "claude",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS": "600",
    }
    assert demand_context(env, include_ceilings=False) == {"provider": "claude"}


def test_demand_context_with_none_at_all_is_none() -> None:
    assert demand_context({}) is None
    assert demand_context({"SASE_PROVIDER_SYNC_CEILING_SECONDS": "0"}) is None
    assert demand_context({"SASE_PROVIDER_SYNC_CEILING_SECONDS": "bogus"}) is None


def test_demand_context_invalid_ceilings_are_absent() -> None:
    env = {
        "SASE_AGENT_LLM_PROVIDER": "claude",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS": "-5",
        "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS": "  ",
    }
    assert demand_context(env) == {"provider": "claude"}


# --- record_run_demand fail-open -------------------------------------------


def test_record_run_demand_failure_warns_once_and_returns_false(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demand_module, "_warned_no_demand", False)

    def _boom(_request: object) -> object:
        raise RuntimeError("store gone")

    monkeypatch.setattr(demand_module, "tool_run_record_demand", _boom)
    assert record_run_demand("run-1", usage={"cpu_user_ms": 5}) is False
    assert record_run_demand("run-1", usage={"cpu_user_ms": 5}) is False
    captured = capsys.readouterr()
    assert captured.err.count("sase: run demand not recorded") == 1


def test_record_run_demand_skips_empty_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        demand_module, "tool_run_record_demand", lambda request: calls.append(request)
    )
    assert record_run_demand("run-1") is True
    assert calls == []


# --- demand file reader ----------------------------------------------------


def _grant_line(run_id: str, **grant: object) -> str:
    base: dict[str, object] = {
        "grant_id": "g1",
        "source": "pytest",
        "observed_ts_ms": 1700000000000,
        "path": "lease",
        "requested_floor": 2,
        "requested_ceiling": 8,
        "granted": 3,
        "wait_ms": 0,
    }
    base.update(grant)
    return json.dumps(
        {"schema_version": 1, "kind": "worker_grant", "run_id": run_id, "grant": base}
    )


def test_read_demand_grants_valid_malformed_and_cross_run(tmp_path: Path) -> None:
    path = tmp_path / "demand.jsonl"
    path.write_text(
        "\n".join(
            [
                _grant_line("run-1"),
                "not json at all",
                json.dumps({"schema_version": 1, "kind": "sample"}),
                _grant_line("run-2", grant_id="other"),
                _grant_line("run-1", grant_id="g2", granted="three"),
                json.dumps(
                    {
                        "schema_version": 2,
                        "kind": "worker_grant",
                        "run_id": "run-1",
                        "grant": {"grant_id": "new"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    grants, diagnostics = read_demand_grants(path, "run-1")
    assert [grant["grant_id"] for grant in grants] == ["g1"]
    assert diagnostics == ["ignored cross-run demand record"]


def test_read_demand_grants_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_demand_grants(tmp_path / "absent.jsonl", "run-1") == ([], [])
    assert read_demand_grants(None, "run-1") == ([], [])


def test_read_demand_grants_skips_oversized_lines_and_caps_count(
    tmp_path: Path,
) -> None:
    path = tmp_path / "demand.jsonl"
    lines = ["x" * 5000]
    lines.extend(_grant_line("run-1", grant_id=f"g{i}") for i in range(70))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    grants, _ = read_demand_grants(path, "run-1")
    assert len(grants) == 64
    assert grants[0]["grant_id"] == "g0"


def test_demand_file_path_beside_events(tmp_path: Path) -> None:
    events = tmp_path / "run-1" / "events.jsonl"
    assert demand_file_path(events) == tmp_path / "run-1" / DEMAND_FILE_NAME
    assert demand_file_path(None) is None


# --- tree RSS scanner ------------------------------------------------------


def _write_stat(proc_root: Path, pid: int, comm: str, ppid: int, rss: int) -> None:
    directory = proc_root / str(pid)
    directory.mkdir(parents=True, exist_ok=True)
    # state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt
    # utime stime cutime cstime priority nice threads itreal starttime vsize
    # rss: 22 fields, ppid at 1 and rss pages at 21.
    fields = (
        ["S", str(ppid), "1", "1", "0", "-1", "0"]
        + ["0"] * 8
        + [
            "20",
            "0",
            "1",
            "0",
            "100",
            "0",
            str(rss),
        ]
    )
    assert len(fields) == 22
    (directory / "stat").write_text(
        f"{pid} ({comm}) {' '.join(fields)}", encoding="utf-8"
    )


def test_tree_rss_sums_descendants_and_survives_tricky_comm(
    tmp_path: Path,
) -> None:
    proc = tmp_path / "proc"
    _write_stat(proc, 100, "mycmd", 1, 10)
    _write_stat(proc, 101, "child", 100, 20)
    _write_stat(proc, 102, "we)ird) (name", 101, 30)
    _write_stat(proc, 200, "unrelated", 1, 1000)
    # 60 pages at 4 KiB pages.
    assert tree_rss_kib(100, proc_root=proc, page_size=4096) == 60 * 4
    assert tree_rss_kib(101, proc_root=proc, page_size=4096) == 50 * 4


def test_tree_rss_vanished_pid_and_missing_root(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_stat(proc, 100, "mycmd", 1, 10)
    assert tree_rss_kib(999, proc_root=proc) is None
    assert tree_rss_kib(100, proc_root=tmp_path / "absent") is None


def test_load_sampler_tracks_peak_and_unavailability(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_stat(proc, 100, "mycmd", 1, 10)
    sampler = LoadSampler(run_id="run-1", started=time.monotonic(), child_pid=100)
    sampler.proc_root = str(proc)
    first = sampler.maybe_sample_tree_rss()
    assert first == 10 * (os.sysconf("SC_PAGE_SIZE") // 1024)
    assert sampler.tree_rss_samples == 1
    assert sampler.peak_tree_rss_kib == first
    sampler.stop_tree_sampling()
    assert sampler.maybe_sample_tree_rss() is None
    assert sampler.tree_rss_samples == 1


def test_load_sampler_without_proc_root_reports_unavailable(
    tmp_path: Path,
) -> None:
    sampler = LoadSampler(
        run_id="run-1",
        started=time.monotonic(),
        child_pid=100,
        proc_root=str(tmp_path / "absent"),
    )
    assert sampler.maybe_sample_tree_rss() is None
    assert sampler.tree_rss_unavailable == "tree RSS unavailable on this host"
    assert sampler.tree_rss_samples == 0


# --- resource usage builder --------------------------------------------------


class _Rusage:
    def __init__(self, utime: float, stime: float, maxrss: int) -> None:
        self.ru_utime = utime
        self.ru_stime = stime
        self.ru_maxrss = maxrss


def test_build_resource_usage_from_rusage() -> None:
    usage = build_resource_usage(
        _Rusage(1.5, 0.25, 2048),
        peak_tree_rss_kib=10240,
        tree_rss_samples=3,
    )
    assert usage == {
        "cpu_user_ms": 1500,
        "cpu_system_ms": 250,
        "max_process_rss_kib": 2048,
        "peak_tree_rss_kib": 10240,
        "tree_rss_samples": 3,
        "availability": [],
    }


def test_build_resource_usage_without_rusage_carries_reason() -> None:
    usage = build_resource_usage(None, tree_rss_samples=2)
    assert usage["tree_rss_samples"] == 2
    assert usage["availability"] == ["rusage unavailable"]
    assert "cpu_user_ms" not in usage
    assert "max_process_rss_kib" not in usage


def test_build_resource_usage_normalizes_darwin_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    usage = build_resource_usage(_Rusage(0.0, 0.0, 2048 * 1024))
    assert usage["max_process_rss_kib"] == 2048


# --- formatters --------------------------------------------------------------


def test_format_kib() -> None:
    assert format_kib(None) == "—"
    assert format_kib(512) == "512 KiB"
    assert format_kib(1127) == "1.1 MiB"
    assert format_kib(10276045) == "9.8 GiB"


def test_format_ceiling_seconds() -> None:
    assert format_ceiling_seconds(None) == "—"
    assert format_ceiling_seconds(14400) == "4h"
    assert format_ceiling_seconds(600) == "10m"
    assert format_ceiling_seconds(45) == "45s"


def test_format_cpu_cores() -> None:
    assert format_cpu_cores(2340000, 600000) == "3.9"
    assert format_cpu_cores(100, 999) is None
    assert format_cpu_cores(None, 600000) is None
    assert format_cpu_cores(100, None) is None


# --- wait4 reaper --------------------------------------------------------------


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


# --- child env -----------------------------------------------------------------


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


# --- executor integration --------------------------------------------------------


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


# --- hand-off reservation context --------------------------------------------------


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


# --- monitor provider overlay --------------------------------------------------------


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


# --- show rendering --------------------------------------------------------------------


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


# --- grant writer ------------------------------------------------------------------------


def _writer_kwargs(**overrides: object) -> dict:
    kwargs: dict[str, object] = {
        "path": "lease",
        "requested_floor": 2,
        "requested_ceiling": 8,
        "granted": 7,
    }
    kwargs.update(overrides)
    return kwargs


def test_record_worker_grant_noop_without_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests._suite_gate_demand import record_worker_grant

    monkeypatch.delenv("SASE_TOOL_RUN_DEMAND", raising=False)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    assert record_worker_grant(**_writer_kwargs()) is None
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(tmp_path / "demand.jsonl"))
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    assert record_worker_grant(**_writer_kwargs()) is None


def test_record_worker_grant_appends_one_json_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import stat

    from tests._suite_gate_demand import record_worker_grant

    demand_path = tmp_path / "demand.jsonl"
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(demand_path))
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    grant_id = record_worker_grant(**_writer_kwargs(lane="fast", budget=12, wait_ms=50))
    assert grant_id
    assert stat.S_IMODE(demand_path.stat().st_mode) == 0o600
    record = json.loads(demand_path.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["kind"] == "worker_grant"
    assert record["run_id"] == "run-1"
    grant = record["grant"]
    assert grant["grant_id"] == grant_id
    assert grant["source"] == "pytest"
    assert grant["lane"] == "fast"
    assert grant["budget"] == 12
    assert grant["wait_ms"] == 50


def test_record_worker_grant_never_raises_and_caps_line_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests._suite_gate_demand import record_worker_grant

    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(tmp_path / "missing" / "d.jsonl"))
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    assert record_worker_grant(**_writer_kwargs()) is None
    demand_path = tmp_path / "demand.jsonl"
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(demand_path))
    assert record_worker_grant(**_writer_kwargs(lane="x" * 5000)) is None
    assert not demand_path.exists()

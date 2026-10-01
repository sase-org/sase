"""Tests for ``sase tool stats``: parser, handler, and end-to-end ledger read."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.main.parser_tool import register_tool_parser
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.stats_report import ToolStatsCliRequest, handle_stats


def _parse(words: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sase")
    subparsers = parser.add_subparsers(dest="command")
    register_tool_parser(subparsers)
    return parser.parse_args(words)


def test_parser_stats_defaults() -> None:
    args = _parse(["tool", "stats"])
    assert args.tool_subcommand == "stats"
    assert args.tool_stats_all is False
    assert args.tool_stats_days == 7
    assert args.tool_stats_json is False
    assert args.tool_stats_tool is None


def test_parser_stats_options() -> None:
    args = _parse(["tool", "stats", "-a", "-d", "14", "-j", "-t", "check"])
    assert args.tool_stats_all is True
    assert args.tool_stats_days == 14
    assert args.tool_stats_json is True
    assert args.tool_stats_tool == "check"


def test_stats_help_documents_options_and_caveats(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        _parse(["tool", "stats", "-h"])
    assert error.value.code == 0
    out = capsys.readouterr().out
    for option in ("-a", "--all", "-d", "--days", "-j", "--json", "-t", "--tool"):
        assert option in out
    assert "read-only" in out
    assert "baseline" in out


def test_human_render_escapes_bracketed_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool.stats_report_render import print_human

    tool = _fixture_tool("tests [x86]")
    tool["stages"] = [
        {
            "description": "oops [/foo] bar",
            "runs": 1,
            "ok": 1,
            "failed": 0,
            "incomplete": 0,
            "p50_ms": 1000,
            "p90_ms": 1000,
            "p90_over_p50": 1.0,
            "total_hours": 0.1,
        }
    ]
    tool["routes"] = [
        {
            "route": "inline",
            "runs": 1,
            "settled": 1,
            "p50_ms": 1000,
            "p90_ms": 1000,
            "under_2m": 1,
            "under_5m": 1,
            "kills": 0,
        }
    ]
    tool["providers"] = [
        {
            "provider": "acme [beta]",
            "runs": 1,
            "outcomes": {"succeeded": 1, "failed": 0, "censored": 0},
            "p50_ms": 1000,
            "p90_ms": 1000,
            "kills": 0,
            "kill_hours": 0.0,
        }
    ]
    print_human(_fixture_envelope(tools=[tool]), detail_tool="tests [x86]")
    out = capsys.readouterr().out
    assert "tests [x86]" in out
    assert "oops [/foo] bar" in out
    assert "acme [beta]" in out


def _now_ts() -> int:
    return int(time.time())


def _fixture_envelope(*, tools: list[dict[str, Any]]) -> dict[str, Any]:
    now = _now_ts()
    return {
        "schema_version": 1,
        "project": "sase",
        "window": {
            "days": 7,
            "since_ts": now - 7 * 86400,
            "now_ts": now,
            "utc_offset_seconds": 0,
        },
        "runs_scanned": sum(int(t.get("runs") or 0) for t in tools),
        "runs_truncated": False,
        "stages_truncated": False,
        "samples_truncated": False,
        "adhoc_runs": 1,
        "tools": tools,
        "pressure": {
            "buckets": 100,
            "busy_buckets": 20,
            "buckets_with_psi": 50,
            "memory_over_threshold_share": 0.04,
            "busy_memory_over_threshold_share": 0.10,
            "cpu_psi_p90": 0.4,
            "memory_psi_p90": 4.9,
            "io_psi_p90": 32.2,
            "load_per_cpu_p90": 0.6,
        },
        "thresholds": {},
        "diagnostics": [],
    }


def _fixture_tool(name: str = "check") -> dict[str, Any]:
    return {
        "project": "sase",
        "tool_name": name,
        "runs": 10,
        "definition_digests": 1,
        "extra_args_runs": 0,
        "outcomes": {
            "succeeded": 8,
            "failed": 1,
            "signaled": 1,
            "interrupted": 0,
            "lost": 0,
            "unsettled": 0,
            "censored": 1,
        },
        "terminal_causes": {},
        "duration": {
            "count": 9,
            "p10_ms": 1000,
            "p50_ms": 192000,
            "p90_ms": 845000,
            "max_ms": 900000,
            "succeeded": {},
            "failed": {},
        },
        "waste": {
            "total_hours": 1.8,
            "killed_at_ceiling": {"runs": 1, "hours": 1.8, "runs_without_duration": 0},
            "timeout": {"runs": 0, "hours": 0.0, "runs_without_duration": 0},
            "stopped": {"runs": 0, "hours": 0.0, "runs_without_duration": 0},
            "lost": {"runs": 0, "hours": 0.0, "runs_without_duration": 0},
            "interrupted": {"runs": 0, "hours": 0.0, "runs_without_duration": 0},
            "other_signal": {"runs": 0, "hours": 0.0, "runs_without_duration": 0},
        },
        "reruns_after_kill": 1,
        "routes": [
            {
                "route": "inline",
                "runs": 10,
                "settled": 10,
                "p50_ms": 192000,
                "p90_ms": 845000,
                "under_2m": 2,
                "under_5m": 5,
                "kills": 1,
            }
        ],
        "monitor_owned": {
            "runs": 4,
            "under_2m": 1,
            "under_5m": 2,
            "under_2m_share": 0.25,
        },
        "providers": [
            {
                "provider": "claude",
                "runs": 10,
                "outcomes": {"succeeded": 8, "failed": 1, "censored": 1},
                "p50_ms": 192000,
                "p90_ms": 845000,
                "kills": 1,
                "kill_hours": 1.8,
                "routes": {"inline": 10},
            }
        ],
        "trend": [
            {
                "day_start_ts": _now_ts() - 86400,
                "runs": 10,
                "succeeded": 8,
                "failed": 1,
                "censored": 1,
                "killed_at_ceiling": 1,
                "monitor_owned": 4,
                "p50_ms": 192000,
            }
        ],
        "repeats": {
            "repeat_runs": 2,
            "repeat_hours": 0.5,
            "after_censored_runs": 1,
            "after_censored_hours": 0.2,
            "duplicate_runs": 0,
            "duplicate_hours": 0.0,
            "unkeyed_runs": 0,
        },
        "demand": {
            "runs_with_context": 9,
            "runs_with_usage": 9,
            "cpu_seconds_p50": 2520.0,
            "cpu_seconds_p90": 5000.0,
            "cpu_total_hours": 8.0,
            "effective_cores_p50": 3.9,
            "effective_cores_p90": 5.0,
            "max_process_rss_kib_p50": 100000,
            "max_process_rss_kib_p90": 1153434,
            "max_process_rss_kib_max": 2000000,
            "peak_tree_rss_kib_p50": 5000000,
            "peak_tree_rss_kib_p90": 10276045,
            "peak_tree_rss_kib_max": 20000000,
            "runs_with_grants": 8,
            "grant_width_p50": 1,
            "grant_width_p90": 14,
            "grant_width_max": 16,
            "grant_paths": {"lease": 8},
            "token_wait_runs": 1,
            "token_wait_ms_total": 192000,
            "token_wait_ms_max": 192000,
            "token_wait_timeouts": 0,
            "escalated_grant_runs": 0,
        },
        "stages": [
            {
                "description": "lint (ruff)",
                "runs": 10,
                "ok": 10,
                "failed": 0,
                "incomplete": 0,
                "p50_ms": 232,
                "p90_ms": 283,
                "p90_over_p50": 1.2,
                "total_hours": 0.1,
                "median_offset_ms": 100,
            }
        ],
        "backtest": {
            "predictions": 100,
            "covered": 75,
            "coverage": 0.75,
            "median_width": 2.5,
            "target_coverage": 0.8,
            "target_max_width": 3.0,
            "meets_target": False,
        },
        "stage_backtests": [
            {
                "description": "lint (ruff)",
                "backtest": {
                    "predictions": 50,
                    "covered": 40,
                    "coverage": 0.8,
                    "median_width": 1.2,
                    "target_coverage": 0.8,
                    "target_max_width": 3.0,
                    "meets_target": True,
                },
            }
        ],
    }


def _patch_backend(monkeypatch: pytest.MonkeyPatch, envelope: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "sase.tool.stats_report.reconcile_unsettled_tool_runs", lambda: {}
    )
    monkeypatch.setattr("sase.tool.stats_report.tool_project_identity", lambda: "sase")
    monkeypatch.setattr(
        "sase.tool.stats_report.tool_run_stats_report", lambda payload: envelope
    )


def _stats_json(
    capsys: pytest.CaptureFixture[str], **kwargs: object
) -> dict[str, object]:
    params: dict[str, object] = {
        "include_all": False,
        "days": 7,
        "json": True,
        "tool": None,
    }
    params.update(kwargs)
    assert handle_stats(ToolStatsCliRequest(**params)) == 0  # type: ignore[arg-type]
    return json.loads(capsys.readouterr().out)


def test_json_passthrough_adds_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_backend(monkeypatch, _fixture_envelope(tools=[_fixture_tool()]))
    envelope = _stats_json(capsys)
    assert envelope["schema_version"] == 1
    assert envelope["host"]
    assert len(envelope["tools"]) == 1
    assert envelope["tools"][0]["tool_name"] == "check"


def test_human_tool_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_backend(
        monkeypatch,
        _fixture_envelope(tools=[_fixture_tool("check"), _fixture_tool("test")]),
    )
    assert (
        handle_stats(
            ToolStatsCliRequest(include_all=False, days=7, json=False, tool=None)
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "tool stats" in out
    assert "check" in out
    assert "run `sase tool stats -t TOOL`" in out
    assert "pressure" in out


def test_single_group_detail_sections_and_signal_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_backend(monkeypatch, _fixture_envelope(tools=[_fixture_tool()]))
    assert (
        handle_stats(
            ToolStatsCliRequest(include_all=False, days=7, json=False, tool="check")
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "STAGES" in out
    assert "ROUTES" in out
    assert "PROVIDERS" in out
    assert "TREND" in out
    assert "backtest" in out
    assert "killed at ceiling 1" in out
    assert "monitor-owned 4" in out
    assert "exact repeats" in out
    assert "content-equivalent: sase tool receipts" in out
    assert "runs with usage" in out


def test_missing_values_render_as_em_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _fixture_tool()
    tool["duration"] = {"count": 0, "succeeded": {}, "failed": {}}
    tool["demand"] = {}
    tool["backtest"] = {"predictions": 0}
    _patch_backend(monkeypatch, _fixture_envelope(tools=[tool]))
    assert (
        handle_stats(
            ToolStatsCliRequest(include_all=False, days=7, json=False, tool="check")
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "\u2014" in out
    assert "no predictions" in out


def test_empty_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_backend(monkeypatch, _fixture_envelope(tools=[]))
    assert (
        handle_stats(
            ToolStatsCliRequest(include_all=False, days=7, json=False, tool=None)
        )
        == 0
    )
    assert "no recorded runs" in capsys.readouterr().out


def test_store_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.tool.stats_report.reconcile_unsettled_tool_runs", lambda: {}
    )
    monkeypatch.setattr("sase.tool.stats_report.tool_project_identity", lambda: "sase")

    def _boom(payload: object) -> dict[str, Any]:
        raise RuntimeError("store gone")

    monkeypatch.setattr("sase.tool.stats_report.tool_run_stats_report", _boom)
    assert (
        handle_stats(
            ToolStatsCliRequest(include_all=False, days=7, json=False, tool=None)
        )
        == 1
    )
    assert "stats report failed" in capsys.readouterr().err


@pytest.mark.parametrize("days", [0, -1, 181, 1000])
def test_days_bounds_are_usage_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    days: int,
) -> None:
    monkeypatch.setattr(
        "sase.tool.stats_report.reconcile_unsettled_tool_runs", lambda: {}
    )
    assert (
        handle_stats(
            ToolStatsCliRequest(include_all=False, days=days, json=False, tool=None)
        )
        == 2
    )
    assert "-d/--days must be 1..180" in capsys.readouterr().err


def _ledger_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_BYPASS",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(repo))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.example"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "sase").mkdir()
    (repo / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "tiny": {"argv": ["true"], "args": "deny"},
                    "failer": {"argv": ["false"], "args": "deny"},
                }
            }
        ),
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    clear_config_cache()
    return repo


def test_end_to_end_two_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ledger_project(monkeypatch, tmp_path)
    assert (
        execute_tool_run(
            ToolRunCliRequest(
                quiet=True, verbose=False, tail_lines=200, words=("tiny",)
            )
        )
        == 0
    )
    assert (
        execute_tool_run(
            ToolRunCliRequest(
                quiet=True, verbose=False, tail_lines=200, words=("failer",)
            )
        )
        == 1
    )
    capsys.readouterr()
    assert (
        handle_stats(
            ToolStatsCliRequest(include_all=False, days=7, json=True, tool=None)
        )
        == 0
    )
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1
    assert envelope["host"]
    by_tool = {t["tool_name"]: t for t in envelope["tools"]}
    assert set(by_tool) == {"tiny", "failer"}
    assert by_tool["tiny"]["runs"] == 1
    assert by_tool["tiny"]["outcomes"]["succeeded"] == 1
    assert by_tool["tiny"]["outcomes"]["failed"] == 0
    assert by_tool["failer"]["runs"] == 1
    assert by_tool["failer"]["outcomes"]["failed"] == 1
    assert by_tool["failer"]["outcomes"]["succeeded"] == 0

def run_payload() -> dict[str, object]:
    return {
        "start_ts": 0,
        "end_ts": 7_200,
        "runtime_group_by": "agent",
        "bucket_seconds": 3_600,
        "totals": {
            "runs": 6,
            "completed": 3,
            "failed": 1,
            "other_terminal": 1,
            "in_progress": 1,
            "waiting": 0,
        },
        "outcomes": [
            {"name": "completed", "count": 3},
            {"name": "failed", "count": 1},
            {"name": "stopped", "count": 1},
        ],
        "retries": {"chains": 2, "attempts": 3, "kills": 1},
        "providers": [
            {
                "provider": "codex",
                "model": "gpt-5",
                "effort": "high",
                "runs": 4,
                "success_rate": 0.75,
                "mean_runtime_seconds": 200.0,
            },
            {
                "provider": "codex",
                "model": "gpt-5",
                "effort": "default",
                "runs": 1,
                "success_rate": 1.0,
                "mean_runtime_seconds": 50.0,
            },
            {
                "provider": "claude",
                "model": "opus",
                "effort": "xhigh",
                "runs": 1,
                "success_rate": 0.0,
                "mean_runtime_seconds": None,
            },
        ],
        "commits": {
            "total_commits": 7,
            "committing_agents": 3,
            "committing_runs": 3,
            "average_per_committing_agent": 7 / 3,
            "distribution": {"zero": 3, "one": 1, "two": 1, "three_plus": 1},
            "top_repos": [
                {"name": "sase", "count": 5},
                {"name": "core", "count": 2},
            ],
        },
        "plans": {
            "proposed": 4,
            "approved": 1,
            "rejected": 2,
            "pending": 1,
        },
        "questions": {"sessions": 1, "asking_agents": 1},
        "workspaces": [
            {"project": "sase", "workspace_num": 17, "runs": 4},
            {"project": "core", "workspace_num": 2, "runs": 2},
        ],
        "buckets": [
            {"start_ts": 0, "runs": 2},
            {"start_ts": 3_600, "runs": 4},
        ],
        "runtime_groups": [
            {
                "group": "alpha",
                "runs": 2,
                "total_seconds": 1_000.0,
                "mean_seconds": 500.0,
                "p50_seconds": 450.0,
                "p95_seconds": 700.0,
                "max_seconds": 750.0,
            },
            {
                "group": "beta",
                "runs": 1,
                "total_seconds": 500.0,
                "mean_seconds": 500.0,
                "p50_seconds": 500.0,
                "p95_seconds": 500.0,
                "max_seconds": 500.0,
            },
        ],
        "work": {
            "projects": [
                {
                    "project": "sase",
                    "runs": 4,
                    "completed": 3,
                    "failed": 1,
                    "other_terminal": 0,
                    "in_progress": 0,
                    "waiting": 0,
                    "success_rate": 0.75,
                    "commits": 5,
                    "distinct_patches": 2,
                    "unattributed_runs": 1,
                    "total_runtime_seconds": 1_200.0,
                    "last_run_ts": 7_000.0,
                },
                {
                    "project": "core",
                    "runs": 2,
                    "completed": 0,
                    "failed": 0,
                    "other_terminal": 1,
                    "in_progress": 1,
                    "waiting": 0,
                    "success_rate": 0.0,
                    "commits": 2,
                    "distinct_patches": 1,
                    "unattributed_runs": 0,
                    "total_runtime_seconds": 300.0,
                    "last_run_ts": 6_000.0,
                },
            ],
            "changespecs": [  # legacy wire key
                {
                    "project": "sase",
                    "name": "stats-view",
                    "status": "Ready",
                    "has_pr": True,
                    "runs": 2,
                    "distinct_agents": 2,
                    "commits": 3,
                    "total_runtime_seconds": 700.0,
                    "first_run_ts": 1_000.0,
                    "last_run_ts": 7_000.0,
                },
                {
                    "project": "core",
                    "name": "wire-work",
                    "status": "unknown",
                    "has_pr": False,
                    "runs": 2,
                    "distinct_agents": 1,
                    "commits": 2,
                    "total_runtime_seconds": 300.0,
                    "first_run_ts": 2_000.0,
                    "last_run_ts": 6_000.0,
                },
            ],
            "unattributed_runs": 1,
            "truncated_patch_rows": 1,
            "malformed_spec_files_skipped": 2,
        },
        "runners": {
            "start_ts": 0.0,
            "end_ts": 7_200.0,
            "peak_runners": 3,
            "peak_seconds": 600.0,
            "average_runners": 1.25,
            "busy_seconds": 6_000.0,
            "busy_share": 6_000 / 7_200,
            "runner_seconds": 9_000.0,
            "distribution": [
                {"runners": 0, "seconds": 1_200.0, "share": 1_200 / 7_200},
                {"runners": 1, "seconds": 3_600.0, "share": 3_600 / 7_200},
                {"runners": 2, "seconds": 1_800.0, "share": 1_800 / 7_200},
                {"runners": 3, "seconds": 600.0, "share": 600 / 7_200},
            ],
            "trend": [
                {
                    "start_ts": 0.0,
                    "end_ts": 3_600.0,
                    "average_runners": 1.0,
                    "peak_runners": 2,
                    "busy_seconds": 3_000.0,
                    "runner_seconds": 3_600.0,
                },
                {
                    "start_ts": 3_600.0,
                    "end_ts": 7_200.0,
                    "average_runners": 1.5,
                    "peak_runners": 3,
                    "busy_seconds": 3_000.0,
                    "runner_seconds": 5_400.0,
                },
            ],
            "lanes_counted": 8,
            "lanes_without_end_skipped": 3,
            "user_hidden_skipped": 4,
            "malformed_rows_skipped": 1,
            "invalid_intervals_skipped": 2,
        },
    }


def activity_payload() -> dict[str, object]:
    return {
        "skills": [
            {"name": "review", "count": 8, "distinct_agents": 3},
            {"name": "plan", "count": 4, "distinct_agents": 2},
        ],
        "memories": [
            {"name": "sase.md", "count": 5, "distinct_agents": 2},
        ],
        "plans": {
            "proposed": 3,
            "proposing_agents": 2,
            "tiers": [
                {"name": "epic", "count": 2},
                {"name": "tale", "count": 1},
            ],
            "approved": 2,
            "rejected": 1,
            "feedback": 0,
            "pending": 0,
            "phases_per_epic": [
                {"value": 2, "count": 1},
                {"value": 4, "count": 1},
            ],
            "mean_phases_per_epic": 3.0,
        },
        "questions": {
            "sessions": 2,
            "asking_agents": 2,
            "questions": 3,
            "questions_per_session": [
                {"value": 1, "count": 1},
                {"value": 2, "count": 1},
            ],
            "mean_questions_per_session": 1.5,
        },
        "coverage_start_ts": 1_000.0,
    }


def _series(value: float, **labels: str) -> dict[str, object]:
    return {"labels": dict(labels), "value": value}


def _agg(*series: dict[str, object], resolution: str = "raw") -> dict[str, object]:
    return {"resolution": resolution, "series": list(series)}


def perf_logs_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "start_ts": 1_000,
        "end_ts": 2_000,
        "startup": {
            "sessions": 3,
            "stages": [
                {
                    "stage": "process_to_mount",
                    "summary": {"samples": 3, "p50": 0.2, "p95": 0.4, "max": 0.5},
                },
                {
                    "stage": "mount_to_first_paint",
                    "summary": {"samples": 3, "p50": 0.3, "p95": 0.5, "max": 0.6},
                },
                {
                    "stage": "visible_ready",
                    "summary": {"samples": 3, "p50": 1.5, "p95": 3.0, "max": 4.0},
                },
                {
                    "stage": "all_surfaces_ready",
                    "summary": {"samples": 3, "p50": 2.0, "p95": 4.0, "max": 5.0},
                },
            ],
            "visible_ready_series": [
                {"ts": 1_100.0, "visible_ready_seconds": 1.2, "initial_tab": "agents"},
                {"ts": 1_500.0, "visible_ready_seconds": 1.5, "initial_tab": "logs"},
                {"ts": 1_900.0, "visible_ready_seconds": 4.0, "initial_tab": "agents"},
            ],
            "slowest_session": {
                "ts": 1_900.0,
                "visible_ready_seconds": 4.0,
                "initial_tab": "agents",
            },
        },
        "stalls": {
            "events": [
                {
                    "event": "tui_stall",
                    "count": 1,
                    "worst_seconds": 3.2,
                    "median_seconds": 3.2,
                    "last_seen_ts": 1_800.0,
                    "suppressed_count": 0,
                },
                {
                    "event": "tui_pump_stall",
                    "count": 0,
                    "worst_seconds": None,
                    "median_seconds": None,
                    "last_seen_ts": None,
                    "suppressed_count": 0,
                },
                {
                    "event": "tui_hitch",
                    "count": 2,
                    "worst_seconds": 0.4,
                    "median_seconds": 0.3,
                    "last_seen_ts": 1_700.0,
                    "suppressed_count": 5,
                },
                {
                    "event": "tui_pump_hitch",
                    "count": 0,
                    "worst_seconds": None,
                    "median_seconds": None,
                    "last_seen_ts": None,
                    "suppressed_count": 0,
                },
            ],
            "top_contexts": [{"name": "agents", "count": 3}],
            "recovery_count": 1,
        },
        "launches": {
            "count": 4,
            "total_ms": {"samples": 4, "p50": 200.0, "p95": 450.0, "max": 800.0},
            "slow_stage_count": 2,
            "worst_stages": [
                {
                    "ts": 1_600.0,
                    "stage": "claim",
                    "elapsed_ms": 300.0,
                    "operation": "bead.work",
                    "slow_stage": True,
                }
            ],
        },
        "agent_loads": {
            "count": 1,
            "slow_stage_count": 1,
            "worst_stage_seconds": {},
            "worst_stages": [],
        },
        "git_ops": {
            "count": 2,
            "duration_ms": {},
            "timeout_count": 1,
            "suppressed_count": 0,
            "operations": [],
            "statuses": [],
        },
        "external_tool_waits": {"count": 1, "elapsed_seconds": {}, "tools": []},
        "coverage": [
            {
                "source": "startup",
                "path": "/tmp/tui_startup.jsonl",
                "present": True,
                "records_scanned": 3,
                "records_in_window": 3,
                "earliest_ts": 1_100.0,
                "latest_ts": 1_900.0,
                "truncated": False,
                "malformed_skipped": 0,
            },
            {
                "source": "stalls",
                "path": "/tmp/tui_stalls.jsonl",
                "present": True,
                "records_scanned": 4,
                "records_in_window": 4,
                "earliest_ts": 1_200.0,
                "latest_ts": 1_800.0,
                "truncated": False,
                "malformed_skipped": 1,
            },
            {
                "source": "launch_timing",
                "path": "/tmp/tui_launch_timing.jsonl",
                "present": True,
                "records_scanned": 4,
                "records_in_window": 4,
                "earliest_ts": 1_300.0,
                "latest_ts": 1_600.0,
                "truncated": True,
                "malformed_skipped": 0,
            },
            {
                "source": "agent_loads",
                "path": "/tmp/tui_agent_loads.jsonl",
                "present": True,
                "records_scanned": 1,
                "records_in_window": 1,
                "earliest_ts": 1_400.0,
                "latest_ts": 1_400.0,
                "truncated": False,
                "malformed_skipped": 0,
            },
            {
                "source": "git_ops",
                "path": "/tmp/tui_git_ops.jsonl",
                "present": False,
                "records_scanned": 0,
                "records_in_window": 0,
                "earliest_ts": None,
                "latest_ts": None,
                "truncated": False,
                "malformed_skipped": 0,
            },
            {
                "source": "external_tools",
                "path": "/tmp/tui_external_tools.jsonl",
                "present": True,
                "records_scanned": 1,
                "records_in_window": 1,
                "earliest_ts": 1_540.0,
                "latest_ts": 1_540.0,
                "truncated": False,
                "malformed_skipped": 0,
            },
        ],
    }


def perf_telemetry_payload() -> dict[str, object]:
    return {
        "enabled": True,
        "group_by": "subsystem",
        "error": None,
        "resolution": "raw",
        "store": {
            "store_path": "/tmp/metrics.sqlite",
            "db_size_bytes": 4_096,
            "raw_sample_count": 12,
            "rollup_5m_count": 4,
            "rollup_1h_count": 2,
            "earliest_sample_ts": 1_000,
            "latest_sample_ts": 1_900,
            "last_write_ts": 1_900,
            "last_write_by_subsystem": {"agent": 1_900, "llm": 1_850},
        },
        "histograms": {
            "sase_agent_run_duration_seconds": {
                "p50": _agg(_series(40.0)),
                "p95": _agg(_series(120.0)),
                "max": _agg(_series(200.0)),
            },
            "sase_llm_invocation_duration_seconds": {
                "p50": _agg(_series(1.5)),
                "p95": _agg(_series(8.0)),
                "max": _agg(_series(20.0)),
            },
            "sase_hook_duration_seconds": {
                "p50": _agg(_series(0.2)),
                "p95": _agg(_series(0.8)),
                "max": _agg(_series(1.2)),
            },
            "sase_workflow_duration_seconds": {
                "p50": _agg(_series(12.0)),
                "p95": _agg(_series(30.0)),
                "max": _agg(_series(40.0)),
            },
            "sase_axe_cycle_duration_seconds": {
                "p50": _agg(_series(2.0)),
                "p95": _agg(_series(5.0)),
                "max": _agg(_series(7.0)),
            },
        },
        "counters": {
            "sase_agent_runs_total": _agg(_series(20.0)),
            "sase_agent_runs_total:error": _agg(_series(1.0)),
            "sase_llm_invocations_total": _agg(_series(100.0)),
            "sase_llm_errors_total": _agg(_series(5.0)),
            "sase_llm_retries_total": _agg(_series(8.0)),
            "sase_hook_executions_total": _agg(_series(10.0)),
            "sase_hook_retries_total": _agg(_series(1.0)),
            "sase_llm_input_tokens_total": _agg(_series(1_000.0)),
            "sase_llm_output_tokens_total": _agg(_series(400.0)),
            "sase_llm_cache_read_tokens_total": _agg(_series(200.0)),
        },
    }


def perf_telemetry_provider_payload() -> dict[str, object]:
    payload = perf_telemetry_payload()
    payload["group_by"] = "provider"
    payload["histograms"] = {
        "sase_agent_run_duration_seconds": {
            "p50": _agg(_series(30.0, llm_provider="codex")),
            "p95": _agg(_series(90.0, llm_provider="codex")),
            "max": _agg(_series(120.0, llm_provider="codex")),
        },
        "sase_llm_invocation_duration_seconds": {
            "p50": _agg(
                _series(1.0, provider="codex"),
                _series(2.0, provider="claude"),
            ),
            "p95": _agg(
                _series(6.0, provider="codex"),
                _series(12.0, provider="claude"),
            ),
            "max": _agg(
                _series(10.0, provider="codex"),
                _series(18.0, provider="claude"),
            ),
        },
    }
    payload["counters"] = {
        "sase_agent_runs_total": _agg(_series(8.0, llm_provider="codex")),
        "sase_agent_runs_total:error": _agg(_series(0.0, llm_provider="codex")),
        "sase_llm_invocations_total": _agg(
            _series(80.0, provider="codex"),
            _series(20.0, provider="claude"),
        ),
        "sase_llm_errors_total": _agg(
            _series(2.0, provider="codex"),
            _series(4.0, provider="claude"),
        ),
        "sase_llm_retries_total": _agg(
            _series(4.0, provider="codex"),
            _series(2.0, provider="claude"),
        ),
        "sase_llm_input_tokens_total": _agg(
            _series(800.0, provider="codex"),
            _series(200.0, provider="claude"),
        ),
        "sase_llm_output_tokens_total": _agg(
            _series(300.0, provider="codex"),
            _series(100.0, provider="claude"),
        ),
        "sase_llm_cache_read_tokens_total": _agg(
            _series(200.0, provider="codex"),
            _series(0.0, provider="claude"),
        ),
    }
    return payload

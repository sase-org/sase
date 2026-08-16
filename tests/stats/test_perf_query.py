from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from sase.stats.perf_query import query_perf_logs, query_perf_telemetry
from sase.telemetry._config import HealthThresholds, _TelemetryConfig


def test_query_perf_logs_resolves_paths_and_calls_binding(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    def binding(request: dict[str, object]) -> dict[str, Any]:
        calls.append(request)
        return {"schema_version": 1, "startup": {"sessions": 0}}

    monkeypatch.setattr(
        "sase.stats.perf_query.require_rust_binding",
        lambda name: binding if name == "perf_logs_query" else None,
    )
    startup = tmp_path / "tui_startup.jsonl"
    stalls = tmp_path / "tui_stalls.jsonl"

    result = query_perf_logs(
        start_ts=10,
        end_ts=20,
        paths={"startup": startup, "stalls": stalls},
    )

    assert result["schema_version"] == 1
    assert calls[0]["start_ts"] == 10
    assert calls[0]["end_ts"] == 20
    sources = {
        row["id"]: row["path"]
        for row in calls[0]["sources"]  # type: ignore[index]
    }
    assert sources["startup"] == str(startup)
    assert sources["stalls"] == str(stalls)
    assert set(sources) == {
        "startup",
        "stalls",
        "agent_loads",
        "launch_timing",
        "git_ops",
        "external_tools",
    }


def test_query_perf_logs_uses_canonical_log_paths(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[list[dict[str, str]]] = []

    def binding(request: dict[str, object]) -> dict[str, Any]:
        captured.append(request["sources"])  # type: ignore[arg-type]
        return {}

    monkeypatch.setattr(
        "sase.stats.perf_query.require_rust_binding", lambda _name: binding
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.tui_startup_jsonl_path",
        lambda: tmp_path / "startup.jsonl",
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.tui_stalls_jsonl_path",
        lambda: tmp_path / "stalls.jsonl",
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.tui_agent_loads_jsonl_path",
        lambda: tmp_path / "loads.jsonl",
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.tui_launch_timing_jsonl_path",
        lambda: tmp_path / "launch.jsonl",
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.tui_git_ops_jsonl_path",
        lambda: tmp_path / "git.jsonl",
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.tui_external_tools_jsonl_path",
        lambda: tmp_path / "ext.jsonl",
    )

    query_perf_logs(start_ts=1, end_ts=2)

    by_id = {row["id"]: row["path"] for row in captured[0]}
    assert by_id["startup"] == str(tmp_path / "startup.jsonl")
    assert by_id["external_tools"] == str(tmp_path / "ext.jsonl")


def test_query_perf_telemetry_disabled_does_not_query(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.stats.perf_query.get_telemetry_config",
        lambda: _TelemetryConfig(enabled=False),
    )
    calls: list[object] = []
    monkeypatch.setattr(
        "sase.stats.perf_query.query_range",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {},
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.store_stats",
        lambda: calls.append("store") or {},
    )

    result = query_perf_telemetry(start_ts=0, end_ts=60, group_by="subsystem")

    assert result == {"enabled": False, "group_by": "subsystem"}
    assert calls == []


def test_query_perf_telemetry_subsystem_uses_enumerated_set(
    monkeypatch: MonkeyPatch,
) -> None:
    queries = _patch_enabled_queries(monkeypatch)

    result = query_perf_telemetry(start_ts=100, end_ts=200, group_by="subsystem")

    assert result["enabled"] is True
    assert result["resolution"] == "raw"
    assert result["store"]["raw_sample_count"] == 3
    metrics = {
        (item["metric"], item["aggregation"], item["quantile"]) for item in queries
    }
    assert (
        "sase_agent_run_duration_seconds",
        "quantile",
        0.5,
    ) in metrics
    assert (
        "sase_agent_run_duration_seconds",
        "quantile",
        0.95,
    ) in metrics
    assert ("sase_agent_run_duration_seconds", "max", None) in metrics
    assert ("sase_hook_duration_seconds", "quantile", 0.95) in metrics
    assert ("sase_axe_cycle_duration_seconds", "max", None) in metrics
    assert ("sase_llm_input_tokens_total", "sum", None) in metrics
    filtered = [item for item in queries if item["filters"] == {"status": "error"}]
    assert filtered[0]["metric"] == "sase_agent_runs_total"
    assert all(item["group_by"] == () for item in queries)
    assert all(item["step_seconds"] == 100 for item in queries)


def test_query_perf_telemetry_provider_replaces_ungrouped_counterparts(
    monkeypatch: MonkeyPatch,
) -> None:
    queries = _patch_enabled_queries(monkeypatch)

    query_perf_telemetry(start_ts=0, end_ts=10, group_by="provider")

    metrics = {item["metric"] for item in queries}
    assert "sase_hook_duration_seconds" not in metrics
    assert "sase_workflow_duration_seconds" not in metrics
    assert "sase_axe_cycle_duration_seconds" not in metrics
    agent = next(
        item
        for item in queries
        if item["metric"] == "sase_agent_run_duration_seconds"
        and item["aggregation"] == "quantile"
    )
    assert agent["group_by"] == ("llm_provider",)
    llm = next(item for item in queries if item["metric"] == "sase_llm_errors_total")
    assert llm["group_by"] == ("provider",)
    tokens = next(
        item for item in queries if item["metric"] == "sase_llm_cache_read_tokens_total"
    )
    assert tokens["group_by"] == ("provider",)


def test_query_perf_telemetry_workflow_selects_named_metrics(
    monkeypatch: MonkeyPatch,
) -> None:
    queries = _patch_enabled_queries(monkeypatch)

    query_perf_telemetry(start_ts=0, end_ts=10, group_by="workflow")

    metrics = {item["metric"] for item in queries}
    assert metrics == {
        "sase_agent_run_duration_seconds",
        "sase_workflow_duration_seconds",
        "sase_agent_runs_total",
    }
    assert all(item["group_by"] == ("workflow",) for item in queries)


def test_query_perf_telemetry_never_raises_on_store_errors(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.stats.perf_query.get_telemetry_config",
        lambda: _TelemetryConfig(enabled=True, health_thresholds=HealthThresholds()),
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.store_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("busy")),
    )

    def failing_query_range(_metric: str, **_kwargs: object) -> dict[str, object]:
        raise ValueError("missing store")

    monkeypatch.setattr("sase.stats.perf_query.query_range", failing_query_range)

    result = query_perf_telemetry(start_ts=0, end_ts=10)

    assert result["enabled"] is True
    assert result["error"] == "busy"
    assert result["histograms"] == {}
    assert result["counters"] == {}
    assert result["resolution"] is None


def test_query_perf_telemetry_combines_mixed_resolutions(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.stats.perf_query.get_telemetry_config",
        lambda: _TelemetryConfig(enabled=True),
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.store_stats", lambda: {"raw_sample_count": 1}
    )
    resolutions = iter(["raw", "5m", "1h"])

    def query_range(_metric: str, **_kwargs: object) -> dict[str, object]:
        try:
            resolution = next(resolutions)
        except StopIteration:
            resolution = "1h"
        return {
            "resolution": resolution,
            "series": [{"labels": {}, "points": [{"ts": 1, "value": 1.0}]}],
        }

    monkeypatch.setattr("sase.stats.perf_query.query_range", query_range)

    result = query_perf_telemetry(start_ts=0, end_ts=10, group_by="workflow")

    assert result["resolution"] == "mixed"


def test_load_statistics_view_builds_perf_only_for_perf_view(
    monkeypatch: MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.statistics_pane_data import load_statistics_view
    from sase.project_display_names import ProjectDisplaySnapshot
    from sase.stats.ranges import StatsRange
    from tests.stats._views_payloads import perf_logs_payload, perf_telemetry_payload

    perf_log_calls: list[dict[str, int]] = []
    telemetry_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_run_stats",
        lambda **_kwargs: {"totals": {"runs": 0}},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_activity_stats",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.load_project_display_snapshot",
        ProjectDisplaySnapshot,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.get_max_running_agents",
        lambda: 2,
        raising=False,
    )
    monkeypatch.setattr(
        "sase.config.core.get_max_running_agents",
        lambda: 2,
    )
    monkeypatch.setattr(
        "sase.telemetry._config.get_telemetry_config",
        lambda: _TelemetryConfig(enabled=True),
    )

    def logs(*, start_ts: int, end_ts: int, paths: object = None) -> dict[str, object]:
        del paths
        perf_log_calls.append({"start_ts": start_ts, "end_ts": end_ts})
        return perf_logs_payload()

    def telemetry(
        *, start_ts: int, end_ts: int, group_by: str = "subsystem"
    ) -> dict[str, object]:
        telemetry_calls.append(
            {"start_ts": start_ts, "end_ts": end_ts, "group_by": group_by}
        )
        return perf_telemetry_payload()

    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_perf_logs", logs
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_perf_telemetry", telemetry
    )
    selected = StatsRange(1_000, 2_000, "span", "Last hour")

    overview = load_statistics_view("overview", selected)
    assert overview.perf is None
    assert perf_log_calls == []
    assert telemetry_calls == []

    result = load_statistics_view("perf", selected, perf_group_by="provider")
    assert result.perf is not None
    assert result.perf.group_by == "provider"
    assert result.perf.startup.sessions == 3
    assert [call["group_by"] for call in telemetry_calls] == [
        "provider",
        "provider",
    ]
    assert perf_log_calls == [
        {"start_ts": 1_000, "end_ts": 2_000},
        {"start_ts": 0, "end_ts": 1_000},
    ]


def _patch_enabled_queries(monkeypatch: MonkeyPatch) -> list[dict[str, object]]:
    queries: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.stats.perf_query.get_telemetry_config",
        lambda: _TelemetryConfig(enabled=True),
    )
    monkeypatch.setattr(
        "sase.stats.perf_query.store_stats",
        lambda: {"raw_sample_count": 3, "db_size_bytes": 128},
    )

    def query_range(
        metric: str,
        *,
        start_ts: int,
        end_ts: int,
        step_seconds: int,
        kind: str | None = None,
        filters: dict[str, str] | None = None,
        group_by: object = None,
        aggregation: str | None = None,
        quantile: float | None = None,
    ) -> dict[str, object]:
        del start_ts, end_ts, kind
        queries.append(
            {
                "metric": metric,
                "aggregation": aggregation,
                "quantile": quantile,
                "filters": filters or {},
                "group_by": tuple(group_by) if group_by is not None else (),
                "step_seconds": step_seconds,
            }
        )
        return {
            "resolution": "raw",
            "series": [{"labels": {}, "points": [{"ts": 1, "value": 2.0}]}],
        }

    monkeypatch.setattr("sase.stats.perf_query.query_range", query_range)
    return queries

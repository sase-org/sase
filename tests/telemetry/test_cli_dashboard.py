"""Tests for the local-store telemetry dashboard."""

from pathlib import Path

from rich.console import Console

from sase.telemetry.cli_dashboard import _render_dashboard, load_dashboard_data
from tests.telemetry.conftest import record_samples, use_store


def _render(renderable: object) -> str:
    console = Console(file=None, force_terminal=False, width=120)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _seed_dashboard(store_path: Path) -> None:
    record_samples(
        store_path,
        [
            {
                "ts": 100,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {"llm_provider": "codex", "status": "ok", "workflow": ""},
                "source": "agent-1",
                "value": 9,
            },
            {
                "ts": 100,
                "metric": "sase_agent_runs_total",
                "kind": "counter",
                "labels": {
                    "llm_provider": "codex",
                    "status": "error",
                    "workflow": "",
                },
                "source": "agent-1",
                "value": 1,
            },
            {
                "ts": 100,
                "metric": "sase_agent_run_duration_seconds",
                "kind": "histogram",
                "labels": {"llm_provider": "codex", "workflow": ""},
                "source": "agent-1",
                "count": 2,
                "sum": 58,
                "min": 8,
                "max": 50,
                "buckets": [{"le": 10, "count": 1}, {"le": 60, "count": 2}],
            },
            {
                "ts": 190,
                "metric": "sase_agent_active",
                "kind": "gauge",
                "labels": {"llm_provider": "codex", "project": "sase"},
                "source": "axe-1",
                "value": 2,
            },
            {
                "ts": 190,
                "metric": "sase_workspace_active",
                "kind": "gauge",
                "labels": {"project": "sase"},
                "source": "axe-1",
                "value": 3,
            },
            {
                "ts": 190,
                "metric": "sase_bead_active",
                "kind": "gauge",
                "labels": {"project": "sase", "status": "in_progress"},
                "source": "axe-1",
                "value": 4,
            },
            {
                "ts": 120,
                "metric": "sase_llm_input_tokens_total",
                "kind": "counter",
                "labels": {"provider": "codex"},
                "source": "agent-1",
                "value": 1000,
            },
            {
                "ts": 120,
                "metric": "sase_llm_output_tokens_total",
                "kind": "counter",
                "labels": {"provider": "codex"},
                "source": "agent-1",
                "value": 250,
            },
        ],
        now_ts=200,
    )


def test_dashboard_loads_real_local_store(tmp_path: Path) -> None:
    store_path = tmp_path / "metrics.sqlite"
    use_store(store_path)
    _seed_dashboard(store_path)

    data = load_dashboard_data(now_ts=200, range_key="15m", subsystem="agents")

    assert data.has_samples
    assert data.active_agents == 2
    assert data.active_workspaces == 3
    assert data.active_beads == 4
    assert data.runs_in_range == 10
    assert data.error_rate == 10
    assert [chart.title for chart in data.charts] == [
        "Agent Runs by status",
        "Run Duration p50/p95",
        "LLM Tokens by provider",
        "Error Rate %",
    ]


def test_dashboard_render_has_tiles_and_charts(tmp_path: Path) -> None:
    store_path = tmp_path / "metrics.sqlite"
    use_store(store_path)
    _seed_dashboard(store_path)
    data = load_dashboard_data(now_ts=200, range_key="15m", subsystem="agents")

    output = _render(_render_dashboard(data, width=120))

    assert "Active Agents" in output
    assert "Active Workspaces" in output
    assert "Error Rate" in output
    assert "Agent Runs by status" in output
    assert "Run Duration p50/p95" in output


def test_dashboard_switches_subsystem_chart_set(tmp_path: Path) -> None:
    store_path = tmp_path / "metrics.sqlite"
    use_store(store_path)
    _seed_dashboard(store_path)

    data = load_dashboard_data(now_ts=200, range_key="15m", subsystem="workspace")

    assert data.charts[0].title == "Active Workspaces"
    assert data.charts[-1].title == "VCS Operations"


def test_dashboard_empty_store_is_friendly(tmp_path: Path) -> None:
    use_store(tmp_path / "metrics.sqlite")

    data = load_dashboard_data(now_ts=200, range_key="1h", subsystem="agents")
    output = _render(_render_dashboard(data, width=120))

    assert not data.has_samples
    assert "No telemetry samples have been recorded yet" in output

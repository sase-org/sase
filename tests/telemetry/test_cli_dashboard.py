"""Tests for ``sase telemetry dashboard`` CLI subcommand."""

from argparse import Namespace
from unittest.mock import patch

from rich.console import Console

from sase.telemetry.cli_dashboard import (
    _build_dashboard,
    _build_stat_panels,
    handle_telemetry_dashboard,
)
from sase.telemetry.scrape import MetricSample
from tests.telemetry.conftest import reset_telemetry_config

_MOCK_SAMPLES = [
    MetricSample(
        name="sase_agent_runs_total",
        labels={"llm_provider": "claude", "status": "ok", "workflow": ""},
        value=42.0,
        metric_type="counter",
    ),
    MetricSample(
        name="sase_agent_runs_total",
        labels={"llm_provider": "claude", "status": "error", "workflow": ""},
        value=3.0,
        metric_type="counter",
    ),
    MetricSample(
        name="sase_agent_active",
        labels={"llm_provider": "claude", "project": "sase"},
        value=2.0,
        metric_type="gauge",
    ),
    MetricSample(
        name="sase_bead_operations_total",
        labels={"operation": "create"},
        value=5.0,
        metric_type="counter",
    ),
]


def setup_function() -> None:
    reset_telemetry_config()


def teardown_function() -> None:
    reset_telemetry_config()


def _render(renderable: object) -> str:
    """Render a Rich renderable to a string."""
    console = Console(file=None, force_terminal=False, width=120)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_dashboard_shows_subsystem_panels() -> None:
    output = _render(_build_dashboard(_MOCK_SAMPLES))
    assert "Agent Lifecycle" in output
    assert "Beads" in output


def test_dashboard_shows_metric_values() -> None:
    output = _render(_build_dashboard(_MOCK_SAMPLES))
    # Agent runs total = 42 + 3 = 45
    assert "45" in output


def test_dashboard_shows_gauge_values() -> None:
    output = _render(_build_dashboard(_MOCK_SAMPLES))
    assert "2" in output


def test_dashboard_empty_samples() -> None:
    output = _render(_build_dashboard([]))
    assert "Agent Lifecycle" not in output


def test_dashboard_unreachable_source() -> None:
    """When no source is reachable, dashboard shows an error message."""
    args = Namespace(
        source="auto", interval=5, charts=False, range="1h", subsystem=None
    )
    output_parts: list[str] = []
    console = Console(file=None, force_terminal=False, width=120)

    def fake_print(*args: object, **_kw: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    with (
        patch("sase.telemetry.cli_dashboard.Console") as mock_console_cls,
        patch("sase.telemetry.cli_dashboard._resolve_source", return_value=None),
    ):
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        handle_telemetry_dashboard(args)

    output = "\n".join(output_parts)
    assert "No metric source is reachable" in output


def test_dashboard_panel_labels_are_readable() -> None:
    """Dashboard converts metric names to readable labels."""
    output = _render(_build_dashboard(_MOCK_SAMPLES))
    assert "Agent Runs" in output or "Agent Active" in output


# ── Stat panels ──────────────────────────────────────────────────────


def test_stat_panels_show_key_gauges() -> None:
    samples = [
        MetricSample(name="sase_agent_active", value=3.0, metric_type="gauge"),
        MetricSample(name="sase_workspace_active", value=1.0, metric_type="gauge"),
        MetricSample(name="sase_bead_active", value=7.0, metric_type="gauge"),
    ]
    panels = _build_stat_panels(samples)
    assert len(panels) == 3
    rendered = "\n".join(_render(p) for p in panels)
    assert "Active Agents" in rendered
    assert "Active Workspaces" in rendered
    assert "Active Beads" in rendered


def test_stat_panels_zero_when_missing() -> None:
    panels = _build_stat_panels([])
    assert len(panels) == 3
    rendered = "\n".join(_render(p) for p in panels)
    assert "0" in rendered


# ── Charts mode fallback ────────────────────────────────────────────


def test_charts_mode_falls_back_when_prometheus_unreachable() -> None:
    """Charts mode falls back to summary when Prometheus is unreachable."""
    args = Namespace(source="auto", interval=5, charts=True, range="1h", subsystem=None)
    output_parts: list[str] = []
    console = Console(file=None, force_terminal=False, width=120)

    def fake_print(*args: object, **_kw: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    with (
        patch("sase.telemetry.cli_dashboard.Console") as mock_console_cls,
        patch(
            "sase.telemetry.prom_query.check_prometheus_reachable",
            return_value=False,
        ),
        patch("sase.telemetry.cli_dashboard._resolve_source", return_value=None),
    ):
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        handle_telemetry_dashboard(args)

    output = "\n".join(output_parts)
    assert "falling back to summary" in output or "No metric source" in output

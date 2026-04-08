"""Tests for ``sase telemetry dashboard`` CLI subcommand."""

from argparse import Namespace
from unittest.mock import patch

from rich.console import Console

from sase.telemetry.cli_dashboard import _build_dashboard, handle_telemetry_dashboard
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


def _render_dashboard(samples: list[MetricSample]) -> str:
    """Render the dashboard layout to a string."""
    console = Console(file=None, force_terminal=False, width=120)
    layout = _build_dashboard(samples)
    with console.capture() as capture:
        console.print(layout)
    return capture.get()


def test_dashboard_shows_subsystem_panels() -> None:
    output = _render_dashboard(_MOCK_SAMPLES)
    assert "Agent Lifecycle" in output
    assert "Beads" in output


def test_dashboard_shows_metric_values() -> None:
    output = _render_dashboard(_MOCK_SAMPLES)
    # Agent runs total = 42 + 3 = 45
    assert "45" in output


def test_dashboard_shows_gauge_values() -> None:
    output = _render_dashboard(_MOCK_SAMPLES)
    assert "2" in output


def test_dashboard_empty_samples() -> None:
    output = _render_dashboard([])
    # Should render without error, just no panels
    assert output.strip() == "" or "Agent" not in output


def test_dashboard_unreachable_source() -> None:
    """When no source is reachable, dashboard shows an error message."""
    args = Namespace(source="auto", interval=5)
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
    output = _render_dashboard(_MOCK_SAMPLES)
    # sase_agent_runs -> "Agent Runs"
    assert "Agent Runs" in output or "Agent Active" in output

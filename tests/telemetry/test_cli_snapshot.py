"""Tests for ``sase telemetry snapshot`` CLI subcommand."""

from argparse import Namespace
from unittest.mock import patch

from rich.console import Console

from sase.telemetry.cli_snapshot import handle_telemetry_snapshot
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


def _capture_snapshot(**kwargs: object) -> str:
    """Run handle_telemetry_snapshot and capture the Rich console output."""
    args = Namespace(
        source=kwargs.get("source", "auto"),
        format=kwargs.get("format", "rich"),
        subsystem=kwargs.get("subsystem"),
    )
    console = Console(file=None, force_terminal=False, width=120)
    output_parts: list[str] = []

    def fake_print(*args: object, **_kw: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    with (
        patch("sase.telemetry.cli_snapshot.Console") as mock_console_cls,
        patch(
            "sase.telemetry.cli_snapshot._resolve_source",
            return_value="http://localhost:9091/metrics",
        ),
        patch("sase.telemetry.cli_snapshot.scrape", return_value=_MOCK_SAMPLES),
    ):
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        handle_telemetry_snapshot(args)

    return "\n".join(output_parts)


def _capture_snapshot_unreachable(**kwargs: object) -> str:
    """Run with no reachable source."""
    args = Namespace(
        source=kwargs.get("source", "auto"),
        format=kwargs.get("format", "rich"),
        subsystem=kwargs.get("subsystem"),
    )
    console = Console(file=None, force_terminal=False, width=120)
    output_parts: list[str] = []

    def fake_print(*args: object, **_kw: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    with (
        patch("sase.telemetry.cli_snapshot.Console") as mock_console_cls,
        patch("sase.telemetry.cli_snapshot._resolve_source", return_value=None),
    ):
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        handle_telemetry_snapshot(args)

    return "\n".join(output_parts)


def test_snapshot_rich_shows_subsystem_panels() -> None:
    output = _capture_snapshot()
    assert "Agent Lifecycle" in output
    assert "Beads" in output


def test_snapshot_rich_shows_metric_values() -> None:
    output = _capture_snapshot()
    assert "42" in output
    assert "sase_agent_runs_total" in output


def test_snapshot_rich_shows_labels() -> None:
    output = _capture_snapshot()
    assert "claude" in output


def test_snapshot_filter_by_subsystem() -> None:
    output = _capture_snapshot(subsystem="Beads")
    assert "Beads" in output
    assert "Agent Lifecycle" not in output
    assert "sase_bead_operations_total" in output


def test_snapshot_filter_no_match() -> None:
    output = _capture_snapshot(subsystem="Nonexistent")
    assert "No metrics match" in output or "No known metrics" in output


def test_snapshot_json_format() -> None:
    output = _capture_snapshot(format="json")
    assert '"name"' in output
    assert '"sase_agent_runs_total"' in output
    assert '"value"' in output


def test_snapshot_prometheus_format() -> None:
    output = _capture_snapshot(format="prometheus")
    assert "sase_agent_runs_total" in output
    assert "42.0" in output


def test_snapshot_unreachable() -> None:
    output = _capture_snapshot_unreachable()
    assert "No metric source is reachable" in output


def test_snapshot_subsystem_case_insensitive() -> None:
    output = _capture_snapshot(subsystem="beads")
    assert "Beads" in output
    assert "sase_bead_operations_total" in output

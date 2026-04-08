"""Tests for ``sase telemetry list`` CLI subcommand."""

from argparse import Namespace
from unittest.mock import patch

from rich.console import Console

from sase.telemetry.cli_list import handle_telemetry_list


def _capture_list(**kwargs: object) -> str:
    """Run handle_telemetry_list and capture the Rich console output."""
    args = Namespace(
        subsystem=kwargs.get("subsystem"),
        type=kwargs.get("type"),
    )
    console = Console(file=None, force_terminal=False, width=120)
    output_parts: list[str] = []

    def fake_print(*args: object, **kw: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    with patch("sase.telemetry.cli_list.Console") as mock_console_cls:
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        handle_telemetry_list(args)

    return "\n".join(output_parts)


def test_list_shows_all_subsystems() -> None:
    output = _capture_list()
    assert "Agent Lifecycle" in output
    assert "LLM Provider" in output
    assert "Axe Orchestrator" in output
    assert "Beads" in output
    assert "VCS / Workspace" in output
    assert "Notifications" in output


def test_list_shows_metric_names() -> None:
    output = _capture_list()
    assert "AGENT_RUNS" in output
    assert "sase_agent_runs_total" in output


def test_list_shows_kind_labels() -> None:
    output = _capture_list()
    assert "counter" in output
    assert "histogram" in output
    assert "gauge" in output


def test_list_filter_by_subsystem() -> None:
    output = _capture_list(subsystem="Beads")
    assert "Beads" in output
    assert "Agent Lifecycle" not in output
    assert "BEAD_OPERATIONS" in output


def test_list_filter_by_type() -> None:
    output = _capture_list(type="gauge")
    # Should only show gauges
    assert "gauge" in output
    # Counters should not appear as table rows (they may appear in panel titles)
    assert "AGENT_RUNS" not in output


def test_list_filter_no_match() -> None:
    output = _capture_list(subsystem="Nonexistent")
    assert "No metrics match" in output


def test_list_filter_subsystem_case_insensitive() -> None:
    output = _capture_list(subsystem="beads")
    assert "Beads" in output
    assert "BEAD_OPERATIONS" in output

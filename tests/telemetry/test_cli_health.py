"""Tests for ``sase telemetry health`` CLI subcommand."""

from argparse import Namespace
from unittest.mock import patch

from rich.console import Console

from sase.telemetry._config import HealthThresholds
from sase.telemetry.cli_health import (
    CRITICAL,
    OK,
    WARN,
    _SubsystemHealth,
    _overall_status,
    _assess_health,
    handle_telemetry_health,
)
from sase.telemetry.scrape import MetricSample
from tests.telemetry.conftest import reset_telemetry_config


def setup_function() -> None:
    reset_telemetry_config()


def teardown_function() -> None:
    reset_telemetry_config()


_DEFAULT_THRESHOLDS = HealthThresholds()


# --- _assess_health unit tests ---


def test_health_agents_ok() -> None:
    """Agent error rate below warn threshold -> OK."""
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 90.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 5.0, "counter"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    agents = [r for r in results if r.name == "Agents"]
    assert len(agents) == 1
    assert agents[0].status == OK
    assert "5.3%" in agents[0].detail


def test_health_agents_warn() -> None:
    """Agent error rate above warn threshold -> WARN."""
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 80.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 15.0, "counter"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    agents = [r for r in results if r.name == "Agents"]
    assert agents[0].status == WARN


def test_health_agents_critical() -> None:
    """Agent error rate above critical threshold -> CRITICAL."""
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 70.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 30.0, "counter"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    agents = [r for r in results if r.name == "Agents"]
    assert agents[0].status == CRITICAL


def test_health_llm_ok() -> None:
    """LLM with low error rate -> OK."""
    samples = [
        MetricSample("sase_llm_invocations_total", {}, 100.0, "counter"),
        MetricSample("sase_llm_errors_total", {}, 1.0, "counter"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    llm = [r for r in results if r.name == "LLM"]
    assert len(llm) == 1
    assert llm[0].status == OK


def test_health_hooks_retry_rate() -> None:
    """Hooks retry rate check."""
    samples = [
        MetricSample("sase_hook_executions_total", {}, 100.0, "counter"),
        MetricSample("sase_hook_retries_total", {}, 15.0, "counter"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    hooks = [r for r in results if r.name == "Hooks"]
    assert len(hooks) == 1
    assert hooks[0].status == WARN
    assert "15.0%" in hooks[0].detail


def test_health_axe_no_errors() -> None:
    """Axe with zero errors -> OK."""
    samples = [
        MetricSample("sase_axe_cycles_total", {}, 100.0, "counter"),
        MetricSample("sase_axe_errors_total", {}, 0.0, "counter"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    axe = [r for r in results if r.name == "Axe"]
    assert len(axe) == 1
    assert axe[0].status == OK


def test_health_axe_with_errors() -> None:
    """Axe with errors -> WARN or CRITICAL."""
    samples = [
        MetricSample("sase_axe_cycles_total", {}, 100.0, "counter"),
        MetricSample("sase_axe_errors_total", {}, 3.0, "counter"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    axe = [r for r in results if r.name == "Axe"]
    assert axe[0].status == WARN


def test_health_beads_ok() -> None:
    """Beads with operations -> OK."""
    samples = [
        MetricSample("sase_bead_operations_total", {}, 10.0, "counter"),
        MetricSample("sase_bead_active", {}, 2.0, "gauge"),
    ]
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    beads = [r for r in results if r.name == "Beads"]
    assert len(beads) == 1
    assert beads[0].status == OK


def test_health_empty_samples() -> None:
    """No samples -> no results."""
    results = _assess_health([], _DEFAULT_THRESHOLDS)
    assert results == []


def test_health_custom_thresholds() -> None:
    """Custom thresholds change classification."""
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 90.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 6.0, "counter"),
    ]
    # With default thresholds (10% warn), 6.25% -> OK
    results = _assess_health(samples, _DEFAULT_THRESHOLDS)
    agents = [r for r in results if r.name == "Agents"]
    assert agents[0].status == OK

    # With strict thresholds (5% warn), 6.25% -> WARN
    strict = HealthThresholds(error_rate_warn=5.0, error_rate_critical=15.0)
    results = _assess_health(samples, strict)
    agents = [r for r in results if r.name == "Agents"]
    assert agents[0].status == WARN


# --- _overall_status tests ---


def test_overall_ok() -> None:
    results = [_SubsystemHealth("A", OK, ""), _SubsystemHealth("B", OK, "")]
    assert _overall_status(results) == OK


def test_overall_degraded() -> None:
    results = [_SubsystemHealth("A", OK, ""), _SubsystemHealth("B", WARN, "")]
    assert _overall_status(results) == WARN


def test_overall_critical() -> None:
    results = [
        _SubsystemHealth("A", OK, ""),
        _SubsystemHealth("B", WARN, ""),
        _SubsystemHealth("C", CRITICAL, ""),
    ]
    assert _overall_status(results) == CRITICAL


# --- handle_telemetry_health integration tests ---


def _capture_health(
    samples: list[MetricSample],
    *,
    use_json: bool = False,
    source: str = "auto",
) -> tuple[str, int]:
    """Run handle_telemetry_health and capture output + exit code."""
    args = Namespace(source=source, json=use_json)
    console = Console(file=None, force_terminal=False, width=120)
    output_parts: list[str] = []
    exit_code = 0

    def fake_print(*args: object, **_kw: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    def fake_exit(code: int = 0) -> None:
        nonlocal exit_code
        exit_code = code

    with (
        patch("sase.telemetry.cli_health.Console") as mock_console_cls,
        patch(
            "sase.telemetry.cli_health._resolve_source",
            return_value="http://localhost:9091/metrics",
        ),
        patch("sase.telemetry.cli_health.scrape", return_value=samples),
        patch("sase.telemetry.cli_health.sys") as mock_sys,
    ):
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        mock_sys.exit = fake_exit
        handle_telemetry_health(args)

    return "\n".join(output_parts), exit_code


def test_health_handler_rich_output() -> None:
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 90.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 5.0, "counter"),
    ]
    output, code = _capture_health(samples)
    assert "Health Check" in output
    assert "Agents" in output
    assert "HEALTHY" in output
    assert code == 0


def test_health_handler_json_output() -> None:
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 90.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 5.0, "counter"),
    ]
    output, code = _capture_health(samples, use_json=True)
    assert '"status": "ok"' in output
    assert '"name": "Agents"' in output
    assert code == 0


def test_health_handler_exit_code_degraded() -> None:
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 80.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 15.0, "counter"),
    ]
    _, code = _capture_health(samples)
    assert code == 1


def test_health_handler_exit_code_critical() -> None:
    samples = [
        MetricSample("sase_agent_runs_total", {"status": "ok"}, 70.0, "counter"),
        MetricSample("sase_agent_runs_total", {"status": "error"}, 30.0, "counter"),
    ]
    _, code = _capture_health(samples)
    assert code == 2


def test_health_handler_unreachable() -> None:
    """When source is unreachable, exits with code 2."""
    args = Namespace(source="auto", json=False)
    output_parts: list[str] = []
    exit_code = 0
    console = Console(file=None, force_terminal=False, width=120)

    def fake_print(*args: object, **_kw: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    def fake_exit(code: int = 0) -> None:
        nonlocal exit_code
        exit_code = code
        raise SystemExit(code)

    with (
        patch("sase.telemetry.cli_health.Console") as mock_console_cls,
        patch("sase.telemetry.cli_health._resolve_source", return_value=None),
        patch("sase.telemetry.cli_health.sys") as mock_sys,
    ):
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        mock_sys.exit = fake_exit
        try:
            handle_telemetry_health(args)
        except SystemExit:
            pass

    output = "\n".join(output_parts)
    assert "No metric source is reachable" in output
    assert exit_code == 2
    assert exit_code == 2

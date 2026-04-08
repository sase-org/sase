"""Tests for ``sase telemetry status`` CLI subcommand."""

from unittest.mock import patch

from rich.console import Console

from sase.telemetry._config import _TelemetryConfig
from sase.telemetry.cli_status import handle_telemetry_status
from tests.telemetry.conftest import reset_telemetry_config


def setup_function() -> None:
    reset_telemetry_config()


def teardown_function() -> None:
    reset_telemetry_config()


def _capture_status(**config_overrides: object) -> str:
    """Run handle_telemetry_status and capture the Rich console output."""
    cfg = _TelemetryConfig(**config_overrides)  # type: ignore[arg-type]
    console = Console(file=None, force_terminal=False, width=120)
    output_parts: list[str] = []

    def fake_print(*args: object, **kwargs: object) -> None:
        for arg in args:
            if hasattr(arg, "__rich_console__"):
                with console.capture() as capture:
                    console.print(arg)
                output_parts.append(capture.get())
            else:
                output_parts.append(str(arg))

    with (
        patch("sase.telemetry.cli_status.get_telemetry_config", return_value=cfg),
        patch("sase.telemetry.cli_status.Console") as mock_console_cls,
    ):
        mock_console = mock_console_cls.return_value
        mock_console.print = fake_print
        handle_telemetry_status()

    return "\n".join(output_parts)


def test_status_disabled() -> None:
    output = _capture_status(enabled=False)
    assert "disabled" in output.lower()
    assert "sase.yml" in output


def test_status_enabled_shows_metric_count() -> None:
    with patch("sase.telemetry.cli_status._check_reachable", return_value=False):
        output = _capture_status(enabled=True)
    assert "registered" in output
    assert "yes" in output.lower()


def test_status_enabled_shows_connectivity() -> None:
    with patch("sase.telemetry.cli_status._check_reachable", return_value=False):
        output = _capture_status(enabled=True)
    assert "not reachable" in output or "not running" in output


def test_status_reachable_indicators() -> None:
    with patch("sase.telemetry.cli_status._check_reachable", return_value=True):
        output = _capture_status(enabled=True)
    assert "reachable" in output
    assert "running" in output

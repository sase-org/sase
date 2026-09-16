"""Tests for the ``handle_axe_lumberjack_list`` and ``handle_axe_lumberjack_status`` CLI handlers."""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.cli import handle_axe_lumberjack_list, handle_axe_lumberjack_status
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig

pytest_plugins = ("tests._axe_cli_fixtures",)


# --- handle_axe_lumberjack_list Tests ---


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_lumberjack_list_prints_lumberjacks(
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that lumberjack list prints 4 default lumberjacks."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    # 4 routines × (name + description + interval + "jobs:" + 1 job).
    assert len(lines) == 20
    assert "hooks" in output
    assert "checks" in output
    assert "comments" in output
    assert "housekeeping" in output
    assert "interval:" in output
    assert "jobs:" in output


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_lumberjack_list_prints_descriptions(
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each described lumberjack prints its description before its interval."""
    mock_load.return_value = default_axe_config
    with pytest.raises(SystemExit):
        handle_axe_lumberjack_list(argparse.Namespace())

    lines = [
        line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()
    ]
    hooks_index = lines.index("hooks")
    assert lines[hooks_index + 1] == (
        "description: Fast lane that advances hook lifecycle state"
    )
    assert lines[hooks_index + 2].startswith("interval:")
    housekeeping_index = lines.index("housekeeping")
    assert lines[housekeeping_index + 1] == (
        "description: Run hourly housekeeping checks"
    )
    assert lines[housekeeping_index + 2].startswith("interval:")


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_lumberjack_list_prints_only_configured_wait_runners(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_load.return_value = AxeConfig(
        lumberjacks={
            "audits": LumberjackConfig(
                name="audits",
                description="Run audits",
                interval=60,
                wait_runners=0,
            ),
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hooks",
                interval=1,
            ),
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(argparse.Namespace())

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert output.count("wait_runners:") == 1
    assert "wait_runners: 0" in output


@patch("sase.axe.cli.load_axe_config")
@pytest.mark.parametrize("verbose", [False, True])
def test_handle_axe_lumberjack_list_verbose_controls_description_body(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
    verbose: bool,
) -> None:
    body = "Explains the hook lifecycle and stale-work startup path."
    mock_load.return_value = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Advance hook lifecycle state\n\n" + body,
                description_summary="Advance hook lifecycle state",
                description_body=body,
                interval=1,
                chops=[
                    ChopConfig(
                        name="hook_checks",
                        description="Complete hook checks",
                    )
                ],
            )
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(argparse.Namespace(verbose=verbose))

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "description: Advance hook lifecycle state" in output
    assert ("details:" in output) is verbose
    assert (body in output) is verbose


# --- handle_axe_lumberjack_status Tests ---


@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_lumberjack_status", return_value=None)
def test_handle_axe_lumberjack_status_none_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when no lumberjacks are running."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "not running" in output


@patch("sase.axe.cli.is_process_running", return_value=True)
@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_lumberjack_status")
def test_handle_axe_lumberjack_status_with_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    mock_running: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when a lumberjack is running."""
    from sase.axe.state import LumberjackStatus

    mock_load.return_value = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hook status checks",
                interval=1,
                chops=[ChopConfig(name="hook_checks", description="Check hooks")],
            )
        }
    )
    mock_status.return_value = LumberjackStatus(
        name="hooks",
        pid=12345,
        started_at="2026-01-01T00:00:00",
        status="running",
        interval=1,
        chops=["hook_checks"],
        cycles_run=42,
        errors_encountered=0,
        uptime_seconds=100,
    )

    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "hooks" in output
    assert "running" in output
    assert "12345" in output
    assert "42" in output

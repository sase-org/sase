"""Tests for the axe CLI command handlers."""

import argparse
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.cli import (
    handle_axe_chop_list,
    handle_axe_chop_run,
    handle_axe_lumberjack_list,
    handle_axe_lumberjack_status,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.chop_runner import ChopRunOutcome

ALL_12_CHOP_NAMES = sorted(
    [
        "hook_checks",
        "mentor_checks",
        "workflow_checks",
        "pending_checks_poll",
        "comment_zombie_checks",
        "suffix_transforms",
        "orphan_cleanup",
        "stale_running_cleanup",
        "pr_submitted_checks",
        "comment_checks",
        "error_digest",
        "wait_checks",
    ]
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch state directories for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
        patch("sase.axe.state.shared_state_dir", return_value=shared_dir),
    ):
        yield state_dir


@pytest.fixture
def default_axe_config() -> AxeConfig:
    """Return a default AxeConfig with 4 lumberjacks."""
    from sase.axe.config import _parse_lumberjacks

    return AxeConfig(
        lumberjacks=_parse_lumberjacks(
            {
                "hooks": {
                    "interval": 1,
                    "description": "Fast lane that advances hook lifecycle state",
                    "chops": [
                        {"name": "hook_checks", "description": "Check hooks"},
                    ],
                },
                "checks": {
                    "interval": 300,
                    "description": "Poll slower PR-submission checks",
                    "chops": [
                        {
                            "name": "pr_submitted_checks",
                            "description": "Check Patches",
                        },
                    ],
                },
                "comments": {
                    "interval": 60,
                    "description": "Start critique-comment checks for mailed PRs",
                    "chops": [
                        {"name": "comment_checks", "description": "Check comments"},
                    ],
                },
                "housekeeping": {
                    "description": "Run hourly housekeeping checks",
                    "interval": 3600,
                    "chops": [
                        {"name": "error_digest", "description": "Digest errors"},
                    ],
                },
            }
        )
    )


# --- handle_axe_chop_list Tests ---


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_chop_list_renders_configured_chops(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The list view renders one configured-chop row per lumberjack."""
    from sase.axe.config import _parse_lumberjacks

    config = AxeConfig(
        lumberjacks=_parse_lumberjacks(
            {
                "lumberjack1": {
                    "description": "Run first shared-chop checks",
                    "interval": 1,
                    "chops": [
                        {"name": "shared_chop", "description": "From lumberjack1"},
                    ],
                },
                "lumberjack2": {
                    "description": "Run second shared-chop checks",
                    "interval": 60,
                    "chops": [
                        {"name": "shared_chop", "description": "From lumberjack2"},
                    ],
                },
            }
        )
    )
    mock_load.return_value = config
    args = argparse.Namespace(json=False, available=False, verbose=False)
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_chop_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "shared_chop" in output
    assert "Configured Chops" in output


# --- handle_axe_chop_run --lumberjack Tests ---


def _config_with(**chops_per_jack: list[ChopConfig]) -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            name: LumberjackConfig(
                name=name,
                description=f"Run {name} CLI test chops",
                interval=10,
                chops=chops,
            )
            for name, chops in chops_per_jack.items()
        }
    )


def test_handle_axe_chop_run_ambiguous_requires_lumberjack(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A duplicate chop name without --lumberjack exits with a clear error."""
    config = _config_with(
        hooks=[ChopConfig(name="dup", description="")],
        comments=[ChopConfig(name="dup", description="")],
    )
    args = argparse.Namespace(chop_name="dup", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "multiple lumberjacks" in err
    assert "--lumberjack" in err


def test_handle_axe_chop_run_with_lumberjack_disambiguates(
    temp_state_dir: Path,
) -> None:
    """Passing --lumberjack selects the configured chop under that lumberjack."""
    chop = ChopConfig(
        name="dup",
        description="script under comments",
        script="comments_dup",
    )
    config = _config_with(
        hooks=[ChopConfig(name="dup", description="")],
        comments=[chop],
    )
    args = argparse.Namespace(chop_name="dup", lumberjack="comments")

    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch(
            "sase.axe.cli.run_configured_chop_once",
            return_value=ChopRunOutcome(
                lumberjack_name="comments",
                chop_name="dup",
                status="success",
            ),
        ) as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    assert mock_run.call_args.kwargs["lumberjack_name"] == "comments"
    assert mock_run.call_args.kwargs["chop"] is chop


def test_handle_axe_chop_run_passes_debug_flags(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="probe", description="")
    config = _config_with(checks=[chop])
    args = argparse.Namespace(
        chop_name="probe",
        lumberjack="checks",
        dry_run=True,
        chop_verbose=True,
        force=True,
    )

    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch(
            "sase.axe.cli.run_configured_chop_once",
            return_value=ChopRunOutcome(
                lumberjack_name="checks",
                chop_name="probe",
                status="success",
                dry_run=True,
            ),
        ) as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    assert mock_run.call_args.kwargs["dry_run"] is True
    assert mock_run.call_args.kwargs["chop_verbose"] is True
    assert mock_run.call_args.kwargs["force"] is True


def test_handle_axe_chop_run_with_lumberjack_not_configured(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--lumberjack pointing at a chop that doesn't exist there errors out."""
    config = _config_with(
        hooks=[ChopConfig(name="hook_checks", description="")],
    )
    args = argparse.Namespace(chop_name="hook_checks", lumberjack="comments")
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 1
    assert "not configured under lumberjack" in capsys.readouterr().err


def test_handle_axe_chop_run_unknown_chop(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config_with(hooks=[])
    args = argparse.Namespace(chop_name="absent", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.cli.discover_chop_script", return_value=None),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 1
    assert "unknown chop" in capsys.readouterr().err


def test_handle_axe_chop_run_records_run_history_under_lumberjack(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    """A successful CLI run writes the run-history entry under the configured lumberjack."""
    from sase.axe.state import read_chop_run_index

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "hook_checks"
    script.write_text("#!/bin/sh\necho hello\n")
    import stat as _stat

    script.chmod(script.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)

    chop = ChopConfig(name="hook_checks", description="")
    config = AxeConfig(
        chop_script_dirs=[str(scripts_dir)],
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hook CLI test chops",
                interval=10,
                chops=[chop],
            ),
        },
    )
    args = argparse.Namespace(chop_name="hook_checks", lumberjack="hooks")
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    index = read_chop_run_index("hooks", "hook_checks")
    assert len(index) == 1


def test_handle_axe_chop_run_unconfigured_script_uses_oneshot(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    """A discoverable but unconfigured script still runs under ``_oneshot``."""
    from sase.axe.state import read_chop_run_index

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "freestanding"
    script.write_text("#!/bin/sh\ntrue\n")
    import stat as _stat

    script.chmod(script.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)

    config = AxeConfig(chop_script_dirs=[str(scripts_dir)])
    args = argparse.Namespace(chop_name="freestanding", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    assert read_chop_run_index("_oneshot", "freestanding")


def test_handle_axe_chop_run_already_running_skips(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When a chop is already running, the CLI notifies and exits nonzero."""
    from datetime import datetime

    from sase.axe.state import ChopRunEntry, start_chop_run

    chop = ChopConfig(name="hook_checks", description="")
    config = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hook CLI test chops",
                interval=10,
                chops=[chop],
            ),
        }
    )

    live_entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="hooks",
        chop_name="hook_checks",
        started_at=datetime.now().isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(live_entry)

    args = argparse.Namespace(chop_name="hook_checks", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 1
    assert "already running" in capsys.readouterr().err
    mock_stream.assert_not_called()


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
    # 4 lumberjacks × (name + description + interval + "chops:" + 1 chop).
    assert len(lines) == 20
    assert "hooks" in output
    assert "checks" in output
    assert "comments" in output
    assert "housekeeping" in output
    assert "interval:" in output
    assert "chops:" in output


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

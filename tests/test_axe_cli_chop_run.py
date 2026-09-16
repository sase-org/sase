"""Tests for the ``handle_axe_chop_run`` CLI command handler."""

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.chop_runner import ChopRunOutcome
from sase.axe.cli import handle_axe_chop_run
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig

pytest_plugins = ("tests._axe_cli_fixtures",)


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
    config = AxeConfig(
        lumberjacks={
            "lumberjack_hooks": LumberjackConfig(
                name="lumberjack_hooks",
                description="Run hook CLI test chops",
                interval=10,
                chops=[ChopConfig(name="chop-test", description="")],
            ),
            "comments": LumberjackConfig(
                name="comments",
                description="Run comment CLI test chops",
                interval=10,
                chops=[ChopConfig(name="chop-test", description="")],
            ),
        }
    )
    args = argparse.Namespace(chop_name="chop-test", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "multiple routines" in err
    assert "--routine" in err
    assert "job 'chop-test'" in err
    assert "lumberjack_hooks" in err
    assert "job-test" not in err
    assert "routine_hooks" not in err


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
    assert "not configured under routine" in capsys.readouterr().err


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
    assert "unknown job" in capsys.readouterr().err


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

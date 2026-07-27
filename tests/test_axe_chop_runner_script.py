"""Tests for running script-backed chops through the shared runner."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import (
    ChopRunEntry,
    ChopRunSource,
    chop_run_context_path,
    read_chop_run,
    read_chop_run_index,
    read_chop_run_log_tail,
    start_chop_run,
)

from tests.axe_chop_runner_helpers import (
    make_script,
    started_at_seconds_ago,
)

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_run_configured_chop_once_records_manual_source(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "live_chop", "echo hello\n")
    cfg = AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
        chop_script_dirs=[str(tmp_path / "scripts")],
    )
    chop = ChopConfig(name="live_chop", description="")

    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=cfg,
            source="manual",
            started_by="ace",
        )

    assert outcome.status == "success"
    assert outcome.exit_code == 0
    assert outcome.run_id is not None

    entry = read_chop_run("hooks", "live_chop", outcome.run_id)
    assert entry is not None
    assert entry.status == "success"
    assert entry.source == "manual"
    assert entry.started_by == "ace"

    tail = read_chop_run_log_tail("hooks", "live_chop", outcome.run_id)
    assert "hello" in tail


def test_run_configured_chop_once_resolves_explicit_full_script_name(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "actual_executable", "echo exact\n")
    cfg = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])
    chop = ChopConfig(
        name="friendly_name",
        description="",
        script="actual_executable",
    )

    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=cfg,
            source="manual",
        )

    assert outcome.status == "success"
    assert outcome.run_id is not None
    assert "exact" in read_chop_run_log_tail("hooks", "friendly_name", outcome.run_id)


def test_run_configured_chop_once_uses_per_chop_timeout(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    """Per-chop timeout overrides the lumberjack-level default."""
    make_script(tmp_path, "noop_chop", "true\n")
    cfg = AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
        chop_script_dirs=[str(tmp_path / "scripts")],
    )
    chop = ChopConfig(name="noop_chop", description="", timeout=7)

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0, pid=1234, output_bytes=0, timed_out=False
        )
        run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=cfg,
            chop_timeout_default=999,
            source="manual",
        )

    assert mock_stream.call_args.kwargs["timeout"] == 7


def test_run_configured_chop_once_falls_back_to_default_timeout(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "noop_chop", "true\n")
    cfg = AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
        chop_script_dirs=[str(tmp_path / "scripts")],
    )
    chop = ChopConfig(name="noop_chop", description="")

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0, pid=1234, output_bytes=0, timed_out=False
        )
        run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=cfg,
            chop_timeout_default=42,
            source="manual",
        )

    assert mock_stream.call_args.kwargs["timeout"] == 42


def test_run_configured_chop_once_propagates_chop_env(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "env_chop", "true\n")
    cfg = AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
        chop_script_dirs=[str(tmp_path / "scripts")],
    )
    chop = ChopConfig(name="env_chop", description="", env={"MY_VAR": "abc"})

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0, pid=1234, output_bytes=0, timed_out=False
        )
        run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=cfg,
            source="manual",
        )

    env = mock_stream.call_args.kwargs["env"]
    assert env["MY_VAR"] == "abc"
    # Chop identity env is also injected for downstream agent records.
    assert env["SASE_CHOP_LUMBERJACK"] == "hooks"
    assert env["SASE_CHOP_NAME"] == "env_chop"


@pytest.mark.parametrize(
    ("source", "dry_run", "dry_run_env"),
    [
        ("scheduled", False, "0"),
        ("manual", True, "1"),
        ("oneshot", False, "0"),
    ],
)
def test_run_configured_chop_once_exports_source_and_dry_run(
    temp_state_dir: Path,
    tmp_path: Path,
    source: ChopRunSource,
    dry_run: bool,
    dry_run_env: str,
) -> None:
    make_script(tmp_path, "env_chop", "true\n")
    cfg = AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])
    chop = ChopConfig(name="env_chop", description="")

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0, pid=1234, output_bytes=0, timed_out=False
        )
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=cfg,
            source=source,
            dry_run=dry_run,
        )

    assert outcome.status == "success"
    assert outcome.run_id is not None
    env = mock_stream.call_args.kwargs["env"]
    assert env["SASE_CHOP_SOURCE"] == source
    assert env["SASE_CHOP_DRY_RUN"] == dry_run_env

    context = json.loads(
        chop_run_context_path("hooks", "env_chop", outcome.run_id).read_text(
            encoding="utf-8"
        )
    )
    assert context["source"] == source
    assert context["dry_run"] is dry_run


def test_run_configured_chop_once_resolves_secrets_and_exports_target_env(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "env_chop", "true\n")
    chop = ChopConfig(
        name="env_chop[sase]",
        base_name="env_chop",
        description="",
        script="env_chop",
        env={"TOKEN": {"env": "SOURCE_TOKEN"}},
        target_key="sase",
        target={"name": "sase", "priority": 2},
    )

    with (
        patch.dict("os.environ", {"SOURCE_TOKEN": "resolved"}),
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0,
            pid=1234,
            output_bytes=0,
            timed_out=False,
        )
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
        )

    assert outcome.status == "success"
    env = mock_stream.call_args.kwargs["env"]
    assert env["TOKEN"] == "resolved"
    assert env["SASE_CHOP_TARGET_KEY"] == "sase"
    assert env["SASE_CHOP_TARGET_NAME"] == "sase"
    assert env["SASE_CHOP_TARGET_PRIORITY"] == "2"


def test_run_configured_chop_once_records_unresolved_secret_as_check_error(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "secret_chop", "true\n")

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(
                name="secret_chop",
                description="",
                env={"TOKEN": {"env": "MISSING_TOKEN"}},
            ),
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
        )

    assert outcome.status == "check_error"
    assert outcome.reason is not None
    assert "MISSING_TOKEN" in outcome.reason


def test_run_configured_chop_once_missing_script(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    chop = ChopConfig(name="absent_chop", description="")
    with patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "missing_script"
    assert outcome.run_id is not None
    entry = read_chop_run("hooks", "absent_chop", outcome.run_id)
    assert entry is not None
    assert entry.status == "missing_script"


def test_run_configured_chop_once_dedupes_live_script_run(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A still-running script chop returns ``already_running`` instead of relaunching."""
    live_entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="hooks",
        chop_name="hook_checks",
        started_at=started_at_seconds_ago(0),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(live_entry)

    chop = ChopConfig(name="hook_checks", description="")
    with patch("sase.axe.chop_runner.stream_chop_script") as mock_stream:
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "already_running"
    assert outcome.run_id == live_entry.run_id
    mock_stream.assert_not_called()


def test_run_configured_chop_once_recovers_old_pidless_script_run(
    temp_state_dir: Path,
    axe_config: AxeConfig,
    tmp_path: Path,
) -> None:
    old_entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="hooks",
        chop_name="hook_checks",
        started_at=started_at_seconds_ago(120),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(old_entry)

    chop = ChopConfig(name="hook_checks", description="")
    with (
        patch(
            "sase.axe.chop_runner.discover_chop_script",
            return_value=Path("/fake/script"),
        ),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0, pid=1234, output_bytes=0, timed_out=False
        )
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=axe_config,
            chop_timeout_default=90,
            context_file=str(tmp_path / "context.json"),
            source="manual",
        )

    assert outcome.status == "success"
    assert outcome.run_id is not None
    assert outcome.run_id != old_entry.run_id
    mock_stream.assert_called_once()

    old_finalized = read_chop_run("hooks", "hook_checks", old_entry.run_id)
    assert old_finalized is not None
    assert old_finalized.status == "failure"
    assert old_finalized.error == (
        "stale running chop never recorded a pid after 90s grace window"
    )

    index = read_chop_run_index("hooks", "hook_checks")
    assert index[0] == outcome.run_id
    assert old_entry.run_id in index[1:]


def test_run_configured_chop_once_records_failure_with_exit_code(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    chop = ChopConfig(name="bad_chop", description="")
    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.chop_runner.discover_chop_script",
            return_value=Path("/fake/script"),
        ),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=2, pid=1234, output_bytes=4, timed_out=False
        )
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=axe_config,
            source="oneshot",
        )

    assert outcome.status == "failure"
    assert outcome.exit_code == 2
    assert outcome.error is not None and "exit code 2" in str(outcome.error)


def test_run_configured_chop_once_reuses_passed_context_file(
    temp_state_dir: Path,
    axe_config: AxeConfig,
    tmp_path: Path,
) -> None:
    """When ``context_file`` is supplied the runner does not rebuild context."""
    chop = ChopConfig(name="hook_checks", description="")
    fake_ctx = str(tmp_path / "fake_context.json")

    with (
        patch("sase.axe.chop_runner.find_all_changespecs") as mock_find,
        patch(
            "sase.axe.chop_runner.discover_chop_script",
            return_value=Path("/fake/script"),
        ),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0, pid=1234, output_bytes=0, timed_out=False
        )
        run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=axe_config,
            context_file=fake_ctx,
            source="scheduled",
        )

    mock_find.assert_not_called()
    assert mock_stream.call_args.args[1] == fake_ctx


def test_run_configured_chop_once_indexes_history_newest_first(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    chop = ChopConfig(name="hook_checks", description="")
    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.chop_runner.discover_chop_script",
            return_value=Path("/fake/script"),
        ),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
    ):
        from sase.axe.chop_script_runner import _StreamedScriptResult

        mock_stream.return_value = _StreamedScriptResult(
            returncode=0, pid=1234, output_bytes=0, timed_out=False
        )
        outcome = run_configured_chop_once(
            lumberjack_name="hooks",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    index = read_chop_run_index("hooks", "hook_checks")
    assert outcome.run_id is not None
    assert index[0] == outcome.run_id

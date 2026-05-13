"""Tests for the shared chop runner service used by the scheduler, CLI, and TUI."""

import stat
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launcher import AgentLaunchResult
from sase.axe.chop_runner import (
    AmbiguousChopError,
    ChopNotFoundError,
    _active_script_chop_run,
    find_configured_chop,
    run_configured_chop_once,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.state import (
    ChopRunEntry,
    read_chop_run,
    read_chop_run_index,
    read_chop_run_log_tail,
    start_chop_run,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", lumberjack_dir),
    ):
        yield state_dir


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
    )


def _make_script(tmp: Path, name: str, body: str) -> Path:
    scripts = tmp / "scripts"
    scripts.mkdir(exist_ok=True)
    script = scripts / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


# --- find_configured_chop ---


def _config_with(**chops_per_jack: list[ChopConfig]) -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            name: LumberjackConfig(name=name, interval=10, chops=chops)
            for name, chops in chops_per_jack.items()
        }
    )


def test_find_configured_chop_unique() -> None:
    chop = ChopConfig(name="hook_checks", description="")
    config = _config_with(hooks=[chop])
    match = find_configured_chop(config, "hook_checks")
    assert match.lumberjack_name == "hooks"
    assert match.chop is chop


def test_find_configured_chop_missing_raises() -> None:
    config = _config_with(hooks=[ChopConfig(name="other", description="")])
    with pytest.raises(ChopNotFoundError):
        find_configured_chop(config, "missing")


def test_find_configured_chop_ambiguous_without_lumberjack_raises() -> None:
    config = _config_with(
        hooks=[ChopConfig(name="dup", description="")],
        comments=[ChopConfig(name="dup", description="")],
    )
    with pytest.raises(AmbiguousChopError) as exc_info:
        find_configured_chop(config, "dup")
    assert exc_info.value.candidates == ["comments", "hooks"]


def test_find_configured_chop_ambiguous_with_lumberjack_succeeds() -> None:
    chop_h = ChopConfig(name="dup", description="from hooks")
    chop_c = ChopConfig(name="dup", description="from comments")
    config = _config_with(hooks=[chop_h], comments=[chop_c])
    match = find_configured_chop(config, "dup", lumberjack_name="comments")
    assert match.lumberjack_name == "comments"
    assert match.chop is chop_c


def test_find_configured_chop_lumberjack_filter_misses_raises() -> None:
    chop = ChopConfig(name="hook_checks", description="")
    config = _config_with(hooks=[chop])
    with pytest.raises(ChopNotFoundError):
        find_configured_chop(config, "hook_checks", lumberjack_name="comments")


# --- active_script_chop_run ---


def test_active_script_chop_run_returns_none_when_no_history(
    temp_state_dir: Path,
) -> None:
    assert _active_script_chop_run("lj", "chop") is None


def test_active_script_chop_run_finds_running_entry(temp_state_dir: Path) -> None:
    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)

    live = _active_script_chop_run("lj", "chop")
    assert live is not None
    assert live.run_id == entry.run_id


def test_active_script_chop_run_keeps_running_entry_with_live_pid(
    temp_state_dir: Path,
) -> None:
    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
        pid=12345,
    )
    start_chop_run(entry)

    with patch("sase.axe.chop_runner.is_process_running", return_value=True):
        live = _active_script_chop_run("lj", "chop")

    assert live is not None
    assert live.run_id == entry.run_id


def test_active_script_chop_run_finalizes_dead_pid_and_returns_none(
    temp_state_dir: Path,
) -> None:
    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
        pid=12345,
    )
    start_chop_run(entry)

    with patch("sase.axe.chop_runner.is_process_running", return_value=False):
        assert _active_script_chop_run("lj", "chop") is None

    finalized = read_chop_run("lj", "chop", entry.run_id)
    assert finalized is not None
    assert finalized.status == "failure"
    assert finalized.finished_at is not None
    assert finalized.error == "stale running chop process exited: pid 12345"


def test_active_script_chop_run_keeps_pidless_running_entry_conservatively(
    temp_state_dir: Path,
) -> None:
    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)

    with patch("sase.axe.chop_runner.is_process_running") as mock_running:
        live = _active_script_chop_run("lj", "chop")

    assert live is not None
    assert live.run_id == entry.run_id
    mock_running.assert_not_called()


def test_active_script_chop_run_returns_none_when_newest_finalized(
    temp_state_dir: Path,
) -> None:
    """A finalized newest entry means no live run, even if older entries exist."""
    from sase.axe.state import finish_chop_run

    started_at = datetime(2026, 1, 1, 12, 0, 0)
    entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="lj",
        chop_name="chop",
        started_at=started_at.isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)
    finish_chop_run(
        "lj",
        "chop",
        entry.run_id,
        status="success",
        finished_at=datetime(2026, 1, 1, 12, 0, 1).isoformat(),
        duration_ms=1000,
        exit_code=0,
    )

    assert _active_script_chop_run("lj", "chop") is None


# --- run_configured_chop_once: script chop ---


def test_run_configured_chop_once_records_manual_source(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _make_script(tmp_path, "live_chop", "echo hello\n")
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


def test_run_configured_chop_once_uses_per_chop_timeout(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    """Per-chop timeout overrides the lumberjack-level default."""
    _make_script(tmp_path, "noop_chop", "true\n")
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
        from sase.axe.chop_script_runner import StreamedScriptResult

        mock_stream.return_value = StreamedScriptResult(
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
    _make_script(tmp_path, "noop_chop", "true\n")
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
        from sase.axe.chop_script_runner import StreamedScriptResult

        mock_stream.return_value = StreamedScriptResult(
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
    _make_script(tmp_path, "env_chop", "true\n")
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
        from sase.axe.chop_script_runner import StreamedScriptResult

        mock_stream.return_value = StreamedScriptResult(
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
    started_at = datetime(2026, 1, 1, 12, 0, 0)
    live_entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="hooks",
        chop_name="hook_checks",
        started_at=started_at.isoformat(),
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
        from sase.axe.chop_script_runner import StreamedScriptResult

        mock_stream.return_value = StreamedScriptResult(
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


# --- run_configured_chop_once: agent chop ---


def test_run_configured_chop_once_launches_agent_with_chop_env(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    chop = ChopConfig(name="my_agent", description="", agent="some prompt")

    launch_result = AgentLaunchResult(
        pid=4242,
        workspace_num=7,
        workspace_dir="/tmp/ws7",
        output_path="/tmp/out",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )
    with patch(
        "sase.agent.launcher.launch_agent_from_cwd", return_value=launch_result
    ) as mock_launch:
        outcome = run_configured_chop_once(
            lumberjack_name="agentj",
            chop=chop,
            axe_config=axe_config,
            source="manual",
            started_by="ace",
        )

    assert outcome.status == "agent_launched"
    assert outcome.agent_pid == 4242
    assert outcome.run_id is not None

    extra_env = mock_launch.call_args.kwargs["extra_env"]
    assert extra_env["SASE_CHOP_LUMBERJACK"] == "agentj"
    assert extra_env["SASE_CHOP_NAME"] == "my_agent"
    assert extra_env["SASE_CHOP_RUN_ID"]
    assert extra_env["SASE_CHOP_PROMPT_HASH"]

    entry = read_chop_run("agentj", "my_agent", outcome.run_id)
    assert entry is not None
    assert entry.status == "agent_launched"
    assert entry.agent_pid == 4242
    assert entry.source == "manual"
    assert entry.started_by == "ace"

    tail = read_chop_run_log_tail("agentj", "my_agent", outcome.run_id)
    assert "Launched agent chop 'my_agent' (PID 4242)" in tail
    assert "chop=my_agent lumberjack=agentj source=manual started_by=ace" in tail
    assert f"prompt_hash={extra_env['SASE_CHOP_PROMPT_HASH']}" in tail
    assert "agent_pid=4242 workspace=7 workspace_dir=/tmp/ws7 output=/tmp/out" in tail
    assert "project=proj workflow=ace(run)-260101_120000 cl=proj" in tail
    assert "prompt_preview='some prompt'" in tail


def test_run_configured_chop_once_dedupes_live_agent(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """A live registry record blocks a duplicate manual launch."""
    from sase.axe.chop_agents import _record_chop_agent_launch

    chop = ChopConfig(name="my_agent", description="", agent="some prompt")
    _record_chop_agent_launch(
        lumberjack_name="agentj",
        chop_name="my_agent",
        run_id="prev",
        pid=99999,
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workspace_num=1,
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
        prompt="some prompt",
    )

    with (
        patch("sase.axe.chop_agents.is_process_running", return_value=True),
        patch("sase.agent.launcher.launch_agent_from_cwd") as mock_launch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="agentj",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "already_running"
    assert outcome.agent_pid == 99999
    mock_launch.assert_not_called()


def test_run_configured_chop_once_agent_launch_failure(
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    chop = ChopConfig(name="my_agent", description="", agent="some prompt")
    with patch(
        "sase.agent.launcher.launch_agent_from_cwd",
        side_effect=RuntimeError("workspace plugin missing"),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="agentj",
            chop=chop,
            axe_config=axe_config,
            source="manual",
        )

    assert outcome.status == "agent_failed"
    assert outcome.error is not None and "workspace plugin" in str(outcome.error)
    assert outcome.run_id is not None
    entry = read_chop_run("agentj", "my_agent", outcome.run_id)
    assert entry is not None
    assert entry.status == "failure"


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
        from sase.axe.chop_script_runner import StreamedScriptResult

        mock_stream.return_value = StreamedScriptResult(
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
        from sase.axe.chop_script_runner import StreamedScriptResult

        mock_stream.return_value = StreamedScriptResult(
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

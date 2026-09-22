"""Phase ownership-roots: agents are ownership roots with a trusted marker."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list
from sase.tool.argv import ResolvedToolArgv
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.executor_process import child_env
from sase.tool.ownership import ToolRunOwnership, resolve_ownership


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_NAME",
        "SASE_TOOL_PROJECT_ROOT",
        "SASE_TOOL_RUN_AGENT",
        "SASE_TOOL_RUN_EVENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _named_resolved() -> ResolvedToolArgv:
    return ResolvedToolArgv(
        tool_name="check",
        argv=("true",),
        extra_args=(),
        display_argv=("true",),
        private_argv=None,
        definition={},
        digest=None,
        cwd="/repo/root",
        adhoc=False,
    )


def _adhoc_resolved() -> ResolvedToolArgv:
    return ResolvedToolArgv(
        tool_name=None,
        argv=("sh", "-c", "true"),
        extra_args=(),
        display_argv=("sh", "-c", "true"),
        private_argv=None,
        definition={},
        digest=None,
        cwd=None,
        adhoc=True,
    )


def test_agent_ignores_live_monitor_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    # No artifacts dir: the monitor id is live, not settled.
    monkeypatch.setenv("SASE_MONITOR_ID", "epic-launch-monitor")
    assert resolve_ownership(quiet=False).owner_kind == "monitor"

    monkeypatch.setenv("SASE_AGENT", "1")
    ownership = resolve_ownership(quiet=False)
    assert (ownership.owner_kind, ownership.owner_id) == (None, None)
    assert ownership.owns_output is True


def test_agent_ignores_running_proc_and_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool import ownership

    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-live")
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-inherited")
    monkeypatch.setattr(
        "sase.procs.store.get_proc",
        lambda proc_id: SimpleNamespace(status="running"),
    )
    monkeypatch.setattr(ownership, "_parent_exists", lambda run_id: True)

    assert resolve_ownership(quiet=False).owner_kind == "proc"

    monkeypatch.setenv("SASE_AGENT", "1")
    resolved = resolve_ownership(quiet=False)
    assert resolved.owner_kind is None
    assert resolved.parent_run_id is None
    assert resolved.owns_output is True


def test_child_env_exports_marker_when_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    env = child_env(
        recorded=True,
        run_id="run-1",
        events_path=tmp_path / "events.jsonl",
        resolved=_named_resolved(),
    )
    assert env["SASE_TOOL_NAME"] == "check"
    assert env["SASE_TOOL_PROJECT_ROOT"] == "/repo/root"
    assert env["SASE_TOOL_RUN_ID"] == "run-1"


def test_child_env_exports_marker_when_unrecorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "stale-parent")
    env = child_env(
        recorded=False, run_id=None, events_path=None, resolved=_named_resolved()
    )
    assert env["SASE_TOOL_NAME"] == "check"
    assert env["SASE_TOOL_PROJECT_ROOT"] == "/repo/root"
    assert "SASE_TOOL_RUN_ID" not in env
    assert "SASE_TOOL_RUN_EVENTS" not in env


def test_child_env_exports_adhoc_with_empty_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    env = child_env(
        recorded=True,
        run_id="run-adhoc",
        events_path=None,
        resolved=_adhoc_resolved(),
    )
    assert env["SASE_TOOL_NAME"] == "ad-hoc"
    assert env["SASE_TOOL_PROJECT_ROOT"] == ""


def test_begin_tool_run_falls_back_to_starter_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool import executor_recording

    _home(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_begin(request: dict[str, object]) -> dict[str, object]:
        captured.update(request)
        return {"run": {"state": "running", "run_id": request["run_id"]}}

    monkeypatch.setattr(executor_recording, "tool_run_begin", fake_begin)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.setenv("SASE_TOOL_RUN_AGENT", "starter.agent")
    ownership = ToolRunOwnership(
        owner_kind="monitor",
        owner_id="mon-1",
        parent_run_id=None,
        other_owner_kind=None,
        other_owner_id=None,
        owns_output=False,
        enclosing_label="monitor mon-1",
    )
    assert (
        executor_recording.begin_tool_run(
            "run-1",
            resolved=_named_resolved(),
            ownership=ownership,
            events_path=None,
            stdout_path=None,
            stderr_path=None,
        )
        is True
    )
    assert captured["agent"] == "starter.agent"


def test_begin_tool_run_prefers_agent_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool import executor_recording

    _home(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_begin(request: dict[str, object]) -> dict[str, object]:
        captured.update(request)
        return {"run": {"state": "running", "run_id": request["run_id"]}}

    monkeypatch.setattr(executor_recording, "tool_run_begin", fake_begin)
    monkeypatch.setenv("SASE_AGENT_NAME", "direct.agent")
    monkeypatch.setenv("SASE_TOOL_RUN_AGENT", "starter.agent")
    ownership = ToolRunOwnership(
        owner_kind=None,
        owner_id=None,
        parent_run_id=None,
        other_owner_kind=None,
        other_owner_id=None,
        owns_output=True,
        enclosing_label=None,
    )
    assert (
        executor_recording.begin_tool_run(
            "run-2",
            resolved=_named_resolved(),
            ownership=ownership,
            events_path=None,
            stdout_path=None,
            stderr_path=None,
        )
        is True
    )
    assert captured["agent"] == "direct.agent"


def test_tool_run_agent_overlay() -> None:
    from sase.monitor.start import _tool_run_agent_overlay

    assert _tool_run_agent_overlay("starter.agent") == {
        "SASE_TOOL_RUN_AGENT": "starter.agent"
    }
    assert _tool_run_agent_overlay(None) == {}
    assert _tool_run_agent_overlay("  ") == {}


def test_phase_agent_run_is_compact_with_replayable_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Live sase-16c evidence: an inherited live monitor id no longer captures.

    A phase agent whose env still carries the epic-launch monitor id gets
    compact output again, and the retained logs replay.
    """
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_MONITOR_ID", "epic-launch-monitor")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-agent")
    code = execute_tool_run(
        ToolRunCliRequest(
            quiet=False,
            verbose=False,
            tail_lines=200,
            words=("--", "sh", "-c", "printf out; exit 0"),
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    run = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    assert run.get("owner_kind") is None
    assert run.get("agent") == "phase-agent"
    assert Path(run["logs"]["stdout_path"]).read_bytes() == b"out"

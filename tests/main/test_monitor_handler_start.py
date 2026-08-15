"""Behavior tests for the ``sase monitor start`` handler."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from sase.running_field import WorkspaceClaim
from tests.main.monitor_handler_helpers import dispatch, make_monitor, monitor_home
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)

__all__ = ["monitor_home"]


def _pin_project(monkeypatch: pytest.MonkeyPatch, project: str = "proj") -> None:
    monkeypatch.setattr(
        "sase.main.monitor_handler._infer_project_name", lambda _cwd: project
    )


def test_start_reaches_the_handler_through_the_real_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real ``sase monitor start`` invocation dispatches through ``entry.main()``.

    ``-c/--command``'s default dest is ``command``, which collides with the
    root parser's ``dest="command"`` used for top-level routing -- calling
    the handler directly (as ``dispatch()`` does) can't catch that, since it
    skips ``entry.py``'s ``if args.command == "monitor":`` check entirely.
    """
    from sase.main import entry

    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "monitor", "start", "-c", "true", "-r", "verify", "-t", "30s"],
    )

    with pytest.raises(SystemExit) as exit_info:
        entry.main()

    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "Unknown command" not in err
    assert "SASE_AGENT_NAME is unset" in err


def test_start_requires_a_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An omitted command remainder is a usage error."""
    assert dispatch(["monitor", "start", "-a", "acme"]) == 2
    assert "command is required" in capsys.readouterr().err


def test_start_requires_agent_when_none_is_given_or_inferable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No ``-a/--agent`` and no ``SASE_AGENT_NAME`` is a usage error."""
    assert (
        dispatch(["monitor", "start", "-c", "true", "-r", "verify", "-t", "30s"]) == 2
    )
    assert "SASE_AGENT_NAME is unset" in capsys.readouterr().err


def test_start_rejects_an_empty_reason(capsys: pytest.CaptureFixture[str]) -> None:
    """An empty ``-r/--reason`` is rejected before touching the engine."""
    assert (
        dispatch(
            ["monitor", "start", "-c", "true", "-r", "  ", "-t", "30s", "-a", "acme"]
        )
        == 2
    )
    assert "-r/--reason must not be empty" in capsys.readouterr().err


def test_start_rejects_an_invalid_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    """A malformed ``-t/--timeout`` is rejected with a helpful message."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "banana",
                "-a",
                "acme",
            ]
        )
        == 2
    )
    assert "invalid -t/--timeout value" in capsys.readouterr().err


def test_start_rejects_an_invalid_idle_timeout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed ``-i/--idle-timeout`` is rejected with a helpful message."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-i",
                "banana",
                "-a",
                "acme",
            ]
        )
        == 2
    )
    assert "invalid -i/--idle-timeout value" in capsys.readouterr().err


def test_start_rejects_an_oversized_status_label(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A status label over 48 characters is rejected."""
    long_label = "x" * 49
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-a",
                "acme",
                "-s",
                long_label,
            ]
        )
        == 2
    )
    assert "-s/--start-status must be at most 48 characters" in capsys.readouterr().err


def test_start_already_running_monitor_with_a_different_command_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A lane with an active monitor for a different command refuses to start."""
    existing = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="existing1111",
        command="just check",
    )
    patch_project_records(monkeypatch, [existing])
    _pin_project(monkeypatch)

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "just check-full",
            "-r",
            "verify",
            "-t",
            "30s",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
        ]
    )

    assert exit_code == 1
    assert "already has an active monitor" in capsys.readouterr().err


def test_start_launches_a_real_monitor_and_reports_the_resolved_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A successful start prints the id, member, resolved timeout, and pointer."""
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    _pin_project(monkeypatch)

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify the fix",
            "-t",
            "45m",
            "-i",
            "10m",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Started monitor" in out
    assert "member: acme--mon" in out
    assert "45m (2700s)" in out
    assert "idle timeout: 10m (600s)" in out
    assert "sase monitor show" in out


def test_start_lane_flag_is_a_deprecated_alias_for_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--lane`` still targets the same agent as ``-a/--agent``."""
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    _pin_project(monkeypatch)

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify the fix",
            "-t",
            "45m",
            "--lane",
            "acme",
            "-C",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Started monitor" in out
    assert "member: acme--mon" in out


def test_start_prints_the_summary_before_the_agent_runner_handoff_kill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``kill_agent_runner_group`` never returns, so output must precede it.

    Regression test for a bug where every line printed after the handoff
    call -- including the whole non-JSON summary and the ``--json``
    envelope -- was unreachable inside a real agent process.
    """
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    _pin_project(monkeypatch)

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)

    killed: list[str] = []

    def fake_kill(artifacts_dir: str) -> int:
        killed.append(artifacts_dir)
        raise SystemExit(0)

    monkeypatch.setattr("sase.main.utils.kill_agent_runner_group", fake_kill)

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify",
            "-t",
            "30s",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert killed == [starter_dir]
    out = capsys.readouterr().out
    assert "Started monitor" in out
    assert "member: acme--mon" in out
    assert "This is the last output before the agent runner is killed" in out


def test_start_json_envelope_reports_handed_off_before_the_kill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``--json`` envelope's ``handed_off`` flag prints before the kill too."""
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    _pin_project(monkeypatch)

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)
    monkeypatch.setattr(
        "sase.main.utils.kill_agent_runner_group",
        lambda _artifacts_dir: (_ for _ in ()).throw(SystemExit(0)),
    )

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify",
            "-t",
            "30s",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["handed_off"] is True


def test_start_json_envelope_is_stable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--json`` emits the monitor projection plus a handed-off flag."""
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    _pin_project(monkeypatch)

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify",
            "-t",
            "30",
            "-i",
            "5s",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["handed_off"] is False
    assert payload["monitor"]["lane"] == "acme"
    assert payload["monitor"]["command"] == "true"
    assert payload["monitor"]["timeout_seconds"] == 30.0
    assert payload["monitor"]["idle_timeout_seconds"] == 5.0

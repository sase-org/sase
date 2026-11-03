"""Launch validation and command behavior tests for ``sase monitor start``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.running_field import WorkspaceClaim
from tests.main.monitor_handler_helpers import dispatch, make_monitor, pin_project
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)


def test_start_truncates_an_overlength_status_label(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Over-length labels are accepted, clamped to 20 chars, and warned on stderr."""
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
    pin_project(monkeypatch)
    overflow = "VERIFYING THE WHOLE SUITE NOW"

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
            "-s",
            overflow,
            "-S",
            "TESTED",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "-s/--start-status truncated to 20 chars" in captured.err
    assert "VERIFYING THE WHOLE…" in captured.err
    payload = json.loads(captured.out)
    assert payload["monitor"]["start_status"] == "VERIFYING THE WHOLE…"
    assert len(payload["monitor"]["start_status"]) == 20
    meta = json.loads(
        Path(payload["monitor"]["artifacts_dir"], "agent_meta.json").read_text()
    )
    assert meta["monitor_start_status"] == "VERIFYING THE WHOLE…"


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
    pin_project(monkeypatch)

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
            "-s",
            "TESTING",
            "-S",
            "TESTED",
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
    pin_project(monkeypatch)

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
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Started monitor" in out
    assert "member: acme--mon" in out
    assert "45m (2700s)" in out
    assert "idle timeout: 10m (600s)" in out
    assert "sase monitor show" in out


def test_start_preserves_inner_quoting_of_a_bash_c_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stored `monitor_command` for a `bash -c '...'` remainder round-trips.

    Regression test for the sase-11o.1 incident: `bash -c 'just install &&
    just check'` must not collapse into `bash -c just install && just
    check`, which silently drops `just install` from the monitored command.
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
    pin_project(monkeypatch)

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-r",
            "verify",
            "-t",
            "30s",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
            "-s",
            "TESTING",
            "-S",
            "TESTED",
            "--json",
            "--",
            "bash",
            "-c",
            "just install && just check",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "warning -- command starts with `bash -c`" in captured.err
    payload = json.loads(captured.out)
    assert payload["monitor"]["command"] == "bash -c 'just install && just check'"


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
    pin_project(monkeypatch)

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
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Started monitor" in out
    assert "member: acme--mon" in out

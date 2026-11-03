"""Launch and output tests for the ``sase monitor start`` handler."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.running_field import WorkspaceClaim
from tests.main.monitor_handler_helpers import (
    dispatch,
    make_monitor,
    monitor_home,
    pin_project,
)
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)

__all__ = ["monitor_home"]


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


def test_start_in_an_agent_reports_staged_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """In-agent starts stage and return; the supervisor launches after the turn."""
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

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)

    from types import SimpleNamespace

    from sase.main.monitor import start as start_handler

    staged_calls: list[object] = []

    def fake_stage(request: object) -> SimpleNamespace:
        staged_calls.append(request)
        return SimpleNamespace(
            record=SimpleNamespace(
                monitor_id="m" * 40,
                member_agent_name="acme--mon",
                tool_run_id=None,
                tool_run_joined=False,
            ),
            staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            payload={},
            replayed=False,
        )

    monkeypatch.setattr("sase.monitor.start_stage.stage_monitor", fake_stage)
    monkeypatch.setattr(
        start_handler,
        "start_monitor",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not spawn on staged path")
        ),
    )

    exit_code = dispatch(_agent_handoff_start_argv(tmp_path))

    assert exit_code == 0
    assert len(staged_calls) == 1
    out = capsys.readouterr().out
    assert out.startswith("Staged monitor")
    assert "Nothing starts until this turn ends" in out
    assert "/sase_final" in out
    assert "Started monitor" not in out
    assert "This is the last output before the agent runner is killed" not in out


def _agent_handoff_start_argv(tmp_path: Path) -> list[str]:
    return [
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
        "TESTING",
        "-S",
        "TESTED",
    ]


def test_start_in_an_agent_does_not_print_a_kill_handoff_line(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Staging returns; there is no print-before-kill stderr line."""
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
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)

    from types import SimpleNamespace

    from sase.main.monitor import start as start_handler

    spawned: list[object] = []

    def fake_stage(request: object) -> SimpleNamespace:
        return SimpleNamespace(
            record=SimpleNamespace(
                monitor_id="m" * 40,
                member_agent_name="acme--mon",
                tool_run_id=None,
                tool_run_joined=False,
            ),
            staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            payload={},
            replayed=False,
        )

    monkeypatch.setattr("sase.monitor.start_stage.stage_monitor", fake_stage)
    monkeypatch.setattr(
        start_handler,
        "start_monitor",
        lambda request: spawned.append(request),
    )

    exit_code = dispatch(_agent_handoff_start_argv(tmp_path))

    assert exit_code == 0
    assert spawned == []
    captured = capsys.readouterr()
    assert "starting monitor for lane" not in captured.err
    assert "hands off your turn" not in captured.err
    assert "Staged monitor" in captured.out


def test_start_outside_an_agent_prints_no_handoff_line(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    monkeypatch.delenv("SASE_AGENT", raising=False)

    exit_code = dispatch(_agent_handoff_start_argv(tmp_path))

    assert exit_code == 0
    assert "starting monitor for lane" not in capsys.readouterr().err


def test_start_json_envelope_in_an_agent_is_staged_not_handed_off(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``--json`` envelope reports staged status and never ``handed_off``."""
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

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)

    from types import SimpleNamespace

    monkeypatch.setattr(
        "sase.monitor.start_stage.stage_monitor",
        lambda request: SimpleNamespace(
            record=SimpleNamespace(
                monitor_id="m" * 40,
                member_agent_name="acme--mon",
                tool_run_id=None,
                tool_run_joined=False,
            ),
            staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            payload={},
            replayed=False,
        ),
    )
    monkeypatch.setattr(
        "sase.main.monitor.start.monitor_start_json",
        lambda record, *, handed_off: {
            "schema_version": 3,
            "monitor": {"monitor_id": record.monitor_id},
            "handed_off": handed_off,
        },
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
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["staged"] is True
    assert payload["status"] == "staged"
    assert payload["handed_off"] is False
    assert "Staged monitor" in captured.err


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
    pin_project(monkeypatch)

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
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 3
    assert payload["handed_off"] is False
    assert payload["monitor"]["lane"] == "acme"
    assert payload["monitor"]["command"] == "true"
    assert payload["monitor"]["timeout_seconds"] == 30.0
    assert payload["monitor"]["idle_timeout_seconds"] == 5.0
    assert payload["monitor"]["start_status"] == "TESTING"
    assert payload["monitor"]["stop_status"] == "TESTED"
    assert payload["monitor"]["status_label"] == "TESTING"
    assert payload["monitor"]["status_accent"] == "#6FC4FF"
    assert payload["monitor"]["next_model"] is None
    assert payload["monitor"]["result"]["summary"] == "Command running"
    assert payload["monitor"]["evidence"]["summary"] == "auto - outcome-aware evidence"
    assert payload["monitor"]["continuation"]["summary"] == "None"


def test_start_verify_profile_supplies_statuses_and_auto_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``-p verify`` provides the common test monitor labels and evidence mode."""
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
            "verify",
            "-t",
            "30",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
            "--json",
            "-p",
            "verify",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    monitor = payload["monitor"]
    assert monitor["start_status"] == "TESTING"
    assert monitor["stop_status"] == "TESTED"
    assert monitor["profile"] == "verify"
    assert monitor["next_output"] == "auto"
    assert monitor["evidence"]["mode"] == "auto"
    meta = json.loads(Path(monitor["artifacts_dir"], "agent_meta.json").read_text())
    assert meta["monitor_profile"] == "verify"
    assert meta["monitor_next_output"] == "auto"


def test_start_json_includes_explicit_followup_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--model`` is persisted and shown in the start JSON envelope."""
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
            "verify",
            "-t",
            "30",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
            "--json",
            "-s",
            "TESTING",
            "-S",
            "TESTED",
            "-n",
            "Fix failures.",
            "-m",
            "@small",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["monitor"]["next_action"] == "Fix failures."
    assert payload["monitor"]["next_model"] == "@small"
    meta = json.loads(
        Path(payload["monitor"]["artifacts_dir"], "agent_meta.json").read_text()
    )
    assert meta["monitor_next_model"] == "@small"

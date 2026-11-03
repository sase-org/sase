"""In-agent staging and handoff tests for ``sase monitor start``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.running_field import WorkspaceClaim
from tests.main.monitor_handler_helpers import dispatch, pin_project
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)


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

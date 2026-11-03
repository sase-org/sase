"""JSON and profile output tests for ``sase monitor start``."""

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

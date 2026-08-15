"""End-to-end CLI coverage for ``sase var`` workflows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.agent_scan_facade import (
    read_agent_artifact_index_meta,
    write_agent_artifact_index_meta,
)
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
from sase.main.parser import create_parser
from sase.main.var_handler import handle_var_command
from tests.main.var_cli_helpers import (
    isolate_sase_home,
    rebuild_home_index,
    write_indexed_agent,
)


def _run_var(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exc:
        handle_var_command(create_parser().parse_args(["var", *argv]))
    return int(exc.value.code)


def test_var_cli_end_to_end_refreshes_index_and_round_trips_machine_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, projects = isolate_sase_home(tmp_path, monkeypatch)
    current = write_indexed_agent(
        projects,
        project="alpha",
        timestamp="20260815120000",
        name="worker",
        variables={"status": "old"},
    )
    write_indexed_agent(
        projects,
        project="beta",
        timestamp="20260815120500",
        name="worker",
        variables={"status": "beta"},
    )
    write_indexed_agent(
        projects,
        project="alpha",
        timestamp="20260815121000",
        name="hidden",
        variables={"status": "hidden"},
        hidden=True,
    )
    index = rebuild_home_index(home, projects)
    write_agent_artifact_index_meta(
        index,
        "schema_version",
        str(AGENT_ARTIFACT_INDEX_SCHEMA_VERSION - 1),
    )

    assert (
        _run_var(["list", "--format", "json", "--key", "status", "--limit", "0"]) == 0
    )
    upgraded = json.loads(capsys.readouterr().out)
    assert upgraded["groups"][0]["key"] == "status"
    assert read_agent_artifact_index_meta(index, "schema_version") == str(
        AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
    )

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "worker")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current))

    assert _run_var(["set", "status=ok"]) == 0
    assert "keys: status" in capsys.readouterr().out
    assert (
        _run_var(
            [
                "set",
                "cfg",
                "--json",
                "--value",
                '{"hosts":["a","b"],"retries":3}',
            ]
        )
        == 0
    )
    assert "keys: cfg, status" in capsys.readouterr().out

    assert _run_var(["get", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "cfg": {"hosts": ["a", "b"], "retries": 3},
        "status": "ok",
    }

    assert (
        _run_var(
            [
                "list",
                "--format",
                "json",
                "--project",
                "alpha",
                "--key",
                "status",
                "--value-json",
                '"ok"',
                "--limit",
                "0",
            ]
        )
        == 0
    )
    status_history = json.loads(capsys.readouterr().out)
    assert status_history["groups"][0]["values"][0]["value"] == "ok"
    assert status_history["groups"][0]["values"][0]["agents"] == ["worker"]

    assert (
        _run_var(
            [
                "get",
                'worker.cfg["retries"]',
                "--project",
                "alpha",
                "--format",
                "raw",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "3\n"

    assert (
        _run_var(
            [
                "get",
                "*.status",
                "--project",
                "alpha",
                "--format",
                "jsonl",
                "--limit",
                "0",
            ]
        )
        == 0
    )
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(row["agent_name"], row["value"]) for row in rows] == [("worker", "ok")]

    assert _run_var(["get", 'worker.cfg["missing"]', "--project", "alpha"]) == 1
    assert "missing key" in capsys.readouterr().err

    assert _run_var(["list", "--key", "absent", "--color", "never"]) == 0
    assert capsys.readouterr().out == "No matching output variables.\n"

"""``sase gate show`` -- what a gate asks for, before anyone answers it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.service import create_gate

_ANSWER_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "json.load(sys.stdin)\n"
    "print(json.dumps({'status': 'ok'}))\n"
)


def _run(*argv: str) -> int:
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", *argv])
    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)
    return int(excinfo.value.code or 0)


def _spec(request_id: str = "show-1") -> dict[str, Any]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {"icon": "🧪", "title": "Show", "notes": ["Show"]},
        "query": "(deploy AND audit) OR abort",
        "primary_branch": ["deploy", "audit"],
        "options": [
            {
                "id": "deploy",
                "label": "Deploy the build",
                "icon": "🚀",
                "command": {"argv": ["commands/deploy"]},
                "inputs": [
                    {
                        "id": "target_env",
                        "label": "Target environment",
                        "type": "enum",
                        "required": True,
                        "choices": ["staging", "production"],
                    },
                    {
                        "id": "ticket",
                        "label": "Ticket",
                        "type": "line",
                        "default": "none",
                    },
                    {
                        "id": "token",
                        "label": "Token",
                        "type": "line",
                        "secret": True,
                    },
                    {
                        "id": "hosts",
                        "label": "Hosts",
                        "type": "word",
                        "repeatable": True,
                    },
                ],
            },
            {
                "id": "audit",
                "label": "Write an audit record",
                "command": {"argv": ["commands/audit"]},
                "input_schema": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"],
                },
            },
            {
                "id": "abort",
                "label": "Abort",
                "default_selected": False,
                "feedback": "required",
                "command": {"argv": ["commands/abort"]},
            },
        ],
        "groups": [{"options": ["deploy", "audit"], "label": "Deploy and audit"}],
        "operations": [
            {
                "id": "show_diff",
                "kind": "run_command",
                "command": {"argv": ["commands/diff"]},
                "label": "Show diff",
                "key": "D",
                "display": "markdown",
                "description": "Print what this deploy would change.",
            },
            {
                "id": "edit_notes",
                "kind": "edit_file",
                "target": "notes.md",
                "edit_target": "origin",
                "label": "Edit notes",
                "key": "e",
            },
        ],
        "resources": [
            {
                "path": f"commands/{name}",
                "role": "command",
                "content": _ANSWER_COMMAND,
            }
            for name in ("deploy", "audit", "abort", "diff")
        ]
        + [{"path": "notes.md", "role": "editable", "content": "notes\n"}],
    }


def test_show_json_reports_declared_inputs_branches_and_actions(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    create_gate(_spec())

    code = _run("show", "--id", "show-1", "--kind", "custom", "--json")

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pending"
    assert payload["kind"] == "custom"
    assert payload["query"] == "(deploy AND audit) OR abort"
    assert payload["primary_branch"] == ["deploy", "audit"]
    assert payload["branches"] == [["deploy", "audit"], ["abort"]]

    deploy = next(item for item in payload["options"] if item["id"] == "deploy")
    fields = {item["id"]: item for item in deploy["inputs"]}
    assert fields["target_env"]["type"] == "enum"
    assert fields["target_env"]["required"] is True
    assert [choice["value"] for choice in fields["target_env"]["choices"]] == [
        "staging",
        "production",
    ]
    assert fields["ticket"]["default"] == "none"
    assert fields["token"]["secret"] is True
    assert fields["hosts"]["repeatable"] is True
    # The compiled schema is what the executor enforces, so it is reported too.
    assert deploy["input_schema"]["required"] == ["target_env"]
    assert deploy["input_schema"]["additionalProperties"] is False

    audit = next(item for item in payload["options"] if item["id"] == "audit")
    assert audit["inputs"] == []
    assert audit["input_schema"]["required"] == ["reason"]

    abort = next(item for item in payload["options"] if item["id"] == "abort")
    assert abort["feedback"] == "required"
    assert abort["default_selected"] is False

    actions = {item["id"]: item for item in payload["actions"]}
    assert actions["show_diff"]["kind"] == "run_command"
    assert actions["show_diff"]["display"] == "markdown"
    assert actions["show_diff"]["key"] == "D"
    assert actions["edit_notes"]["edit_target"] == "origin"


def test_show_prints_a_readable_summary_of_the_decision_surface(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    create_gate(_spec("show-human"))

    code = _run("show", "-i", "show-human", "-k", "custom")

    assert code == 0
    out = capsys.readouterr().out
    assert "Gate custom/show-human" in out
    assert "pending" in out
    assert "deploy AND audit" in out
    assert "target_env (enum, required)" in out
    assert "one of staging, production" in out
    assert "default 'none'" in out
    assert "secret" in out
    assert "hosts (word[], optional)" in out
    assert "raw schema: reason* (* required)" in out
    assert "Actions" in out
    assert "[D] show_diff" in out
    assert "Print what this deploy would change." in out
    assert "edits origin" in out


def test_show_reports_the_terminal_status_of_an_answered_gate(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    gate = create_gate(_spec("show-answered"))
    execute_gate_selection(gate.bundle_path, ["abort"], feedback="no thanks")

    assert _run("show", "-i", "show-answered", "-k", "custom", "-j") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "answered"


def test_show_reports_a_cancelled_gate(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    gate = create_gate(_spec("show-cancelled"))
    cancel_gate(gate.bundle_path, source="test")

    assert _run("show", "-i", "show-cancelled", "-k", "custom", "-j") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"


def test_show_reports_a_missing_bundle(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home

    code = _run("show", "-i", "absent", "-k", "custom")

    assert code == 1
    assert "no gate bundle for custom/absent" in capsys.readouterr().err


def test_show_rejects_id_without_kind(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home

    code = _run("show", "-i", "show-1")

    assert code == 1
    assert "-i/--id and -k/--kind must be given together" in capsys.readouterr().err


def test_show_rejects_neither_ref_nor_id_and_kind(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home

    code = _run("show")

    assert code == 1
    assert "pass a gate-shell reference" in capsys.readouterr().err


def test_show_resolves_a_gate_shell_by_member_name(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A shell-backed gate is also addressable by its member name or id prefix."""
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    from tests.gate_shell._cli_fixtures import (
        make_gate_shell,
        patch_gate_shell_project_records,
    )

    gate = create_gate({**_spec("shell-ref-1"), "shell": {}})
    artifacts_dir = make_gate_shell(
        "proj", "20260812120000", "acme--gate", lane="acme", gate_id="shell-ref-1"
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["gate_bundle_path"] = str(gate.bundle_path)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    patch_gate_shell_project_records(monkeypatch, [artifacts_dir])

    code = _run("show", "acme--gate", "--json")

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["request_id"] == "shell-ref-1"
    assert payload["gate_shell"]["gate_state"] == "pending"
    assert payload["gate_shell"]["member_agent_name"] == "acme--gate"


def test_show_unknown_gate_shell_reference_exits_with_ref_error(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    code = _run("show", "no-such-gate")

    assert code == 2
    assert "no gate shell matches" in capsys.readouterr().err

"""``sase gate act`` -- repeatable actions and origin edits from a script."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate

_ANSWER_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "json.load(sys.stdin)\n"
    "print(json.dumps({'status': 'ok'}))\n"
)

_REPORT_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "value = json.load(sys.stdin)\n"
    "with open(os.environ['GATE_TEST_LOG'], 'a') as stream:\n"
    "    stream.write(json.dumps(value) + '\\n')\n"
    "print(json.dumps({'summary': '3 files changed', 'body': '# Diff\\n\\nbody'}))\n"
)


def _run(*argv: str) -> int:
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", *argv])
    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)
    return int(excinfo.value.code or 0)


def _spec(
    request_id: str,
    operations: list[dict[str, Any]],
    *,
    extra_resources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {"icon": "🧪", "title": "Actions", "notes": ["Actions"]},
        "query": "proceed",
        "primary_branch": ["proceed"],
        "options": [
            {
                "id": "proceed",
                "label": "Proceed",
                "command": {"argv": ["commands/proceed"]},
                "input_schema": {"type": "object"},
            }
        ],
        "operations": operations,
        "resources": [
            {
                "path": "commands/proceed",
                "role": "command",
                "content": _ANSWER_COMMAND,
            },
            *(extra_resources or []),
        ],
    }


def _report_spec(request_id: str = "act-report") -> dict[str, Any]:
    return _spec(
        request_id,
        [
            {
                "id": "report",
                "kind": "run_command",
                "command": {"argv": ["commands/report"]},
                "label": "Show report",
                "key": "R",
                "display": "markdown",
                "result_schema": {"type": "object"},
            }
        ],
        extra_resources=[
            {
                "path": "commands/report",
                "role": "command",
                "content": _REPORT_COMMAND,
            }
        ],
    )


def _origin_spec(origin: Path, request_id: str = "act-origin") -> dict[str, Any]:
    return _spec(
        request_id,
        [
            {
                "id": "edit_notes",
                "kind": "edit_file",
                "target": "notes.md",
                "edit_target": "origin",
                "label": "Edit notes",
                "key": "e",
            }
        ],
        extra_resources=[
            {"path": "notes.md", "role": "editable", "source": str(origin)}
        ],
    )


@pytest.fixture()
def action_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "actions.log"
    monkeypatch.setenv("GATE_TEST_LOG", str(log))
    return log


def _rewriting_editor(tmp_path: Path, text: str) -> Path:
    editor = tmp_path / "fake-editor"
    editor.write_text(
        f"#!/usr/bin/env python3\nimport sys\nopen(sys.argv[1], 'w').write({text!r})\n",
        encoding="utf-8",
    )
    editor.chmod(0o755)
    return editor


def test_run_command_action_repeats_and_leaves_the_gate_answerable(
    gate_home: Path, action_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point of an action: run it as often as you like, then answer."""
    del gate_home
    gate = create_gate(_report_spec())

    assert _run("act", "-i", "act-report", "-k", "custom", "-o", "report") == 0
    out = capsys.readouterr().out
    assert "3 files changed" in out
    assert "still pending and answerable" in out

    assert _run("act", "-i", "act-report", "-k", "custom", "-o", "report") == 0
    capsys.readouterr()
    assert action_log.read_text(encoding="utf-8").count("\n") == 2
    assert not gate.response_path.exists()

    execute_gate_selection(gate.bundle_path, ["proceed"])
    assert gate.response_path.is_file()


def test_run_command_action_emits_the_display_record_as_json(
    gate_home: Path, action_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    del action_log
    create_gate(_report_spec("act-report-json"))

    code = _run(
        "act", "-i", "act-report-json", "-k", "custom", "-o", "report", "--json"
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation_id"] == "report"
    assert payload["operation_kind"] == "run_command"
    assert payload["summary"] == "3 files changed"
    assert payload["display_format"] == "markdown"
    assert payload["refresh"] is False
    assert payload["status"] == "ran"


def test_run_command_action_passes_input_to_the_command(
    gate_home: Path, action_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    create_gate(_report_spec("act-report-input"))

    code = _run(
        "act",
        "-i",
        "act-report-input",
        "-k",
        "custom",
        "-o",
        "report",
        "-I",
        '{"deep": true}',
    )
    capsys.readouterr()

    assert code == 0
    assert json.loads(action_log.read_text(encoding="utf-8").strip()) == {"deep": True}


def test_action_on_an_answered_gate_is_refused(
    gate_home: Path, action_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    del action_log
    gate = create_gate(_report_spec("act-answered"))
    execute_gate_selection(gate.bundle_path, ["proceed"])

    code = _run("act", "-i", "act-answered", "-k", "custom", "-o", "report")

    assert code == 1
    assert "already_answered" in capsys.readouterr().err


def test_unknown_action_is_a_pointed_error(
    gate_home: Path, action_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    del action_log
    create_gate(_report_spec("act-unknown"))

    code = _run("act", "-i", "act-unknown", "-k", "custom", "-o", "nope")

    assert code == 1
    assert "gate declares no action: nope" in capsys.readouterr().err


def test_edit_file_action_edits_the_origin_and_accepts_it(
    gate_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``edit_target: origin`` opens the durable file, not the bundle copy."""
    del gate_home
    origin = tmp_path / "notes.md"
    origin.write_text("original\n", encoding="utf-8")
    gate = create_gate(_origin_spec(origin))
    monkeypatch.setenv(
        "EDITOR", str(_rewriting_editor(tmp_path, "revised by the reviewer\n"))
    )
    monkeypatch.delenv("VISUAL", raising=False)

    code = _run("act", "-i", "act-origin", "-k", "custom", "-o", "edit_notes", "-j")

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["edit_path"] == str(origin)
    assert payload["accepted"] is True
    assert payload["draft_state"] == "clean"
    assert origin.read_text(encoding="utf-8") == "revised by the reviewer\n"
    assert (gate.bundle_path / "notes.md").read_text(encoding="utf-8") == (
        "revised by the reviewer\n"
    )
    assert not gate.response_path.exists()


def test_edit_file_action_keeps_a_rejected_draft_in_the_origin(
    gate_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused edit must never look like a discarded edit."""
    del gate_home
    origin = tmp_path / "notes.md"
    origin.write_text("original\n", encoding="utf-8")
    gate = create_gate(_origin_spec(origin, "act-origin-reject"))
    monkeypatch.setenv("EDITOR", str(_rewriting_editor(tmp_path, "draft\n")))
    monkeypatch.delenv("VISUAL", raising=False)

    def reject(_bundle_path: Path, operation_id: str) -> dict[str, Any]:
        raise GateError("invalid_plan", operation_id, "plan validation failed")

    monkeypatch.setattr("sase.notification_gates.cli_act.accept_edited_origin", reject)

    code = _run("act", "-i", "act-origin-reject", "-k", "custom", "-o", "edit_notes")

    assert code == 1
    err = capsys.readouterr().err
    assert "edit rejected [invalid_plan]" in err
    assert f"your draft is kept in {origin}" in err
    assert origin.read_text(encoding="utf-8") == "draft\n"
    assert (gate.bundle_path / "notes.md").read_text(encoding="utf-8") == "original\n"


def test_edit_file_action_reports_an_editor_that_failed(
    gate_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    origin = tmp_path / "notes.md"
    origin.write_text("original\n", encoding="utf-8")
    create_gate(_origin_spec(origin, "act-origin-editor"))
    failing = tmp_path / "failing-editor"
    failing.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    failing.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(failing))
    monkeypatch.delenv("VISUAL", raising=False)

    code = _run("act", "-i", "act-origin-editor", "-k", "custom", "-o", "edit_notes")

    assert code == 1
    assert "exited with status 3" in capsys.readouterr().err
    assert origin.read_text(encoding="utf-8") == "original\n"


def test_edit_file_action_requires_an_editor(
    gate_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    origin = tmp_path / "notes.md"
    origin.write_text("original\n", encoding="utf-8")
    create_gate(_origin_spec(origin, "act-origin-none"))
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(os, "defpath", str(tmp_path / "empty"))

    code = _run("act", "-i", "act-origin-none", "-k", "custom", "-o", "edit_notes")

    assert code == 1
    assert "no editor is available" in capsys.readouterr().err

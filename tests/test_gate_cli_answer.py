"""``sase gate answer`` -- headless selection, typed input, and retry."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import pytest

from sase.main.gate_handler import handle_gate_command
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.service import create_gate

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)


def _run(*argv: str) -> int:
    """Parse and dispatch one ``sase gate`` invocation, returning its exit code."""
    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["gate", *argv])
    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)
    return int(excinfo.value.code or 0)


def _spec(
    request_id: str,
    options: list[dict[str, Any]],
    *,
    commands: dict[str, str] | None = None,
) -> dict[str, Any]:
    option_ids = [str(option["id"]) for option in options]
    spec: dict[str, Any] = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {"icon": "🧪", "title": "CLI", "notes": ["CLI"]},
        "query": (
            option_ids[0]
            if len(option_ids) == 1
            else "(" + " AND ".join(option_ids) + ")"
        ),
        "primary_branch": option_ids,
        "options": [
            {**option, "command": {"argv": [f"commands/{option['id']}"]}}
            for option in options
        ],
        "resources": [
            {
                "path": f"commands/{option_id}",
                "role": "command",
                "content": (commands or {}).get(option_id, _ECHO_COMMAND),
            }
            for option_id in option_ids
        ],
    }
    if len(option_ids) > 1:
        spec["groups"] = [{"options": option_ids, "label": "All"}]
    return spec


_TYPED_FIELDS = [
    {"id": "a_word", "label": "Word", "type": "word"},
    {"id": "a_line", "label": "Line", "type": "line"},
    {"id": "a_text", "label": "Text", "type": "text"},
    {"id": "a_path", "label": "Path", "type": "path"},
    {"id": "an_agent", "label": "Agent", "type": "agent"},
    {"id": "an_int", "label": "Int", "type": "int"},
    {"id": "a_float", "label": "Float", "type": "float"},
    {"id": "a_bool", "label": "Bool", "type": "bool"},
    {
        "id": "a_mode",
        "label": "Mode",
        "type": "enum",
        "choices": ["fast", "thorough"],
    },
    {"id": "many", "label": "Lines", "type": "line", "repeatable": True},
]


def _typed_gate(request_id: str = "cli-typed") -> Any:
    return create_gate(
        _spec(request_id, [{"id": "run", "label": "Run", "inputs": _TYPED_FIELDS}])
    )


def _response(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_set_types_every_declared_input_field(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--set`` values are typed by the field they name, not left as strings."""
    del gate_home
    gate = _typed_gate()

    code = _run(
        "answer",
        "--id",
        "cli-typed",
        "--kind",
        "custom",
        "--option",
        "run",
        "--set",
        "a_word=token",
        "--set",
        "a_line=one line",
        "--set",
        "a_text=free text",
        "--set",
        "a_path=/tmp/example",
        "--set",
        "an_agent=worker.1",
        "--set",
        "an_int=7",
        "--set",
        "a_float=1.5",
        "--set",
        "a_bool=yes",
        "--set",
        "a_mode=thorough",
        "--set",
        "many=first",
        "--set",
        "many=second",
    )
    capsys.readouterr()

    assert code == 0
    response = _response(gate.response_path)
    assert response["option_inputs"]["run"] == {
        "a_word": "token",
        "a_line": "one line",
        "a_text": "free text",
        "a_path": "/tmp/example",
        "an_agent": "worker.1",
        "an_int": 7,
        "a_float": 1.5,
        "a_bool": True,
        "a_mode": "thorough",
        "many": ["first", "second"],
    }
    assert (
        response["option_results"][0]["result"]["input"]
        == (response["option_inputs"]["run"])
    )


@pytest.mark.parametrize(
    ("assignment", "expected"),
    [
        ("an_int=seven", "expected an integer"),
        ("a_float=fast", "expected a number"),
        ("a_bool=maybe", "expected a boolean"),
        ("a_mode=medium", "expected one of fast, thorough"),
        ("a_word", "expected name=value"),
    ],
)
def test_set_rejects_values_its_field_cannot_hold(
    assignment: str,
    expected: str,
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    gate = _typed_gate("cli-typed-bad")

    code = _run(
        "answer",
        "-i",
        "cli-typed-bad",
        "-k",
        "custom",
        "-o",
        "run",
        "-s",
        assignment,
    )

    assert code == 1
    assert expected in capsys.readouterr().err
    assert not gate.response_path.exists()


def test_set_repeated_on_a_scalar_field_is_a_usage_error(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    _typed_gate("cli-typed-repeat")

    code = _run(
        "answer",
        "-i",
        "cli-typed-repeat",
        "-k",
        "custom",
        "-o",
        "run",
        "-s",
        "a_word=one",
        "-s",
        "a_word=two",
    )

    assert code == 1
    assert "the field is not repeatable" in capsys.readouterr().err


def test_set_names_the_accepted_keys_when_no_option_takes_one(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unknown field fails on the command line, not at submission time."""
    del gate_home
    gate = _typed_gate("cli-typed-unknown")

    code = _run(
        "answer",
        "-i",
        "cli-typed-unknown",
        "-k",
        "custom",
        "-o",
        "run",
        "-s",
        "nonesuch=1",
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "no selected option accepts that input" in err
    assert "a_word" in err and "a_mode" in err
    assert not gate.response_path.exists()


def test_set_broadcasts_a_shared_field_to_every_accepting_option(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One typed field, two AND members, one command line."""
    del gate_home
    ticket = {"id": "ticket", "label": "Ticket", "type": "word", "required": True}
    gate = create_gate(
        _spec(
            "cli-broadcast",
            [
                {"id": "build", "label": "Build", "inputs": [ticket]},
                {"id": "publish", "label": "Publish", "inputs": [ticket]},
            ],
        )
    )

    code = _run(
        "answer",
        "-i",
        "cli-broadcast",
        "-k",
        "custom",
        "-o",
        "build",
        "-o",
        "publish",
        "-s",
        "ticket=OPS-9",
    )
    capsys.readouterr()

    assert code == 0
    response = _response(gate.response_path)
    assert response["option_inputs"] == {
        "build": {"ticket": "OPS-9"},
        "publish": {"ticket": "OPS-9"},
    }


def test_option_input_reads_a_file_and_stdin(
    gate_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    field = {"id": "ticket", "label": "Ticket", "type": "word", "required": True}
    gate = create_gate(
        _spec(
            "cli-files",
            [
                {"id": "build", "label": "Build", "inputs": [field]},
                {"id": "publish", "label": "Publish", "inputs": [field]},
            ],
        )
    )
    payload = tmp_path / "build.json"
    payload.write_text(json.dumps({"ticket": "OPS-1"}), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"ticket": "OPS-2"})))

    code = _run(
        "answer",
        "-i",
        "cli-files",
        "-k",
        "custom",
        "-o",
        "build",
        "-o",
        "publish",
        "-O",
        f"build=@{payload}",
        "-O",
        "publish=-",
    )
    capsys.readouterr()

    assert code == 0
    assert _response(gate.response_path)["option_inputs"] == {
        "build": {"ticket": "OPS-1"},
        "publish": {"ticket": "OPS-2"},
    }


def test_stdin_can_only_be_read_once(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two ``-`` arguments would silently receive the same value."""
    del gate_home
    field = {"id": "ticket", "label": "Ticket", "type": "word"}
    create_gate(
        _spec(
            "cli-stdin-twice",
            [
                {"id": "build", "label": "Build", "inputs": [field]},
                {"id": "publish", "label": "Publish", "inputs": [field]},
            ],
        )
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    code = _run(
        "answer",
        "-i",
        "cli-stdin-twice",
        "-k",
        "custom",
        "-o",
        "build",
        "-o",
        "publish",
        "-O",
        "build=-",
        "-O",
        "publish=-",
    )

    assert code == 1
    assert "stdin can only be read once" in capsys.readouterr().err


def test_shared_and_per_option_input_are_mutually_exclusive(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    _typed_gate("cli-conflict")

    code = _run(
        "answer",
        "-i",
        "cli-conflict",
        "-k",
        "custom",
        "-o",
        "run",
        "-I",
        "{}",
        "-s",
        "a_word=token",
    )

    assert code == 1
    assert "use one or the other" in capsys.readouterr().err


def test_unknown_option_lists_the_declared_ids(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    _typed_gate("cli-unknown-option")

    code = _run("answer", "-i", "cli-unknown-option", "-k", "custom", "-o", "nope")

    assert code == 1
    err = capsys.readouterr().err
    assert "gate declares no option(s): nope" in err
    assert "declared: run" in err


def test_secret_input_reaches_the_command_and_is_redacted_in_json(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    create_gate(
        _spec(
            "cli-secret",
            [
                {
                    "id": "rotate",
                    "label": "Rotate",
                    "inputs": [
                        {
                            "id": "token",
                            "label": "Token",
                            "type": "line",
                            "required": True,
                            "secret": True,
                        }
                    ],
                }
            ],
            # Reports the length of the value it read, which only the
            # unredacted secret can produce, and echoes the value itself,
            # which the response must not keep.
            commands={
                "rotate": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "value = json.load(sys.stdin)['token']\n"
                    "print(json.dumps("
                    "{'token_len': len(value), 'echoed': value}))\n"
                )
            },
        )
    )

    code = _run(
        "answer",
        "-i",
        "cli-secret",
        "-k",
        "custom",
        "-o",
        "rotate",
        "-s",
        "token=hunter2",
        "--json",
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "answered"
    assert payload["option_inputs"] == {"rotate": {"token": {"$redacted": True}}}
    assert payload["option_results"][0]["result"] == {
        "token_len": len("hunter2"),
        "echoed": {"$redacted": True},
    }


def test_cancelled_gate_exits_with_the_cancelled_code(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    gate = create_gate(_spec("cli-cancelled", [{"id": "run", "label": "Run"}]))
    cancel_gate(gate.bundle_path, source="test")

    code = _run("answer", "-i", "cli-cancelled", "-k", "custom", "-o", "run")

    assert code == 3
    assert "gate_cancelled" in capsys.readouterr().err


def test_partial_attempt_names_both_retry_flags_then_resumes(
    gate_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A partially executed AND branch never silently re-runs."""
    del gate_home
    counter = tmp_path / "second-runs"
    failing = (
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "value = json.load(sys.stdin)\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "runs = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(runs + 1))\n"
        "if runs == 0:\n"
        "    sys.stderr.write('first run fails')\n"
        "    raise SystemExit(9)\n"
        "print(json.dumps({'status': 'ok', 'input': value}))\n"
    )
    gate = create_gate(
        _spec(
            "cli-partial",
            [
                {"id": "first", "label": "First"},
                {"id": "second", "label": "Second"},
            ],
            commands={"second": failing},
        )
    )
    argv = (
        "answer",
        "-i",
        "cli-partial",
        "-k",
        "custom",
        "-o",
        "first",
        "-o",
        "second",
    )

    assert _run(*argv) == 1
    capsys.readouterr()

    assert _run(*argv) == 1
    err = capsys.readouterr().err
    assert "partial_attempt" in err
    assert "--resume" in err and "--restart" in err
    assert not gate.response_path.exists()

    assert _run(*argv, "--resume") == 0
    capsys.readouterr()
    assert gate.response_path.is_file()


def test_answering_an_answered_gate_reports_it_without_re_running(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home
    gate = create_gate(_spec("cli-already", [{"id": "run", "label": "Run"}]))
    execute_gate_selection(gate.bundle_path, ["run"])

    code = _run("answer", "-i", "cli-already", "-k", "custom", "-o", "run", "-j")

    assert code == 0
    assert json.loads(capsys.readouterr().out)["already_answered"] is True


def test_missing_bundle_is_a_pointed_error(
    gate_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del gate_home

    code = _run("answer", "-i", "nothing-here", "-k", "custom", "-o", "run")

    assert code == 1
    assert "no gate bundle for custom/nothing-here" in capsys.readouterr().err

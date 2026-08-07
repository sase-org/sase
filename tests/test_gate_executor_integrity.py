"""Diagnosable input rejection and non-destructive retry for gate execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.journal import (
    EXECUTION_JOURNAL_FILENAME,
    incomplete_attempt,
)
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate

_PASSTHROUGH = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "value = json.load(sys.stdin)\n"
    "print(json.dumps({'status': 'ok', 'input': value}))\n"
)

_QUIET = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "json.load(sys.stdin)\n"
    "print(json.dumps({'status': 'ok'}))\n"
)

_JOURNALLING_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "json.load(sys.stdin)\n"
    "name = os.environ['GATE_TEST_OPTION']\n"
    "with open(os.environ['GATE_TEST_LOG'], 'a') as stream:\n"
    "    stream.write(name + '\\n')\n"
    "if os.path.exists(os.environ['GATE_TEST_FAIL'] + '.' + name):\n"
    "    sys.stderr.write(name + ' refused\\n')\n"
    "    raise SystemExit(7)\n"
    "print(json.dumps({'status': 'ok', 'option': name}))\n"
)


def _strict_input_spec(
    *,
    request_id: str = "strict-input",
    input_schema: object | None = None,
    command: str = _PASSTHROUGH,
) -> dict[str, object]:
    schema = input_schema
    if schema is None:
        schema = {
            "type": "object",
            "required": ["target_env"],
            "properties": {"target_env": {"type": "string"}},
        }
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "\U0001f6e1",
            "title": "Strict input",
            "notes": ["Strict input"],
        },
        "query": "proceed",
        "primary_branch": ["proceed"],
        "options": [
            {
                "id": "proceed",
                "label": "Proceed",
                "command": {"argv": ["commands/proceed"]},
                "input_schema": schema,
                "result_schema": {"type": "object"},
            }
        ],
        "resources": [
            {"path": "commands/proceed", "role": "command", "content": command}
        ],
        "auto": False,
    }


def _and_branch_spec(*, request_id: str = "and-branch") -> dict[str, object]:
    def option(option_id: str) -> dict[str, object]:
        return {
            "id": option_id,
            "label": option_id.title(),
            "command": {"argv": [f"commands/{option_id}"]},
            "input_schema": {"type": "object"},
            "result_schema": {"type": "object"},
        }

    def resource(option_id: str) -> dict[str, object]:
        return {
            "path": f"commands/{option_id}",
            "role": "command",
            "content": _JOURNALLING_COMMAND.replace(
                "os.environ['GATE_TEST_OPTION']", repr(option_id)
            ),
        }

    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "\U0001f6e1",
            "title": "Two step",
            "notes": ["Two step"],
        },
        "query": "(first AND second)",
        "primary_branch": ["first", "second"],
        "options": [option("first"), option("second")],
        "resources": [resource("first"), resource("second")],
        "auto": False,
    }


def _errors(bundle_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text())
        for path in sorted((bundle_path / "errors").glob("*.json"))
    ]


def _journal(bundle_path: Path) -> list[dict[str, object]]:
    path = bundle_path / EXECUTION_JOURNAL_FILENAME
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture()
def and_branch_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    log = tmp_path / "runs.log"
    fail = tmp_path / "fail"
    monkeypatch.setenv("GATE_TEST_LOG", str(log))
    monkeypatch.setenv("GATE_TEST_FAIL", str(fail))
    return log, fail


def _runs(log: Path) -> list[str]:
    if not log.is_file():
        return []
    return log.read_text().split()


def test_rejected_input_is_recorded_and_leaves_the_gate_pending(
    gate_home: Path,
) -> None:
    result = create_gate(_strict_input_spec())

    with pytest.raises(GateError) as rejected:
        execute_gate_selection(result.bundle_path, ["proceed"], {})

    assert rejected.value.code == "schema_validation_failed"
    [error] = _errors(result.bundle_path)
    assert error["code"] == "schema_validation_failed"
    assert error["option_id"] == "proceed"
    assert not result.response_path.exists()
    assert _journal(result.bundle_path) == []

    execution = execute_gate_selection(
        result.bundle_path, ["proceed"], {"target_env": "staging"}
    )
    assert execution.response["input"] == {"target_env": "staging"}


def test_feedback_rejection_is_recorded_like_every_other_rejection(
    gate_home: Path,
) -> None:
    spec = _strict_input_spec(request_id="strict-feedback", input_schema={})
    options = spec["options"]
    assert isinstance(options, list)
    options[0]["feedback"] = "required"
    result = create_gate(spec)

    with pytest.raises(GateError) as rejected:
        execute_gate_selection(result.bundle_path, ["proceed"], {})

    assert rejected.value.code == "feedback_required"
    assert [error["code"] for error in _errors(result.bundle_path)] == [
        "feedback_required"
    ]


@pytest.mark.parametrize(
    ("request_id", "value"),
    [
        ("too-large", {"target_env": "x" * 70_000}),
        ("too-deep", None),
        ("too-wide", None),
    ],
)
def test_out_of_bounds_input_is_rejected_and_recorded(
    gate_home: Path, request_id: str, value: object
) -> None:
    if request_id == "too-deep":
        nested: object = "leaf"
        for _ in range(20):
            nested = {"next": nested}
        value = nested
    elif request_id == "too-wide":
        value = {f"key_{index}": index for index in range(200)}
    result = create_gate(_strict_input_spec(request_id=request_id, input_schema={}))

    with pytest.raises(GateError) as rejected:
        execute_gate_selection(result.bundle_path, ["proceed"], value)

    assert rejected.value.code == "input_too_large"
    assert [error["code"] for error in _errors(result.bundle_path)] == [
        "input_too_large"
    ]
    assert not result.response_path.exists()


def test_oversized_array_input_is_rejected(gate_home: Path) -> None:
    result = create_gate(_strict_input_spec(request_id="too-many", input_schema={}))
    with pytest.raises(GateError) as rejected:
        execute_gate_selection(
            result.bundle_path, ["proceed"], {"items": list(range(600))}
        )
    assert rejected.value.code == "input_too_large"


def test_partial_and_branch_offers_resume_and_restart(
    gate_home: Path, and_branch_env: tuple[Path, Path]
) -> None:
    log, fail = and_branch_env
    (fail.parent / "fail.second").write_text("")
    result = create_gate(_and_branch_spec())

    with pytest.raises(GateError) as failed:
        execute_gate_selection(result.bundle_path, ["first", "second"], {})
    assert failed.value.code == "command_failed"
    assert _runs(log) == ["first", "second"]

    events = [record["event"] for record in _journal(result.bundle_path)]
    assert events == ["attempt_started", "option_completed", "option_failed"]
    pending = incomplete_attempt(result.bundle_path)
    assert pending is not None
    assert pending.completed_option_ids == ("first",)
    assert pending.failed_option_ids == ("second",)

    with pytest.raises(GateError) as partial:
        execute_gate_selection(result.bundle_path, ["first", "second"], {})
    assert partial.value.code == "partial_attempt"
    assert partial.value.target == pending.attempt_id
    assert _runs(log) == ["first", "second"]

    (fail.parent / "fail.second").unlink()
    log.unlink()
    execution = execute_gate_selection(
        result.bundle_path, ["first", "second"], {}, retry="resume"
    )
    assert _runs(log) == ["second"]
    assert execution.response["option_results"] == [
        {"id": "first", "result": {"status": "ok", "option": "first"}},
        {"id": "second", "result": {"status": "ok", "option": "second"}},
    ]
    assert incomplete_attempt(result.bundle_path) is None


def test_restart_reruns_every_option_in_the_branch(
    gate_home: Path, and_branch_env: tuple[Path, Path]
) -> None:
    log, fail = and_branch_env
    (fail.parent / "fail.second").write_text("")
    result = create_gate(_and_branch_spec(request_id="and-restart"))

    with pytest.raises(GateError):
        execute_gate_selection(result.bundle_path, ["first", "second"], {})

    (fail.parent / "fail.second").unlink()
    log.unlink()
    execute_gate_selection(result.bundle_path, ["first", "second"], {}, retry="restart")

    assert _runs(log) == ["first", "second"]
    events = [record["event"] for record in _journal(result.bundle_path)]
    assert events.count("attempt_started") == 2
    assert events[-1] == "attempt_completed"


def test_changed_input_supersedes_the_incomplete_attempt(
    gate_home: Path, and_branch_env: tuple[Path, Path]
) -> None:
    log, fail = and_branch_env
    (fail.parent / "fail.second").write_text("")
    result = create_gate(_and_branch_spec(request_id="and-superseded"))

    with pytest.raises(GateError):
        execute_gate_selection(result.bundle_path, ["first", "second"], {})
    stale = incomplete_attempt(result.bundle_path)
    assert stale is not None

    (fail.parent / "fail.second").unlink()
    log.unlink()
    execute_gate_selection(result.bundle_path, ["first", "second"], {"note": "changed"})

    assert _runs(log) == ["first", "second"]
    superseded = [
        record
        for record in _journal(result.bundle_path)
        if record["event"] == "attempt_superseded"
    ]
    assert [record["attempt_id"] for record in superseded] == [stale.attempt_id]


def test_retry_without_a_partial_attempt_is_an_error(gate_home: Path) -> None:
    result = create_gate(_strict_input_spec(request_id="no-attempt", input_schema={}))
    with pytest.raises(GateError) as rejected:
        execute_gate_selection(result.bundle_path, ["proceed"], {}, retry="resume")
    assert rejected.value.code == "no_partial_attempt"


def test_journal_records_input_digests_but_never_raw_input(gate_home: Path) -> None:
    result = create_gate(_strict_input_spec(request_id="digest-only", command=_QUIET))
    execute_gate_selection(
        result.bundle_path, ["proceed"], {"target_env": "secret-env"}
    )

    raw = (result.bundle_path / EXECUTION_JOURNAL_FILENAME).read_text()
    assert "secret-env" not in raw
    started = _journal(result.bundle_path)[0]
    assert started["selected_option_ids"] == ["proceed"]
    digests = started["input_digests"]
    assert isinstance(digests, dict)
    assert len(str(digests["proceed"])) == 64

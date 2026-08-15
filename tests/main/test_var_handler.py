"""Tests for the ``sase var`` parser, handler, and storage helper."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.agent_output_variables import (
    MAX_OUTPUT_VARIABLE_VALUE_BYTES,
    parse_output_variable_assignments,
    read_agent_output_variables,
    set_agent_output_variables,
)
from sase.core.output_variable_values import VarValue
from sase.main.parser import create_parser, default_list_delegation_notice
from sase.main.var_cli import resolve_current_var_agent_name
from sase.main.var_handler import handle_var_command


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "var_subcommand": "set",
        "assignments": ["status=ok"],
        "json": False,
        "value": None,
        "value_file": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_parser_registers_var_set_assignments() -> None:
    parser = create_parser()

    args = parser.parse_args(["var", "set", "plan_file=sdd/plan.md", "status=ok"])

    assert args.command == "var"
    assert args.var_subcommand == "set"
    assert args.assignments == ["plan_file=sdd/plan.md", "status=ok"]


def test_parser_registers_json_for_var_set() -> None:
    parser = create_parser()

    set_args = parser.parse_args(["var", "set", "cfg={}", "--json"])

    assert set_args.var_subcommand == "set"
    assert set_args.json is True


def test_bare_var_delegates_to_list() -> None:
    args = create_parser().parse_args(["var"])
    explicit = create_parser().parse_args(["var", "list"])

    assert args.var_subcommand == "list"
    assert args.format == "pretty"
    assert args.limit == explicit.limit
    assert default_list_delegation_notice(args) == (
        "No subcommand provided for 'sase var'; delegating to 'sase var list'."
    )


def test_var_help_keeps_subcommands_and_set_options_alphabetized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "--help"])
    assert exc.value.code == 0
    group_help = capsys.readouterr().out
    assert group_help.index("\n    get ") < group_help.index("\n    list ")
    assert group_help.index("\n    list ") < group_help.index("\n    set ")
    assert "\n    show " not in group_help

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "set", "--help"])
    assert exc.value.code == 0
    set_help = capsys.readouterr().out
    # Match on ", --option" rather than "-x, --option" since argparse's
    # short-flag/metavar formatting for options that take a value differs
    # between Python 3.12 (`-v TEXT, --value TEXT`) and 3.13+ (`-v, --value
    # TEXT`); the comma before the long option is stable across versions.
    assert set_help.index(", --json") < set_help.index(", --value ")
    assert set_help.index(", --value ") < set_help.index(", --value-file")


@pytest.mark.parametrize(
    ("option", "destination"),
    (
        ("-v", "value"),
        ("--value", "value"),
        ("-f", "value_file"),
        ("--value-file", "value_file"),
    ),
)
def test_parser_registers_var_set_value_sources(
    option: str,
    destination: str,
) -> None:
    parser = create_parser()

    args = parser.parse_args(["var", "set", "summary", option, "source"])

    assert args.assignments == ["summary"]
    assert getattr(args, destination) == "source"


def test_parser_rejects_both_var_set_value_sources() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "var",
                "set",
                "summary",
                "--value",
                "text",
                "--value-file",
                "value.txt",
            ]
        )

    assert exc.value.code == 2


def test_parser_value_source_requires_a_positional_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["var", "set", "--value", "text"])

    assert exc.value.code == 2
    assert "requires exactly one bare KEY" in capsys.readouterr().err


def test_parse_assignments_splits_on_first_equals() -> None:
    variables = parse_output_variable_assignments(["token=a=b=c", "_status=ok"])

    assert variables == {"token": "a=b=c", "_status": "ok"}


@pytest.mark.parametrize(
    "assignment", ["missing_equals", "1bad=value", "bad-key=value"]
)
def test_parse_assignments_rejects_invalid_input(assignment: str) -> None:
    with pytest.raises(ValueError):
        parse_output_variable_assignments([assignment])


def test_parse_assignment_error_explains_spaces_and_newlines() -> None:
    with pytest.raises(ValueError) as exc:
        parse_output_variable_assignments(["summary=tests", "passed"])

    message = str(exc.value)
    assert "passed" in message
    assert "Quote the whole assignment" in message
    assert "sase var set KEY --value TEXT" in message


def test_parse_assignments_normalizes_line_endings() -> None:
    variables = parse_output_variable_assignments(["body=a\r\nb\rc"])

    assert variables == {"body": "a\nb\nc"}


def test_output_variable_value_rejects_nul_and_enforces_utf8_byte_limit(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="body.*NUL"):
        set_agent_output_variables(artifacts_dir, {"body": "a\x00b"})

    accepted = "é" * (MAX_OUTPUT_VARIABLE_VALUE_BYTES // 2)
    with patch(
        "sase.core.agent_output_variables."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        stored = set_agent_output_variables(artifacts_dir, {"body": accepted})
    assert stored["body"] == accepted

    rejected = accepted + "x"
    with pytest.raises(ValueError) as exc:
        set_agent_output_variables(artifacts_dir, {"body": rejected})
    message = str(exc.value)
    assert "body" in message
    assert str(MAX_OUTPUT_VARIABLE_VALUE_BYTES + 1) in message
    assert str(MAX_OUTPUT_VARIABLE_VALUE_BYTES) in message


def test_set_agent_output_variables_merges_metadata_and_refreshes_index(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "name": "build-1",
                "output_variables": {"old": "keep", "status": "old"},
            }
        ),
        encoding="utf-8",
    )

    with patch(
        "sase.core.agent_output_variables."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        stored = set_agent_output_variables(
            artifacts_dir,
            {"status": "ok", "result_path": "dist/report.md"},
        )

    assert stored == {
        "old": "keep",
        "result_path": "dist/report.md",
        "status": "ok",
    }
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["name"] == "build-1"
    assert meta["output_variables"] == stored
    update_index.assert_called_once_with(artifacts_dir)


def test_read_agent_output_variables_returns_structured_json_values(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "output_variables": {
                    "ok": "yes",
                    "count": 123,
                    "cfg": {"enabled": True, "hosts": ["a", "b"]},
                    "missing": None,
                }
            }
        ),
        encoding="utf-8",
    )

    assert read_agent_output_variables(artifacts_dir) == {
        "cfg": {"enabled": True, "hosts": ["a", "b"]},
        "count": 123,
        "missing": None,
        "ok": "yes",
    }


def test_set_agent_output_variables_round_trips_structured_values(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text("{}", encoding="utf-8")
    values: dict[str, VarValue] = {
        "report": {
            "passed": True,
            "duration": 2.5,
            "suites": ["unit", {"name": "integration", "failures": None}],
        }
    }

    with patch(
        "sase.core.agent_output_variables."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        stored = set_agent_output_variables(artifacts_dir, values)

    assert stored == values
    assert read_agent_output_variables(artifacts_dir) == values


def test_var_set_requires_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args())

    assert exc.value.code == 1
    assert "SASE_AGENT=1 is required" in capsys.readouterr().err


def test_var_set_requires_artifacts_dir_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args())

    assert exc.value.code == 1
    assert "SASE_ARTIFACTS_DIR" in capsys.readouterr().err


def test_var_set_persists_values_and_prints_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "build-1"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(_args(assignments=["plan_file=sdd/plan.md", "status=ok"]))

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "agent: build-1" in output
    assert "keys: plan_file, status" in output
    assert f"artifacts_dir: {artifacts_dir}" in output
    meta = json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["output_variables"] == {
        "plan_file": "sdd/plan.md",
        "status": "ok",
    }


def test_var_set_value_preserves_spaces_and_newlines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    value = "tests passed\nnext step"

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(_args(assignments=["summary"], value=value))

    assert exc.value.code == 0
    assert read_agent_output_variables(artifacts_dir) == {"summary": value}


def test_var_set_value_file_strips_exactly_one_trailing_newline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    value_file = tmp_path / "value.txt"
    value_file.write_text("a\n\n", encoding="utf-8")

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(_args(assignments=["body"], value_file=str(value_file)))

    assert exc.value.code == 0
    assert read_agent_output_variables(artifacts_dir) == {"body": "a\n"}


def test_var_set_value_file_reads_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("first\nsecond\n"))

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(_args(assignments=["body"], value_file="-"))

    assert exc.value.code == 0
    assert read_agent_output_variables(artifacts_dir) == {"body": "first\nsecond"}


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        (
            {
                "assignments": ['cfg={"hosts":["b","a"],"retries":3,"enabled":true}'],
                "json": True,
            },
            {"cfg": {"enabled": True, "hosts": ["b", "a"], "retries": 3}},
        ),
        (
            {
                "assignments": ["cfg"],
                "json": True,
                "value": '{"retries":3}',
            },
            {"cfg": {"retries": 3}},
        ),
    ),
)
def test_var_set_json_assignment_and_value_forms(
    overrides: dict[str, object],
    expected: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(_args(**overrides))

    assert exc.value.code == 0
    assert read_agent_output_variables(artifacts_dir) == expected


def test_var_set_json_value_file_preserves_json_whitespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    value_file = tmp_path / "value.json"
    value_file.write_text('{"notes":"ends with newline\\n"}\n', encoding="utf-8")

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(
            _args(
                assignments=["report"],
                json=True,
                value_file=str(value_file),
            )
        )

    assert exc.value.code == 0
    assert read_agent_output_variables(artifacts_dir) == {
        "report": {"notes": "ends with newline\n"}
    }


def test_var_set_json_assignment_uses_structural_not_document_string_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    chunks = ["x" * 1_024 for _ in range(9)]
    assignment = f"chunks={json.dumps(chunks)}"
    assert len(assignment.encode()) > MAX_OUTPUT_VARIABLE_VALUE_BYTES

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(_args(assignments=[assignment], json=True))

    assert exc.value.code == 0
    assert read_agent_output_variables(artifacts_dir) == {"chunks": chunks}


def test_var_set_json_value_file_reads_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO('["first","second"]\n'))

    with (
        patch(
            "sase.core.agent_output_variables."
            "update_agent_artifact_index_for_marker_mutation"
        ),
        pytest.raises(SystemExit) as exc,
    ):
        handle_var_command(_args(assignments=["items"], json=True, value_file="-"))

    assert exc.value.code == 0
    assert read_agent_output_variables(artifacts_dir) == {"items": ["first", "second"]}


def test_var_set_invalid_json_names_input_form(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_agent_artifacts(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args(assignments=["cfg"], json=True, value='{"broken":'))

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "invalid JSON for output variable cfg" in error
    assert "from --value" in error


def test_var_set_json_validation_errors_are_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_agent_artifacts(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args(assignments=[f"count={2**63}"], json=True))

    assert exc.value.code == 1
    assert "signed 64-bit range" in capsys.readouterr().err


def test_var_get_renders_canonical_block_form(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "output_variables": {
                    "status": "ok",
                    "cfg": {"retries": 3, "hosts": ["a", "b"]},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args(var_subcommand="get", format="pretty", color="never"))

    assert exc.value.code == 0
    assert capsys.readouterr().out == (
        "cfg:\n  hosts:\n    - a\n    - b\n  retries: 3\nstatus: ok\n"
    )


def test_var_get_json_is_compact_and_sorted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts_dir = _prepare_agent_artifacts(tmp_path, monkeypatch)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"z": None, "a": [2, True]}}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args(var_subcommand="get", format="json", color="never"))

    assert exc.value.code == 0
    assert capsys.readouterr().out == '{"a":[2,true],"z":null}\n'


@pytest.mark.parametrize(
    "assignments",
    (
        [],
        ["first", "second"],
        ["summary=old"],
    ),
)
def test_var_set_value_source_requires_one_bare_key(
    assignments: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_agent_artifacts(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args(assignments=assignments, value="new"))

    assert exc.value.code == 1
    assert "requires exactly one bare KEY" in capsys.readouterr().err


def test_var_set_missing_value_file_fails_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_agent_artifacts(tmp_path, monkeypatch)
    missing = tmp_path / "missing.txt"

    with pytest.raises(SystemExit) as exc:
        handle_var_command(_args(assignments=["body"], value_file=str(missing)))

    assert exc.value.code == 1
    assert f"value file not found: {missing}" in capsys.readouterr().err


def test_current_identity_prefers_meta_then_name_then_nonsentinel_agent(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "from-meta"}),
        encoding="utf-8",
    )

    assert (
        resolve_current_var_agent_name(
            str(artifacts),
            {"SASE_ARTIFACTS_DIR": str(artifacts), "SASE_AGENT": "1"},
        )
        == "from-meta"
    )
    assert (
        resolve_current_var_agent_name(
            str(artifacts),
            {
                "SASE_ARTIFACTS_DIR": str(artifacts),
                "SASE_AGENT_NAME": "from-env",
                "SASE_AGENT": "1",
            },
        )
        == "from-meta"
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "agent_meta.json").write_text("{}", encoding="utf-8")
    assert (
        resolve_current_var_agent_name(
            str(empty),
            {"SASE_ARTIFACTS_DIR": str(empty), "SASE_AGENT_NAME": "from-env"},
        )
        == "from-env"
    )
    assert (
        resolve_current_var_agent_name(
            str(empty),
            {"SASE_ARTIFACTS_DIR": str(empty), "SASE_AGENT": "legacy-name"},
        )
        == "legacy-name"
    )
    assert (
        resolve_current_var_agent_name(
            str(empty),
            {"SASE_ARTIFACTS_DIR": str(empty), "SASE_AGENT": "1"},
        )
        is None
    )


def _prepare_agent_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    return artifacts_dir

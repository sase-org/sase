"""Tests for the current-agent ``sase var`` handler."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.agent_output_variables import (
    MAX_OUTPUT_VARIABLE_VALUE_BYTES,
    read_agent_output_variables,
)
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

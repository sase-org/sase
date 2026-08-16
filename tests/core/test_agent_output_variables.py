"""Tests for agent output-variable parsing, validation, and storage."""

from __future__ import annotations

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

"""Tests for the ``sase var`` parser, handler, and storage helper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.core.agent_output_variables import (
    parse_output_variable_assignments,
    read_agent_output_variables,
    set_agent_output_variables,
)
from sase.main.parser import create_parser
from sase.main.var_handler import handle_var_command


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "var_subcommand": "set",
        "assignments": ["status=ok"],
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_parser_registers_var_set_assignments() -> None:
    parser = create_parser()

    args = parser.parse_args(["var", "set", "plan_file=sdd/plan.md", "status=ok"])

    assert args.command == "var"
    assert args.var_subcommand == "set"
    assert args.assignments == ["plan_file=sdd/plan.md", "status=ok"]


def test_parse_assignments_splits_on_first_equals() -> None:
    variables = parse_output_variable_assignments(["token=a=b=c", "_status=ok"])

    assert variables == {"token": "a=b=c", "_status": "ok"}


@pytest.mark.parametrize(
    "assignment", ["missing_equals", "1bad=value", "bad-key=value"]
)
def test_parse_assignments_rejects_invalid_input(assignment: str) -> None:
    with pytest.raises(ValueError):
        parse_output_variable_assignments([assignment])


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


def test_read_agent_output_variables_returns_string_values_only(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"ok": "yes", "skip": 123}}),
        encoding="utf-8",
    )

    assert read_agent_output_variables(artifacts_dir) == {"ok": "yes"}


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

"""Tests for the ``sase artifact-file`` parser and handler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.core.artifact_file_facade import read_artifact_file_index
from sase.main.artifact_file_handler import handle_artifact_file_command
from sase.main.parser import create_parser


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "artifact_file_subcommand": "create",
        "path": "artifact.md",
        "label": None,
        "kind": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_parser_registers_artifact_file_create_options() -> None:
    parser = create_parser()

    args = parser.parse_args(
        ["artifact-file", "create", "-p", "report.md", "-n", "Report", "-k", "markdown"]
    )

    assert args.command == "artifact-file"
    assert args.artifact_file_subcommand == "create"
    assert args.path == "report.md"
    assert args.label == "Report"
    assert args.kind == "markdown"


def test_parser_rejects_invalid_artifact_file_kind() -> None:
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["artifact-file", "create", "-p", "report.md", "-k", "bogus"])


def test_create_requires_agent_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "artifact.md"
    source.write_text("content", encoding="utf-8")
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        handle_artifact_file_command(_args(path=str(source)))

    assert exc.value.code == 1
    assert "SASE_AGENT=1 is required" in capsys.readouterr().err


def test_create_requires_artifacts_dir_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "artifact.md"
    source.write_text("content", encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with pytest.raises(SystemExit) as exc:
        handle_artifact_file_command(_args(path=str(source)))

    assert exc.value.code == 1
    assert "SASE_ARTIFACTS_DIR" in capsys.readouterr().err


def test_create_rejects_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260507120000"
    )
    artifacts_dir.mkdir(parents=True)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with pytest.raises(SystemExit) as exc:
        handle_artifact_file_command(_args(path=str(tmp_path / "missing.md")))

    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().err


def test_create_moves_file_and_records_association(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")
    artifacts_dir = (
        home
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260507120000"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "agent-one"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with pytest.raises(SystemExit) as exc:
        handle_artifact_file_command(
            _args(path=str(source), label="Release report", kind="markdown")
        )

    assert exc.value.code == 0
    assert not source.exists()
    output = capsys.readouterr().out
    assert "id: explicit:" in output
    assert "path: " in output

    rows = read_artifact_file_index(home / ".sase" / "artifacts" / "index.jsonl")
    assert len(rows) == 1
    artifact_file = rows[0]
    stored_path = Path(artifact_file.path)
    assert stored_path.is_file()
    assert stored_path.read_text(encoding="utf-8") == "# Report\n"
    assert artifact_file.label == "Release report"
    assert artifact_file.kind == "markdown"
    assert artifact_file.agent_artifacts_dir == str(artifacts_dir)
    assert artifact_file.project == "proj"
    assert artifact_file.workflow == "ace-run"
    assert artifact_file.raw_timestamp == "20260507120000"
    assert artifact_file.agent_name == "agent-one"
    assert artifact_file.explicit is True

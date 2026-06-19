"""Tests for sase.logs.project_creation_log."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.logs import project_creation_jsonl_path, project_creation_log_path
from sase.logs import project_creation_log
from sase.logs.project_creation_log import log_project_creation
from sase.workflows.commit.project_file_utils import create_project_file


def _write_project(name: str, content: str) -> Path:
    project_dir = sase_projects_dir() / name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{name}.sase"
    project_file.write_text(content, encoding="utf-8")
    return project_file


def _read_records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in project_creation_jsonl_path().read_text().splitlines()
    ]


class TestLogProjectCreation:
    def test_writes_both_files(self) -> None:
        log_project_creation(
            project="bob",
            project_file=str(sase_projects_dir() / "bob" / "bob.sase"),
        )

        assert project_creation_jsonl_path().exists()
        assert project_creation_log_path().exists()

    def test_jsonl_record_fields_and_stack(self, monkeypatch, tmp_path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SASE_BEAD_ID", "bead-123")

        log_project_creation(
            project="bob",
            project_file=str(sase_projects_dir() / "bob" / "bob.sase"),
        )

        record = _read_records()[-1]
        assert record["project"] == "bob"
        assert record["project_file"].endswith("/bob/bob.sase")
        assert record["cwd"] == str(tmp_path)
        assert "timestamp" in record
        assert isinstance(record["argv"], list)
        assert record["sase_env"]["SASE_BEAD_ID"] == "bead-123"  # type: ignore[index]
        assert "test_jsonl_record_fields_and_stack" in record["stack"]

    def test_alias_conflict_records_owner(self) -> None:
        _write_project(
            "bob-cli",
            "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: a\n",
        )

        log_project_creation(
            project="bob",
            project_file=str(sase_projects_dir() / "bob" / "bob.sase"),
        )

        record = _read_records()[-1]
        assert record["alias_conflict"] is True
        assert record["alias_conflict_owner"] == "bob-cli"
        assert "ALIAS CONFLICT with bob-cli" in project_creation_log_path().read_text()

    def test_no_alias_conflict_for_unaliased_project(self) -> None:
        _write_project(
            "bob-cli",
            "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: a\n",
        )

        log_project_creation(
            project="sase",
            project_file=str(sase_projects_dir() / "sase" / "sase.sase"),
        )

        record = _read_records()[-1]
        assert record["alias_conflict"] is False
        assert record["alias_conflict_owner"] is None

    def test_never_raises_on_write_error(self, monkeypatch) -> None:
        def _explode(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(project_creation_log, "_append_locked", _explode)

        log_project_creation(
            project="bob",
            project_file=str(sase_projects_dir() / "bob" / "bob.sase"),
        )


def test_create_project_file_logs_only_new_project_file() -> None:
    assert create_project_file("newproj") is True

    assert project_creation_jsonl_path().exists()
    lines = project_creation_jsonl_path().read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["project"] == "newproj"

    assert create_project_file("newproj") is True

    assert len(project_creation_jsonl_path().read_text().splitlines()) == 1

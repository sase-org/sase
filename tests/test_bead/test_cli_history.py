"""CLI coverage for per-bead event history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def _revision_chain(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "History target",
            IssueType.PLAN,
            notes="first note",
        )
        project.update(issue.id, notes="second note")
        project.update(issue.id, notes="third note")
    return issue.id


def _run_history(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> str:
    args = create_parser().parse_args(["bead", "history", *argv])
    bead_cli.handle_bead_history(args)
    return capsys.readouterr().out


def test_history_parser_contract_and_missing_id_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "history",
            "sase-1",
            "-F",
            "notes",
            "--field",
            "title",
            "-f",
            "full",
            "-n",
            "2",
        ]
    )

    assert args.id == "sase-1"
    assert args.field == ["notes", "title"]
    assert args.format == "full"
    assert args.limit == 2

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_history(create_parser().parse_args(["bead", "history"]))
    assert excinfo.value.code == 2
    assert "Error: issue ID is required" in capsys.readouterr().err


def test_history_compact_lists_event_metadata_and_changed_fields(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _revision_chain(project_dir)

    output = _run_history([issue_id], capsys)

    assert "issue_created" in output
    assert output.count("issue_updated") == 2
    assert "notes" in output
    assert all(line.count("·") == 3 for line in output.splitlines())


def test_history_full_makes_overwritten_note_revisions_readable(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _revision_chain(project_dir)

    output = _run_history(
        [issue_id, "--field", "notes", "--format", "full"],
        capsys,
    )

    assert "from: first note" in output
    assert "to: second note" in output
    assert "from: second note" in output
    assert "to: third note" in output
    assert "title:" not in output


def test_history_json_envelope_field_filter_and_newest_limit(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _revision_chain(project_dir)

    output = _run_history(
        [
            issue_id,
            "-F",
            "notes",
            "--format",
            "json",
            "--limit",
            "1",
        ],
        capsys,
    )
    payload = json.loads(output)

    assert set(payload) == {"issue_id", "schema_version", "entries"}
    assert payload["issue_id"] == issue_id
    assert payload["schema_version"] == 1
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["operation"] == "issue_updated"
    assert payload["entries"][0]["changes"] == [
        {
            "field": "notes",
            "from": "second note",
            "to": "third note",
        }
    ]


def test_history_unknown_id_exits_nonzero_with_clear_message(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        project.create("Bystander", IssueType.PLAN)

    with pytest.raises(SystemExit) as excinfo:
        _run_history(["missing"], capsys)

    assert excinfo.value.code == 1
    assert "Error: issue not found: missing" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--limit", "-n"])
def test_history_rejects_negative_limit(flag: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "history", "sase-1", flag, "-1"])

    assert excinfo.value.code == 2

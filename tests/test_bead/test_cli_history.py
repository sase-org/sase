"""CLI coverage for per-bead event history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead import cli_history
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


def test_lost_notes_parser_contract_and_restore_requires_scan_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["bead", "history", "sase-1", "-l", "-R"])
    assert args.id == "sase-1"
    assert args.lost_notes is True
    assert args.restore is True

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_history(
            create_parser().parse_args(["bead", "history", "sase-1", "--restore"])
        )
    assert excinfo.value.code == 2
    assert "--restore requires --lost-notes" in capsys.readouterr().err


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


def test_lost_notes_reports_overwrites_in_stable_order_and_supports_scope(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        first = project.create(
            "First",
            IssueType.PLAN,
            notes="first original",
        )
        second = project.create(
            "Second",
            IssueType.PLAN,
            notes="second original",
        )
        project.update(second.id, notes="second current")
        project.update(first.id, notes="first current")

    output = _run_history(["--lost-notes"], capsys)
    assert output.index(first.id) < output.index(second.id)
    assert f"{first.id}: 1 dropped revision" in output
    assert f"{second.id}: 1 dropped revision" in output

    scoped = _run_history(
        [second.id, "--lost-notes", "--format", "full"],
        capsys,
    )
    assert first.id not in scoped
    assert "second original" in scoped
    assert "second current" in scoped


def test_lost_notes_ignores_append_only_chain(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Append only",
            IssueType.PLAN,
            notes="retained",
        )
        project.update(issue.id, notes="retained\n\nnew")

    assert _run_history(["--lost-notes"], capsys) == "No lost note revisions found.\n"


def test_lost_notes_restore_is_provenanced_and_idempotent(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Restore target",
            IssueType.PLAN,
            notes="lost handoff",
        )
        project.update(issue.id, notes="current summary")

    monkeypatch.setattr(
        cli_history,
        "_confirm_lost_note_restore",
        lambda _count: True,
    )
    monkeypatch.setattr(
        cli_history,
        "_restored_date",
        lambda: "2026-07-27",
    )
    monkeypatch.setattr(
        "sase.bead.project._now",
        lambda: "2026-07-27T19:00:00Z",
    )

    output = _run_history(["--lost-notes", "--restore"], capsys)
    assert "Lost-note restoration preview:" in output
    assert "(restored 2026-07-27) lost handoff" in output
    assert "✓ Restored 1 lost note revision across 1 bead" in output

    with BeadProject(project_dir) as project:
        restored = project.show(issue.id).notes
    assert "current summary" in restored
    assert "(restored 2026-07-27) lost handoff" in restored

    assert _run_history(["--lost-notes"], capsys) == "No lost note revisions found.\n"


def test_lost_notes_declined_confirmation_writes_nothing(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Decline target",
            IssueType.PLAN,
            notes="do not restore",
        )
        project.update(issue.id, notes="current")
        before = project.show(issue.id).notes

    monkeypatch.setattr(
        cli_history,
        "_confirm_lost_note_restore",
        lambda _count: False,
    )
    output = _run_history(["--lost-notes", "--restore"], capsys)

    assert "cancelled; no changes applied" in output
    with BeadProject(project_dir) as project:
        assert project.show(issue.id).notes == before


def test_lost_notes_unknown_scoped_id_exits_nonzero(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        project.create("Bystander", IssueType.PLAN)

    with pytest.raises(SystemExit) as excinfo:
        _run_history(["missing", "--lost-notes"], capsys)

    assert excinfo.value.code == 1
    assert "Error: issue not found: missing" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--limit", "-n"])
def test_history_rejects_negative_limit(flag: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "history", "sase-1", flag, "-1"])

    assert excinfo.value.code == 2

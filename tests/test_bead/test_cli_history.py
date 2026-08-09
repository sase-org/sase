"""CLI coverage for per-bead event history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead import cli_history
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from tests.main.parser_cli_helpers import parse_sase_args


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


def _append_redundant_close_event(
    project_dir: Path,
    issue_id: str,
    *,
    timestamp: str = "2026-07-30T18:09:00Z",
) -> None:
    stream_path = project_dir / f"sdd/beads/events/streams/{issue_id}.jsonl"
    lines = stream_path.read_text(encoding="utf-8").splitlines()
    close_event = json.loads(lines[-1])
    assert close_event["operation"] == "issue_closed"
    close_event["event_id"] = (
        f"{issue_id}:000003:issue_closed:{issue_id}:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    )
    close_event["timestamp"] = timestamp
    close_event["payload"]["close_reason"] = None
    stream_path.write_text(
        "\n".join(
            [
                *lines,
                json.dumps(close_event, separators=(",", ":"), sort_keys=True),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _run_history(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> str:
    args = parse_sase_args(["bead", "history", *argv])
    bead_cli.handle_bead_history(args)
    return capsys.readouterr().out


def test_history_parser_contract_and_missing_id_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(
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
        bead_cli.handle_bead_history(parse_sase_args(["bead", "history"]))
    assert excinfo.value.code == 2
    assert "Error: issue ID is required" in capsys.readouterr().err


def test_lost_notes_parser_contract_and_restore_requires_scan_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse_sase_args(["bead", "history", "sase-1", "-l", "-R", "-y"])
    assert args.id == "sase-1"
    assert args.lost_notes is True
    assert args.restore is True
    assert args.yes is True

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_history(
            parse_sase_args(["bead", "history", "sase-1", "--restore"])
        )
    assert excinfo.value.code == 2
    assert "--restore requires --lost-notes" in capsys.readouterr().err


def test_lost_notes_yes_requires_restore(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_history(
            parse_sase_args(["bead", "history", "sase-1", "--yes"])
        )

    assert excinfo.value.code == 2
    assert "--yes requires --restore" in capsys.readouterr().err


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


def test_history_labels_redundant_duplicate_close_in_all_formats(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Duplicate close", IssueType.PLAN)
        closed = project.close([issue.id], reason="first close")[0]
    assert closed.closed_at is not None
    _append_redundant_close_event(project_dir, issue.id)

    label = f"issue_closed (redundant — already closed {closed.closed_at})"
    compact = _run_history([issue.id], capsys)
    assert label in compact

    full = _run_history([issue.id, "--format", "full"], capsys)
    assert label in full
    assert "Changes: (none)" in full

    payload = json.loads(_run_history([issue.id, "--format", "json"], capsys))
    redundant = [
        entry
        for entry in payload["entries"]
        if entry["operation"] == "issue_closed" and not entry["changes"]
    ]
    assert [entry["redundant"] for entry in payload["entries"]] == [
        False,
        False,
        True,
    ]
    assert len(redundant) == 1
    assert redundant[0]["event_id"] == (
        f"{issue.id}:000003:issue_closed:{issue.id}:"
        "0000000000000000000000000000000000000000000000000000000000000000"
    )
    assert redundant[0]["timestamp"] == "2026-07-30T18:09:00Z"
    assert redundant[0]["redundant"] is True
    assert redundant[0]["already_closed_at"] == closed.closed_at


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


def test_history_full_shows_reopen_clearing_closed_at(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Reopen target", IssueType.PLAN)
        closed = project.close([issue.id], reason="finished")[0]
        project.open(issue.id)

    output = _run_history(
        [issue.id, "--field", "closed_at", "--format", "full"],
        capsys,
    )

    assert closed.closed_at is not None
    assert "issue_opened" in output
    assert f"from: {closed.closed_at}" in output
    assert "to: (unset)" in output


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


def test_lost_notes_restore_yes_skips_non_tty_confirmation(
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
        lambda _count: pytest.fail("confirmation prompt should be skipped"),
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

    output = _run_history(["--lost-notes", "--restore", "--yes"], capsys)
    assert "✓ Restored 1 lost note revision across 1 bead" in output

    with BeadProject(project_dir) as project:
        restored = project.show(issue.id).notes
    assert "(restored 2026-07-27) lost handoff" in restored


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
        parse_sase_args(["bead", "history", "sase-1", flag, "-1"])

    assert excinfo.value.code == 2

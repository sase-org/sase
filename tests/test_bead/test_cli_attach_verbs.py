"""Phase attach_verbs: close -n, update -n, +1 -n, and sase bead attach.

Both flag states run against a temporary bead store. The flag-on tests cover
close/+1/update notes with inline references, per-bead update composition with
a single shared ingest, multi-file attach failures, stdin attach, and the +1
fast-path rule. The flag-off tests pin today's behavior plus the attach
enable hint.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.feature_flags import override_flags
from sase.main.parser import create_parser

PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

_HANDLERS = {
    "close": bead_cli.handle_bead_close,
    "+1": bead_cli.handle_bead_plus_one,
    "note": bead_cli.handle_bead_note,
    "snooze": bead_cli.handle_bead_snooze,
    "update": bead_cli.handle_bead_update,
    "attach": bead_cli.handle_bead_attach,
}


@pytest.fixture()
def work_dir(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate the CAS home and resolve ``@./`` refs inside the project."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    return project_dir


def _create_plan(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create("Attachment target", IssueType.PLAN)
    return issue.id


def _create_task(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Task target",
            IssueType.TASK,
            task_type="bug",
            size="small",
            created_by="creator.agent",
        )
    return issue.id


def _run(argv: list[str]) -> tuple[str, str, int]:
    """Run one ``sase bead`` argv, returning (stdout, stderr, exit code)."""
    args = create_parser().parse_args(["bead", *argv])
    handler = _HANDLERS[args.bead_subcommand]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            handler(args)
    except SystemExit as exc:
        code = int(exc.code or 0)
    return out.getvalue(), err.getvalue(), code


def _show(project_dir: Path, issue_id: str):
    with BeadProject(project_dir) as project:
        return project.show(issue_id)


def test_close_note_attaches_when_on(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD + b"pixels")
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        out, err, code = _run(["close", issue_id, "-n", "verified @./shot.png"])

    assert code == 0
    assert "Closed" in out
    assert "attached shot.png" in err
    closed = _show(project_dir, issue_id)
    assert closed.status is Status.CLOSED
    assert closed.notes[0].text == "verified @attachment:shot.png"
    assert closed.notes[0].attachments[0].name == "shot.png"


def test_close_note_stays_literal_when_off(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD)
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=False):
        out, err, code = _run(["close", issue_id, "-n", "verified @./shot.png"])

    assert code == 0
    assert "Closed" in out
    assert err == ""
    closed = _show(project_dir, issue_id)
    assert closed.notes[0].text == "verified @./shot.png"
    assert closed.notes[0].attachments == ()


def test_close_missing_attachment_writes_nothing(
    project_dir: Path, work_dir: Path
) -> None:
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run(["close", issue_id, "-n", "verified @./gone.png"])

    assert code == 1
    assert "nothing was written" in err
    assert _show(project_dir, issue_id).status is Status.OPEN


def test_plus_one_note_attachments_persist(project_dir: Path, work_dir: Path) -> None:
    data = PNG_HEAD + b"pixels"
    (work_dir / "shot.png").write_bytes(data)
    issue_id = _create_task(project_dir)

    with override_flags(bead_note_attachments=True):
        out, err, code = _run(
            ["+1", issue_id, "-a", "reporter.agent", "-n", "repro @./shot.png"]
        )

    assert code == 0
    assert "+1 recorded" in out
    assert "attached shot.png" in err
    task = _show(project_dir, issue_id)
    assert len(task.plus_one_evidence) == 1
    evidence = task.plus_one_evidence[0]
    assert evidence.note == "repro @attachment:shot.png"
    assert len(evidence.attachments) == 1
    assert evidence.attachments[0].name == "shot.png"
    assert evidence.attachments[0].size_bytes == len(data)
    # Bytes are content-addressed: deleting the source keeps them available.
    (work_dir / "shot.png").unlink()
    from sase.bead.attachments.store import LocalAttachmentStore

    digest = evidence.attachments[0].sha256
    assert LocalAttachmentStore().object_path(digest).read_bytes() == data
    reread = _show(project_dir, issue_id)
    assert reread.plus_one_evidence[0].attachments[0].sha256 == digest


def test_plus_one_note_attachments_on_snooze_wake(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD + b"pixels")
    issue_id = _create_task(project_dir)
    with override_flags(bead_note_attachments=True):
        # Far-future wake: the bead-test clock is pinned in the past.
        assert (
            _run(["snooze", issue_id, "-u", "2030-01-01T00:00:00Z", "-p", "1"])[2] == 0
        )
        out, err, code = _run(
            ["+1", issue_id, "-a", "reporter.agent", "-n", "repro @./shot.png"]
        )

    assert code == 0, err
    assert "+1 recorded" in out
    task = _show(project_dir, issue_id)
    assert task.status is Status.READY
    assert len(task.plus_one_evidence) == 1
    assert task.plus_one_evidence[0].note == "repro @attachment:shot.png"
    assert task.plus_one_evidence[0].attachments[0].name == "shot.png"
    # Snooze note plus the generated wake note; the wake note stays
    # attachment-free because its preset text has no @attachment tokens.
    assert len(task.notes) == 2
    assert task.notes[1].attachments == ()
    assert "Reopened by +1 threshold" in task.notes[1].text


def test_plus_one_no_manifest_evidence_unchanged(
    project_dir: Path, work_dir: Path
) -> None:
    issue_id = _create_task(project_dir)

    with override_flags(bead_note_attachments=True):
        out, _, code = _run(
            ["+1", issue_id, "-a", "reporter.agent", "-n", "plain repro"]
        )

    assert code == 0
    assert "+1 recorded" in out
    task = _show(project_dir, issue_id)
    assert task.plus_one_evidence[0].note == "plain repro"
    assert task.plus_one_evidence[0].attachments == ()


def test_plus_one_note_stays_literal_when_off(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD)
    issue_id = _create_task(project_dir)

    with override_flags(bead_note_attachments=False):
        out, err, code = _run(
            ["+1", issue_id, "-a", "reporter.agent", "-n", "repro @./shot.png"]
        )

    assert code == 0
    assert "+1 recorded" in out
    assert err == ""
    task = _show(project_dir, issue_id)
    assert task.plus_one_evidence[0].note == "repro @./shot.png"


def test_update_ingests_once_and_uniquifies_per_bead(
    project_dir: Path, work_dir: Path
) -> None:
    from sase.bead.attachments import authoring

    (work_dir / "a.png").write_bytes(PNG_HEAD + b"v1")
    first_id = _create_plan(project_dir)
    second_id = _create_plan(project_dir)
    with override_flags(bead_note_attachments=True):
        assert _run(["note", first_id, "-a", "amy", "first", "@./a.png"])[2] == 0
    (work_dir / "a.png").write_bytes(PNG_HEAD + b"v2-changed")

    real_ingest = authoring.ingest_path
    calls = []

    def _counting(path: object, *args: object, **kwargs: object):
        calls.append(str(path))
        return real_ingest(path, *args, **kwargs)

    with (
        override_flags(bead_note_attachments=True),
        patch.object(authoring, "ingest_path", _counting),
    ):
        out, err, code = _run(["update", first_id, second_id, "-n", "see @./a.png"])

    assert code == 0
    assert out.count("Updated issue") == 2
    # One shared ingest for both beads.
    assert len(calls) == 1
    first = _show(project_dir, first_id)
    second = _show(project_dir, second_id)
    # The first bead already has a.png, so the changed bytes uniquify.
    assert first.notes[-1].text == "see @attachment:a-2.png"
    assert second.notes[-1].text == "see @attachment:a.png"
    assert "stored as a-2.png" in err
    assert "attached a.png" in err


def test_update_note_and_fields_apply_together(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "a.png").write_bytes(PNG_HEAD)
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        _, _, code = _run(
            ["update", issue_id, "-s", "in_progress", "-n", "see @./a.png"]
        )

    assert code == 0
    updated = _show(project_dir, issue_id)
    assert updated.status is Status.IN_PROGRESS
    assert updated.notes[0].text == "see @attachment:a.png"


def test_update_failed_note_writes_nothing(project_dir: Path, work_dir: Path) -> None:
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run(
            ["update", issue_id, "-s", "in_progress", "-n", "see @./gone.png"]
        )

    assert code == 1
    assert "nothing was written" in err
    updated = _show(project_dir, issue_id)
    assert updated.notes == []
    assert updated.status is Status.OPEN


def test_attach_single_file_with_prose(project_dir: Path, work_dir: Path) -> None:
    data = PNG_HEAD + b"pixels"
    (work_dir / "shot.png").write_bytes(data)
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        out, err, code = _run(
            ["attach", issue_id, "./shot.png", "-a", "amy", "-n", "Crash shot"]
        )

    assert code == 0
    assert f"Attached: {issue_id}" in out
    assert "attached shot.png" in err
    notes = _show(project_dir, issue_id).notes
    assert notes[0].text == "Crash shot\n\n@attachment:shot.png"
    assert notes[0].attachments[0].name == "shot.png"
    assert notes[0].attachments[0].size_bytes == len(data)


def test_attach_name_option_renames_single_file(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD)
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run(["attach", issue_id, "./shot.png", "-N", "login.png"])

    assert code == 0
    assert "attached login.png" in err
    notes = _show(project_dir, issue_id).notes
    assert notes[0].text == "@attachment:login.png"
    assert notes[0].attachments[0].name == "login.png"


def test_attach_name_option_rejects_multiple_files(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "a.png").write_bytes(PNG_HEAD)
    (work_dir / "b.png").write_bytes(PNG_HEAD + b"b")
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run(["attach", issue_id, "./a.png", "./b.png", "-N", "one.png"])

    assert code == 1
    assert "-N/--name takes exactly one file" in err
    assert _show(project_dir, issue_id).notes == []


def test_attach_failed_file_writes_no_note(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "good.png").write_bytes(PNG_HEAD)
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run(["attach", issue_id, "./good.png", "./gone.png"])

    assert code == 1
    assert "nothing was written" in err
    assert _show(project_dir, issue_id).notes == []


def test_attach_stdin_requires_name_round_trips_bytes(
    project_dir: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run(["attach", issue_id, "-"])

    assert code == 1
    assert "-N/--name is required" in err
    assert _show(project_dir, issue_id).notes == []

    data = b'{"trace": true}\n'
    stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    with override_flags(bead_note_attachments=True):
        out, err, code = _run(["attach", issue_id, "-", "-N", "trace.json"])

    assert code == 0
    assert f"Attached: {issue_id}" in out
    assert "attached trace.json" in err
    notes = _show(project_dir, issue_id).notes
    assert notes[0].text == "@attachment:trace.json"
    assert notes[0].attachments[0].name == "trace.json"
    assert notes[0].attachments[0].size_bytes == len(data)
    from sase.bead.attachments.store import LocalAttachmentStore

    digest = notes[0].attachments[0].sha256
    assert LocalAttachmentStore().object_path(digest).read_bytes() == data


def test_attach_flag_off_refuses_with_hint(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD)
    issue_id = _create_plan(project_dir)

    with override_flags(bead_note_attachments=False):
        _, err, code = _run(["attach", issue_id, "./shot.png"])

    assert code == 1
    assert "sase flag enable bead_note_attachments" in err
    assert _show(project_dir, issue_id).notes == []


def test_fast_path_plus_one_with_embedded_at_stays_in_python_when_on() -> None:
    from sase.main import bead_fast_path

    argv = ["+1", "sase-1", "-n", "see @./shot.png here"]
    with (
        override_flags(bead_note_attachments=True),
        patch.object(bead_fast_path, "execute_bead_cli") as execute,
    ):
        assert bead_fast_path.try_handle_bead_fast_path(argv) is None
        execute.assert_not_called()


def test_fast_path_plus_one_without_at_keeps_fast_path_when_on() -> None:
    from sase.main import bead_fast_path

    argv = ["+1", "sase-1", "-n", "plain evidence"]
    with (
        override_flags(bead_note_attachments=True),
        patch.object(bead_fast_path, "execute_bead_cli", return_value=7) as execute,
    ):
        assert bead_fast_path.try_handle_bead_fast_path(argv) == 7
        execute.assert_called_once()

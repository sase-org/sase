"""CLI coverage for ``@<path>`` on bead free-text values."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.main.bead_fast_path import try_handle_bead_fast_path
from sase.main.entry import main as sase_main
from sase.main.parser import create_parser


def _issues_jsonl(project_dir: Path) -> Path:
    return project_dir / "sdd" / "beads" / "issues.jsonl"


def _flake_create_argv(*extra: str) -> list[str]:
    return [
        "bead",
        "create",
        "--title",
        "Visual flake",
        "--type",
        "task(flake)",
        "--size",
        "medium",
        "--field",
        "node_id=tests/foo.py::test_bar",
        "--field",
        "evidence=failed then passed",
        *extra,
    ]


def test_create_description_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    desc = tmp_path / "description-clean.md"
    contents = "full flake diagnosis\nwith a trailing newline\n"
    desc.write_text(contents, encoding="utf-8")
    at_token = f"@{desc}"

    bead_cli.handle_bead_create(
        create_parser().parse_args(_flake_create_argv("--description", at_token))
    )

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.description == contents
    assert task.description != at_token

    capsys.readouterr()
    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", task.id]))
    output = capsys.readouterr().out
    assert "full flake diagnosis" in output
    assert at_token not in output


def test_create_missing_description_file_creates_no_bead(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "gone.md"
    jsonl_path = _issues_jsonl(project_dir)
    before = jsonl_path.read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(
            create_parser().parse_args(
                _flake_create_argv("--description", f"@{missing}")
            )
        )

    assert exc_info.value.code == 1
    assert "file not found" in capsys.readouterr().err
    assert jsonl_path.read_bytes() == before
    with BeadProject(project_dir) as project:
        assert project.list_issues(issue_types=[IssueType.TASK]) == []


def test_entry_update_description_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desc = tmp_path / "desc.md"
    desc.write_text("expanded through the public entry\n", encoding="utf-8")
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Needs expansion", IssueType.TASK, task_type="bug", size="small"
        )
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "bead", "update", issue.id, "-d", f"@{desc}"],
    )

    with pytest.raises(SystemExit) as exc_info:
        sase_main()

    assert exc_info.value.code == 0
    with BeadProject(project_dir) as project:
        assert (
            project.show(issue.id).description == "expanded through the public entry\n"
        )


def test_update_and_note_at_path_skip_rust_fast_path() -> None:
    assert (
        try_handle_bead_fast_path(["update", "sase-1", "-d", "@/tmp/desc.md"]) is None
    )
    assert (
        try_handle_bead_fast_path(["update", "sase-1", "--note=@/tmp/note.md"]) is None
    )
    assert try_handle_bead_fast_path(["update", "sase-1", "-n", "note"]) is None
    assert try_handle_bead_fast_path(["update", "sase-1", "--notes=old"]) is None
    assert try_handle_bead_fast_path(["update", "sase-1", "-d", "@@literal"]) is None
    assert try_handle_bead_fast_path(["note", "sase-1", "@/tmp/note.md"]) is None
    assert try_handle_bead_fast_path(["close", "sase-1", "-n", "@/tmp/note.md"]) is None
    assert (
        try_handle_bead_fast_path(["close", "sase-1", "-r", "@/tmp/reason.md"]) is None
    )
    assert try_handle_bead_fast_path(["+1", "sase-1", "-n", "@/tmp/note.md"]) is None
    assert (
        try_handle_bead_fast_path(["snooze", "sase-1", "-r", "@/tmp/reason.md"]) is None
    )


def test_create_double_at_description_stores_literal(
    project_dir: Path,
) -> None:
    bead_cli.handle_bead_create(
        create_parser().parse_args(_flake_create_argv("--description", "@@literal"))
    )

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.description == "@literal"


def _parse(*parts: str) -> argparse.Namespace:
    return create_parser().parse_args(["bead", *parts])


def _plan_id(project_dir: Path, title: str = "Closeable") -> str:
    with BeadProject(project_dir) as project:
        return project.create(title, IssueType.PLAN).id


def _task_id(
    project_dir: Path,
    title: str = "Task",
    *,
    ready: bool = False,
) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create(
            title,
            IssueType.TASK,
            task_type="bug",
            size="small",
            created_by="creator.agent",
        )
        if ready:
            project.update(issue.id, status=Status.READY.value)
        return issue.id


def _write(tmp_path: Path, name: str, contents: str) -> Path:
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")
    return path


def test_close_note_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
) -> None:
    issue_id = _plan_id(project_dir)
    contents = "verified from file\nwith a trailing newline"
    note_path = _write(tmp_path, "close-note.md", contents)
    at_token = f"@{note_path}"

    bead_cli.handle_bead_close(_parse("close", issue_id, "-n", at_token))

    with BeadProject(project_dir) as project:
        closed = project.show(issue_id)
    assert closed.status is Status.CLOSED
    assert contents in closed.notes_text
    assert at_token not in closed.notes_text


def test_close_reason_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
) -> None:
    issue_id = _plan_id(project_dir)
    contents = "closed because the replacement shipped"
    reason_path = _write(tmp_path, "close-reason.md", contents)
    at_token = f"@{reason_path}"

    bead_cli.handle_bead_close(_parse("close", issue_id, "-r", at_token))

    with BeadProject(project_dir) as project:
        closed = project.show(issue_id)
    assert closed.status is Status.CLOSED
    assert closed.close_reason == contents
    assert closed.close_reason != at_token


def test_close_double_at_note_and_reason_store_literal(project_dir: Path) -> None:
    issue_id = _plan_id(project_dir)

    bead_cli.handle_bead_close(
        _parse("close", issue_id, "-n", "@@literal-note", "-r", "@@literal-reason")
    )

    with BeadProject(project_dir) as project:
        closed = project.show(issue_id)
    assert closed.status is Status.CLOSED
    assert closed.notes_text.endswith("] @literal-note")
    assert closed.close_reason == "@literal-reason"


def test_close_missing_note_file_mutates_nothing(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _plan_id(project_dir)
    missing = tmp_path / "gone.md"
    before = _issues_jsonl(project_dir).read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_close(_parse("close", issue_id, "-n", f"@{missing}"))

    assert exc_info.value.code == 1
    assert "file not found" in capsys.readouterr().err
    assert _issues_jsonl(project_dir).read_bytes() == before
    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.status is Status.OPEN
    assert issue.notes_text == ""


def test_close_missing_reason_file_mutates_nothing(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _plan_id(project_dir)
    missing = tmp_path / "gone.md"
    before = _issues_jsonl(project_dir).read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_close(_parse("close", issue_id, "-r", f"@{missing}"))

    assert exc_info.value.code == 1
    assert "file not found" in capsys.readouterr().err
    assert _issues_jsonl(project_dir).read_bytes() == before
    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    assert issue.status is Status.OPEN
    assert issue.close_reason is None


def test_reclose_reason_compares_expanded_text(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _plan_id(project_dir)
    recorded = "the recorded reason"
    bead_cli.handle_bead_close(_parse("close", issue_id, "-r", recorded))
    matching = _write(tmp_path, "same.md", recorded)
    different = _write(tmp_path, "other.md", "a different reason")

    bead_cli.handle_bead_close(_parse("close", issue_id, "-r", f"@{matching}"))
    with BeadProject(project_dir) as project:
        closed = project.show(issue_id)
    assert closed.status is Status.CLOSED
    assert closed.close_reason == recorded

    before = _issues_jsonl(project_dir).read_bytes()
    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_close(_parse("close", issue_id, "-r", f"@{different}"))

    assert exc_info.value.code == 1
    error = capsys.readouterr().err
    assert "already-closed" in error
    assert _issues_jsonl(project_dir).read_bytes() == before


def test_plus_one_note_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
) -> None:
    issue_id = _task_id(project_dir)
    contents = "reproduced on a clean tree"
    note_path = _write(tmp_path, "plus-one.md", contents)
    at_token = f"@{note_path}"

    bead_cli.handle_bead_plus_one(
        _parse("+1", issue_id, "-a", "reporter.agent", "-n", at_token)
    )

    with BeadProject(project_dir) as project:
        task = project.show(issue_id)
    assert [item.note for item in task.plus_one_evidence] == [contents]
    assert all(item.note != at_token for item in task.plus_one_evidence)


def test_plus_one_double_at_note_stores_literal(project_dir: Path) -> None:
    issue_id = _task_id(project_dir)

    bead_cli.handle_bead_plus_one(
        _parse("+1", issue_id, "-a", "reporter.agent", "-n", "@@literal")
    )

    with BeadProject(project_dir) as project:
        task = project.show(issue_id)
    assert [item.note for item in task.plus_one_evidence] == ["@literal"]


def test_plus_one_missing_note_file_mutates_nothing(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _task_id(project_dir)
    missing = tmp_path / "gone.md"
    before = _issues_jsonl(project_dir).read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_plus_one(
            _parse("+1", issue_id, "-a", "reporter.agent", "-n", f"@{missing}")
        )

    assert exc_info.value.code == 1
    assert "file not found" in capsys.readouterr().err
    assert _issues_jsonl(project_dir).read_bytes() == before
    with BeadProject(project_dir) as project:
        task = project.show(issue_id)
    assert task.plus_one_evidence == []
    assert task.status is Status.OPEN


def test_plus_one_missing_note_file_beats_verified_after_close_status_check(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _task_id(project_dir)
    missing = tmp_path / "gone.md"
    before = _issues_jsonl(project_dir).read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_plus_one(
            _parse(
                "+1",
                issue_id,
                "-n",
                f"@{missing}",
                "--verified-after-close",
            )
        )

    assert exc_info.value.code == 1
    error = capsys.readouterr().err
    assert "file not found" in error
    assert "requires a closed" not in error
    assert _issues_jsonl(project_dir).read_bytes() == before
    with BeadProject(project_dir) as project:
        task = project.show(issue_id)
    assert task.status is Status.OPEN
    assert task.plus_one_evidence == []


def test_snooze_reason_reads_at_path(
    project_dir: Path,
    tmp_path: Path,
) -> None:
    issue_id = _task_id(project_dir, ready=True)
    contents = "waiting on upstream"
    reason_path = _write(tmp_path, "snooze-reason.md", contents)
    at_token = f"@{reason_path}"

    bead_cli.handle_bead_snooze(
        _parse("snooze", issue_id, "-u", "2028-08-01T12:00:00Z", "-r", at_token)
    )

    with BeadProject(project_dir) as project:
        stored = project.show(issue_id)
    assert stored.status is Status.SNOOZED
    assert stored.snooze is not None
    assert stored.snooze.reason == contents
    assert stored.snooze.reason != at_token


def test_snooze_double_at_reason_stores_literal(project_dir: Path) -> None:
    issue_id = _task_id(project_dir, ready=True)

    bead_cli.handle_bead_snooze(
        _parse("snooze", issue_id, "-u", "2028-08-01T12:00:00Z", "-r", "@@literal")
    )

    with BeadProject(project_dir) as project:
        stored = project.show(issue_id)
    assert stored.snooze is not None
    assert stored.snooze.reason == "@literal"


def test_snooze_missing_reason_file_mutates_nothing(
    project_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _task_id(project_dir, ready=True)
    missing = tmp_path / "gone.md"
    before = _issues_jsonl(project_dir).read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_snooze(
            _parse(
                "snooze", issue_id, "-u", "2028-08-01T12:00:00Z", "-r", f"@{missing}"
            )
        )

    assert exc_info.value.code == 1
    assert "file not found" in capsys.readouterr().err
    assert _issues_jsonl(project_dir).read_bytes() == before
    with BeadProject(project_dir) as project:
        stored = project.show(issue_id)
    assert stored.status is Status.READY
    assert stored.snooze is None


def test_snooze_cancel_with_at_path_reports_cancel_conflict(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_id = _task_id(project_dir, ready=True)
    before = _issues_jsonl(project_dir).read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_snooze(
            _parse("snooze", issue_id, "--cancel", "-r", "@/nope.md")
        )

    assert exc_info.value.code == 1
    error = capsys.readouterr().err
    assert "--cancel takes no wake conditions" in error
    assert "file not found" not in error
    assert _issues_jsonl(project_dir).read_bytes() == before


_FLAG_ACTIONS = (
    argparse._StoreTrueAction,
    argparse._StoreFalseAction,
    argparse._CountAction,
    argparse._HelpAction,
)

# dests that expand ``@<path>`` into stored bead prose.
_EXPANDED_FREE_TEXT = frozenset(
    {
        ("+1", "note"),
        ("close", "note"),
        ("close", "reason"),
        ("create", "description"),
        ("create", "field"),
        ("note", "text"),
        ("snooze", "reason"),
        ("update", "description"),
        ("update", "note"),
    }
)

# dests that take a string but must stay literal.
_DELIBERATELY_LITERAL_FREE_TEXT = frozenset(
    {
        # Short identifiers, not prose.
        ("+1", "author"),
        ("+1", "ref"),
        ("create", "assignee"),
        ("create", "title"),
        ("create", "external_ref"),
        ("note", "author"),
        ("update", "assignee"),
        ("update", "design"),
        ("update", "external_ref"),
        ("update", "title"),
        # Structured tokens / names, not free-text bodies.
        ("create", "bug_id"),
        ("create", "model"),
        ("create", "patch"),
        ("create", "ref"),
        ("create", "type"),
        ("update", "model"),
        ("update", "remove_by"),
        # Selectors, times, paths, and filter names.
        ("apply-status", "operation_request_path"),
        ("apply-status", "operation_result_path"),
        ("close", "phases"),
        ("history", "field"),
        ("list", "task_type"),
        ("pages", "refresh", "bead"),
        ("search", "task_type"),
        ("show", "project"),
        ("snooze", "until"),
        ("sync-external", "project"),
        ("work", "artifacts_dir"),
        ("work", "cl_name"),
        ("work", "parent"),
    }
)


def _bead_parser() -> argparse.ArgumentParser:
    parser = create_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices["bead"]
    raise AssertionError("sase parser is missing the bead command")


def _iter_free_text_dests(
    parser: argparse.ArgumentParser,
    path: tuple[str, ...],
) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                found.extend(_iter_free_text_dests(child, (*path, name)))
            continue
        if action.dest in {"help"} or action.help is argparse.SUPPRESS:
            continue
        if isinstance(action, _FLAG_ACTIONS) or action.nargs == 0:
            continue
        if action.choices is not None:
            continue
        if action.type is not None and action.type is not str:
            continue
        if action.option_strings or action.dest == "text":
            found.append((*path, action.dest))
    return found


def test_every_bead_free_text_option_is_classified() -> None:
    """A new free-text option cannot land unclassified, which is how close -n slipped."""

    observed = frozenset(_iter_free_text_dests(_bead_parser(), ()))
    classified = _EXPANDED_FREE_TEXT | _DELIBERATELY_LITERAL_FREE_TEXT
    overlap = _EXPANDED_FREE_TEXT & _DELIBERATELY_LITERAL_FREE_TEXT
    assert overlap == frozenset()
    assert observed - classified == frozenset(), (
        "Unclassified free-text bead option(s); put each in "
        "_EXPANDED_FREE_TEXT or _DELIBERATELY_LITERAL_FREE_TEXT: "
        f"{sorted(observed - classified)!r}"
    )
    assert classified - observed == frozenset(), (
        "Classified free-text option(s) missing from the parser tree: "
        f"{sorted(classified - observed)!r}"
    )

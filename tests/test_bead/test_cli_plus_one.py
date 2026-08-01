"""Public CLI coverage for structured task +1 evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


def _suffix(issue_id: str) -> str:
    return issue_id.rsplit("-", 1)[-1]


def _args(
    issue_id: str,
    *,
    reporter: str = "reporter.agent",
    note: str = "Reproduced with a clean configuration",
    refs: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        id=issue_id,
        author=reporter,
        note=note,
        ref=refs,
    )


def test_plus_one_parser_requires_evidence_and_accepts_all_public_options() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "bead",
            "+1",
            "sase-42",
            "-a",
            "reporter.agent",
            "-n",
            "Independent reproduction",
            "-R",
            "research:202608/repro.md",
            "--ref",
            "bead:sase-related",
        ]
    )

    assert args.bead_subcommand == "+1"
    assert args.id == "sase-42"
    assert args.author == "reporter.agent"
    assert args.note == "Independent reproduction"
    assert args.ref == ["research:202608/repro.md", "bead:sase-related"]

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["bead", "+1", "sase-42"])
    assert exc_info.value.code == 2


def test_plus_one_accepts_shorthand_refs_and_promotes_draft_task(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            size=PhaseSize.MEDIUM,
            created_by="creator.agent",
        )

    bead_cli.handle_bead_plus_one(
        _args(
            _suffix(task.id),
            refs=[
                "research:202608/repro.md",
                "research:202608/repro.md",
                "bead:sase-related",
            ],
        )
    )

    with BeadProject(project_dir) as project:
        updated = project.show(task.id)
    assert updated.status is Status.READY
    assert updated.plus_one_count == 1
    assert updated.refs == ["research:202608/repro.md", "bead:sase-related"]
    assert updated.plus_one_evidence[0].refs == (
        "research:202608/repro.md",
        "bead:sase-related",
    )
    assert capsys.readouterr().out == (
        f"✓ +1 recorded: {task.id} — +1 independent report\n"
    )


def test_plus_one_public_entry_dispatch_uses_current_agent(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import globalize_owned_agent_name
    from sase.main import entry

    with BeadProject(project_dir) as project:
        task = project.create(
            "Public command",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
    monkeypatch.setenv("SASE_AGENT_NAME", "q8--code")
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "bead", "+1", task.id, "-n", "Public reproduction"],
    )

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 0
    with BeadProject(project_dir) as project:
        evidence = project.show(task.id).plus_one_evidence
    assert [item.reporter for item in evidence] == [
        globalize_owned_agent_name("q8--code")
    ]


def test_plus_one_repeat_is_noop_with_note_guidance(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )

    bead_cli.handle_bead_plus_one(_args(task.id))
    capsys.readouterr()
    bead_cli.handle_bead_plus_one(_args(task.id, note="Later detail"))

    output = capsys.readouterr().out
    assert f"· Unchanged: {task.id}" in output
    assert "use `sase bead note` for supplementary evidence" in output
    assert output.endswith("(+1)\n")
    with BeadProject(project_dir) as project:
        assert project.show(task.id).plus_one_count == 1


def test_plus_one_rejects_non_task_without_mutation(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        plan = project.create("Not a task", IssueType.PLAN)
        before = (project.beads_dir / "issues.jsonl").read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_plus_one(_args(plan.id))

    assert exc_info.value.code == 1
    assert "only applies to task beads" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert (project.beads_dir / "issues.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    ("issue_id", "note", "expected"),
    [
        ("missing", "Evidence", "issue not found: missing"),
        ("unused", "   ", "note cannot be empty or blank"),
    ],
)
def test_plus_one_reports_missing_task_and_blank_evidence(
    issue_id: str,
    note: str,
    expected: str,
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if issue_id == "unused":
        with BeadProject(project_dir) as project:
            issue_id = project.create(
                "Needs evidence",
                IssueType.TASK,
                size=PhaseSize.SMALL,
                created_by="creator.agent",
            ).id

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_plus_one(_args(issue_id, note=note))

    assert exc_info.value.code == 1
    assert expected in capsys.readouterr().err


def test_plus_one_uses_canonical_commit_and_deferred_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Published evidence",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
    auto_commit = MagicMock(return_value=True)
    push = MagicMock()
    monkeypatch.setattr("sase.bead.cli_crud.auto_commit_bead_store", auto_commit)
    monkeypatch.setattr("sase.bead.cli_common._push_committed_bead_store", push)

    bead_cli.handle_bead_plus_one(_args(task.id))

    auto_commit.assert_called_once_with(
        f"chore(beads): +1 {task.id}",
        push_after_commit=False,
        already_locked=False,
    )
    push.assert_called_once_with()


def test_plus_one_idempotent_retry_skips_commit_and_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Published evidence",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
        project.plus_one(
            task.id,
            "First report",
            reporter="reporter.agent",
        )
    auto_commit = MagicMock(return_value=True)
    push = MagicMock()
    monkeypatch.setattr("sase.bead.cli_crud.auto_commit_bead_store", auto_commit)
    monkeypatch.setattr("sase.bead.cli_common._push_committed_bead_store", push)

    bead_cli.handle_bead_plus_one(_args(task.id, note="Retry"))

    auto_commit.assert_not_called()
    push.assert_not_called()

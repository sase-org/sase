"""Public CLI coverage for structured task +1 evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, PhaseSize, Resolution, Status
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
    verified_after_close: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        id=issue_id,
        author=reporter,
        note=note,
        ref=refs,
        verified_after_close=verified_after_close,
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


def test_plus_one_parser_accepts_verified_after_close_flag() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "bead",
            "+1",
            "sase-42",
            "-n",
            "Reproduced after the fix",
            "--verified-after-close",
        ]
    )
    assert args.verified_after_close is True

    default_args = parser.parse_args(["bead", "+1", "sase-42", "-n", "Reproduced"])
    assert default_args.verified_after_close is False


def test_plus_one_verified_after_close_reopens_and_clears_assignee(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Fixed task",
            IssueType.TASK,
            task_type="bug",
            size=PhaseSize.SMALL,
            assignee="finisher.agent",
            created_by="creator.agent",
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)

    bead_cli.handle_bead_plus_one(_args(task.id, verified_after_close=True))

    with BeadProject(project_dir) as project:
        updated = project.show(task.id)
    assert updated.status is Status.READY
    assert updated.assignee == ""
    output = capsys.readouterr().out
    assert "+1 recorded" in output
    assert "withheld" not in output


def test_plus_one_verified_after_close_rejects_non_closed_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Open task",
            IssueType.TASK,
            task_type="bug",
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
        before = (project.beads_dir / "issues.jsonl").read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_plus_one(_args(task.id, verified_after_close=True))

    assert exc_info.value.code == 1
    assert "requires a closed bead" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert (project.beads_dir / "issues.jsonl").read_bytes() == before


def test_plus_one_withheld_reopen_reports_and_leaves_bead_closed(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_crud_evidence.resolve_observation_window_start",
        lambda: "2020-01-01T00:00:00Z",
    )
    with BeadProject(project_dir) as project:
        task = project.create(
            "Fixed task",
            IssueType.TASK,
            task_type="bug",
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)
        closed_at = project.show(task.id).closed_at

    bead_cli.handle_bead_plus_one(_args(task.id, reporter="stale.reporter"))

    with BeadProject(project_dir) as project:
        updated = project.show(task.id)
    assert updated.status is Status.CLOSED
    assert "stale.reporter" in updated.notes_text
    assert "withheld" in updated.notes_text

    output = capsys.readouterr().out
    assert "withheld" in output
    assert "--verified-after-close" in output
    assert "sase bead open" in output
    assert closed_at is not None
    assert closed_at in output


def test_plus_one_malformed_agent_metadata_falls_back_and_reopens(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "malformed.agent", "run_started_at": "not-an-instant"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "malformed.agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setattr(
        "sase.agent.identity.current_instant",
        lambda: "2099-01-01T00:00:00.000000Z",
    )

    with BeadProject(project_dir) as project:
        task = project.create(
            "Fixed task",
            IssueType.TASK,
            task_type="bug",
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)

    bead_cli.handle_bead_plus_one(_args(task.id, reporter="malformed.reporter"))

    with BeadProject(project_dir) as project:
        updated = project.show(task.id)
    assert updated.status is Status.READY
    assert updated.assignee == ""


def test_plus_one_human_fallback_uses_current_time_and_reopens(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    with BeadProject(project_dir) as project:
        task = project.create(
            "Fixed task",
            IssueType.TASK,
            task_type="bug",
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)

    bead_cli.handle_bead_plus_one(_args(task.id, reporter="human.reporter"))

    with BeadProject(project_dir) as project:
        updated = project.show(task.id)
    assert updated.status is Status.READY


def test_plus_one_accepts_shorthand_refs_and_promotes_draft_task(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            task_type="bug",
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
            task_type="bug",
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
            task_type="bug",
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
                task_type="bug",
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
            task_type="bug",
            size=PhaseSize.SMALL,
            created_by="creator.agent",
        )
    auto_commit = MagicMock(return_value=True)
    push = MagicMock()
    monkeypatch.setattr(
        "sase.bead.cli_crud_evidence.auto_commit_bead_store", auto_commit
    )
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
            task_type="bug",
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
    monkeypatch.setattr(
        "sase.bead.cli_crud_evidence.auto_commit_bead_store", auto_commit
    )
    monkeypatch.setattr("sase.bead.cli_common._push_committed_bead_store", push)

    bead_cli.handle_bead_plus_one(_args(task.id, note="Retry"))

    auto_commit.assert_not_called()
    push.assert_not_called()

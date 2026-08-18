"""Python facade and CLI coverage for task beads and ready status."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.db import create_issue, get_issue, init_db
from sase.bead.jsonl import export_to_jsonl, import_from_jsonl
from sase.bead.model import Issue, IssueType, PhaseSize, Status
from sase.bead.project import BeadProject
from sase.core.bead_wire import issue_from_dict
from sase.main.parser import create_parser

NOW = "2026-07-30T00:00:00Z"


def test_parse_type_arg_accepts_bare_task() -> None:
    assert bead_cli._parse_type_arg("task") == (IssueType.TASK, None, None, None, "")


def test_create_task_accepts_size_and_prints_type(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Investigate follow-up",
            "--type",
            "task",
            "--size",
            "medium",
        ]
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.parent_id is None
    assert task.status is Status.OPEN
    assert task.size is PhaseSize.MEDIUM
    assert capsys.readouterr().out == (
        f"Created task: {task.id} — Investigate follow-up\n"
    )


def test_create_task_records_acting_agent(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import globalize_owned_agent_name

    monkeypatch.setenv("SASE_AGENT_NAME", "q8--code")
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Agent follow-up",
            "--type",
            "task",
            "--size",
            "small",
        ]
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.created_by == globalize_owned_agent_name("q8--code")


def test_create_task_without_agent_records_store_owner(project_dir: Path) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Human follow-up",
            "--type",
            "task",
            "--size",
            "small",
        ]
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.created_by == task.owner


def test_create_phase_inherits_parent_creator(project_dir: Path) -> None:
    creator = "bbugyi200.athena.q8--plan"
    with BeadProject(project_dir) as project:
        parent = project.create(
            "Attributed epic",
            IssueType.PLAN,
            created_by=creator,
        )
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Inherited phase",
            "--type",
            f"phase({parent.id})",
        ]
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as project:
        phase = project.list_issues(issue_types=[IssueType.PHASE])[0]
    assert phase.created_by == creator


def test_create_task_requires_size(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        ["bead", "create", "--title", "Missing size", "--type", "task"]
    )

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(args)

    assert exc_info.value.code == 1
    assert "task beads require -z/--size" in capsys.readouterr().err
    with BeadProject(project_dir) as project:
        assert project.list_issues(issue_types=[IssueType.TASK]) == []


def test_create_plan_prefers_frontmatter_proposer(project_dir: Path) -> None:
    creator = "bbugyi200.athena.q8--plan"
    plan_path = project_dir / "attributed.md"
    plan_path.write_text(
        f"---\ntier: tale\nproposed_by: {creator}\n---\n# Plan\n",
        encoding="utf-8",
    )
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Attributed plan",
            "--type",
            f"plan({plan_path})",
        ]
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as project:
        plan = project.list_issues(issue_types=[IssueType.PLAN])[0]
    assert plan.created_by == creator


@pytest.mark.parametrize("subcommand", ["list", "search"])
def test_query_parsers_accept_task_and_ready(subcommand: str) -> None:
    argv = ["bead", subcommand]
    if subcommand == "search":
        argv.append("follow-up")
    argv.extend(["--status", "ready", "--type", "task"])

    args = create_parser().parse_args(argv)

    assert args.status == ["ready"]
    assert args.type == ["task"]


def test_ready_stats_and_detail_handlers_render_task_semantics(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        first = project.create(
            "Ready follow-up",
            IssueType.TASK,
            size=PhaseSize.MEDIUM,
        )
        blocked = project.create(
            "Blocked follow-up", IssueType.TASK, size=PhaseSize.SMALL
        )
        project.update(first.id, status="ready")
        project.update(blocked.id, status="ready")
        project.add_dependency(blocked.id, first.id)

    bead_cli.handle_bead_ready(create_parser().parse_args(["bead", "ready"]))
    ready_output = capsys.readouterr().out
    assert f"◇  M {first.id} · Ready follow-up" in ready_output
    assert blocked.id not in ready_output
    assert "Ready: 1 task bead with no active blockers" in ready_output

    bead_cli.handle_bead_stats(create_parser().parse_args(["bead", "stats"]))
    stats_output = capsys.readouterr().out
    assert "  Ready:       2" in stats_output
    assert "  Tasks:       2" in stats_output

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", first.id]))
    detail_output = capsys.readouterr().out
    assert "Type: task" in detail_output
    assert "Size: medium" in detail_output


def test_ready_handler_uses_task_specific_empty_message(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        project.create("Draft follow-up", IssueType.TASK, size=PhaseSize.SMALL)

    bead_cli.handle_bead_ready(create_parser().parse_args(["bead", "ready"]))

    assert capsys.readouterr().out == (
        "No ready task beads (epic work is preassigned at launch).\n"
    )


def test_jsonl_round_trip_preserves_ready_task_size(tmp_path: Path) -> None:
    source = init_db(tmp_path / "source.db")
    target = init_db(tmp_path / "target.db")
    path = tmp_path / "issues.jsonl"
    try:
        task = Issue(
            id="task-1",
            title="Ready follow-up",
            status=Status.READY,
            issue_type=IssueType.TASK,
            size=PhaseSize.LARGE,
            created_at=NOW,
            updated_at=NOW,
        )
        create_issue(source, task)

        export_to_jsonl(source, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "ready"
        assert payload["issue_type"] == "task"
        assert payload["size"] == "large"

        import_from_jsonl(path, target)
        loaded = get_issue(target, task.id)
        assert loaded is not None
        assert loaded.status is Status.READY
        assert loaded.issue_type is IssueType.TASK
        assert loaded.size is PhaseSize.LARGE
    finally:
        source.close()
        target.close()


def test_rust_wire_dict_decodes_ready_task() -> None:
    issue = issue_from_dict(
        {
            "id": "task-1",
            "title": "Ready follow-up",
            "status": "ready",
            "issue_type": "task",
            "size": "small",
        }
    )

    assert issue.status is Status.READY
    assert issue.issue_type is IssueType.TASK
    assert issue.size is PhaseSize.SMALL

"""Typed task creation, field values, rendered body, and reading filters."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.db import create_issue, get_issue, init_db
from sase.bead.jsonl import export_to_jsonl, import_from_jsonl
from sase.bead.model import Issue, IssueType, PhaseSize, Status
from sase.bead.project import BeadProject
from sase.bead_pages.rendering_identity import render_prose_sections
from sase.core.bead_wire import issue_from_dict
from sase.main.parser import create_parser
from sase.task_types import (
    UNTYPED_TASK_TYPE,
    TaskTypeCreateError,
    parse_field_args,
    render_task_type_display_block,
    resolve_created_task_type,
)
from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)
from tests.main.parser_cli_helpers import parse_sase_args

NOW = "2026-07-30T00:00:00Z"


def _create_typed_task(
    title: str = "Flaky retry",
    *,
    extra: list[str] | None = None,
) -> None:
    argv = [
        "bead",
        "create",
        "--title",
        title,
        "--type",
        "task(flake)",
        "--size",
        "medium",
        "--field",
        "node_id=tests/foo.py::test_bar",
        "--field",
        "evidence=failed then passed",
    ]
    if extra:
        argv.extend(extra)
    bead_cli.handle_bead_create(create_parser().parse_args(argv))


def test_parse_type_arg_accepts_task_slug() -> None:
    assert bead_cli._parse_type_arg("task(flake)") == (
        IssueType.TASK,
        None,
        None,
        "flake",
    )


def test_parse_type_arg_rejects_empty_task_slug(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        bead_cli._parse_type_arg("task()")

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "invalid --type value: task()" in err
    assert "task(<slug>)" in err


def test_parse_field_args_reads_at_path(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("failed then passed\n", encoding="utf-8")

    assert parse_field_args(
        ["node_id=tests/foo.py::test_bar", f"evidence=@{evidence}"]
    ) == {
        "node_id": "tests/foo.py::test_bar",
        "evidence": "failed then passed\n",
    }


def test_parse_field_args_rejects_duplicate_keys() -> None:
    with pytest.raises(TaskTypeCreateError, match="duplicate --field key: node_id"):
        parse_field_args(["node_id=one", "node_id=two"])


def test_parse_field_args_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "gone.txt"
    with pytest.raises(TaskTypeCreateError, match="file not found") as exc_info:
        parse_field_args([f"evidence=@{missing}"])
    assert isinstance(exc_info.value, TaskTypeCreateError)


def test_parse_field_args_double_at_stores_literal() -> None:
    assert parse_field_args(["evidence=@@literal"]) == {"evidence": "@literal"}


def test_create_typed_task_stores_fields_not_description(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create_typed_task()

    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]
    assert task.task_type == "flake"
    assert task.task_type_fields["node_id"] == "tests/foo.py::test_bar"
    assert task.task_type_fields["evidence"] == "failed then passed"
    assert "Flake report" not in task.description
    assert capsys.readouterr().out == f"Created task: {task.id} — Flaky retry\n"


def test_create_typed_task_rejects_unknown_type(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Unknown",
            "--type",
            "task(not_a_real_type)",
            "--size",
            "small",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(args)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "unknown task type 'not_a_real_type'" in err
    assert "Available agent-creatable types:" in err
    assert "flake" in err
    with BeadProject(project_dir) as project:
        assert project.list_issues(issue_types=[IssueType.TASK]) == []


def test_create_typed_task_reports_every_field_problem(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Incomplete flake",
            "--type",
            "task(flake)",
            "--size",
            "small",
            "--field",
            "unknown_field=x",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(args)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "invalid task type fields:" in err
    assert "unknown_field" in err
    assert "node_id" in err
    assert "evidence" in err


def test_create_typed_task_rejects_fields_on_bare_task(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Untyped with fields",
            "--type",
            "task",
            "--size",
            "small",
            "--field",
            "node_id=tests/foo.py::test_bar",
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_create(args)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "task beads require -T 'task(<slug>)'" in err
    assert "bug" in err


def test_resolve_created_task_type_rejects_empty_slug() -> None:
    with pytest.raises(
        TaskTypeCreateError, match=r"task beads require -T 'task\(<slug>\)'"
    ):
        resolve_created_task_type("", {})


def test_create_unknown_type_names_snapshot_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.task_types.fields._snapshot_entry",
        lambda slug: (
            {"task_type": slug, "package": "sase-github"} if slug == "github" else None
        ),
    )
    empty = TaskTypeRegistry(records=(), diagnostics=())

    with pytest.raises(TaskTypeCreateError, match="sase plugin install sase-github"):
        resolve_created_task_type("github", {}, registry=empty)


def test_create_rejects_agent_uncreatable_type() -> None:
    record = TaskTypeRecord(
        task_type="github",
        spec={
            "schema_version": 1,
            "task_type": "github",
            "label": "GitHub",
            "summary": "Mirrored GitHub issue.",
            "when_to_use": "Agents never create this type.",
            "agent_creatable": False,
            "fields": [],
        },
        digest="a" * 64,
        provenance=TaskTypeProvenance(
            source="plugin",
            name="sase_github",
            package="sase-github",
            version="0.1.0",
        ),
    )
    registry = TaskTypeRegistry(records=(record,), diagnostics=())

    with pytest.raises(
        TaskTypeCreateError, match="cannot be created by agents"
    ) as exc_info:
        resolve_created_task_type("github", {}, registry=registry)

    assert "Agents never create this type." in str(exc_info.value)
    assert "reserved for the providing plugin" not in str(exc_info.value)


def test_show_appends_rendered_body_below_description(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Flaky retry",
            "--type",
            "task(flake)",
            "--size",
            "medium",
            "--description",
            "Found while landing the retry patch.",
            "--field",
            "node_id=tests/foo.py::test_bar",
            "--field",
            "evidence=failed then passed",
        ]
    )
    bead_cli.handle_bead_create(args)
    capsys.readouterr()
    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]

    bead_cli.handle_bead_show(create_parser().parse_args(["bead", "show", task.id]))
    output = capsys.readouterr().out
    assert "Found while landing the retry patch." in output
    desc_at = output.index("Found while landing the retry patch.")
    assert output.index("## Flake report") > desc_at
    assert "`tests/foo.py::test_bar`" in output
    assert "failed then passed" in output


def test_show_json_includes_task_type_fields(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create_typed_task()
    capsys.readouterr()
    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]

    bead_cli.handle_bead_show(
        create_parser().parse_args(["bead", "show", task.id, "--format", "json"])
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["issue"]["task_type"] == "flake"
    assert payload["issue"]["task_type_fields"]["node_id"] == "tests/foo.py::test_bar"


def test_unknown_type_renders_degraded_key_values() -> None:
    issue = Issue(
        id="task-1",
        title="Mirrored",
        issue_type=IssueType.TASK,
        task_type="github",
        task_type_fields={"external": "sase-org/sase#1"},
    )

    rendered = render_task_type_display_block(
        issue, registry=TaskTypeRegistry(records=(), diagnostics=())
    )

    assert "Task type: github (not installed on this machine)" in rendered
    assert "**external:** sase-org/sase#1" in rendered


def test_known_github_type_without_body_template_does_not_degrade() -> None:
    record = TaskTypeRecord(
        task_type="github",
        spec={
            "schema_version": 1,
            "task_type": "github",
            "label": "GitHub",
            "summary": "A GitHub issue mirrored into a task bead.",
            "when_to_use": "Agents never create this type.",
            "agent_creatable": False,
            "fields": [],
        },
        digest="a" * 64,
        provenance=TaskTypeProvenance(
            source="plugin",
            name="github",
            package="sase-github",
            version="0.1.0",
        ),
    )
    issue = Issue(
        id="task-1",
        title="Mirrored",
        issue_type=IssueType.TASK,
        task_type="github",
    )

    rendered = render_task_type_display_block(
        issue, registry=TaskTypeRegistry(records=(record,), diagnostics=())
    )

    assert rendered == ""
    assert "not installed on this machine" not in rendered


def test_bead_page_appends_body_below_description() -> None:
    issue = Issue(
        id="sase-task",
        title="Flaky",
        issue_type=IssueType.TASK,
        task_type="flake",
        description="Found while landing.",
        task_type_fields={
            "node_id": "tests/foo.py::test_bar",
            "evidence": "failed then passed",
        },
    )

    rendered = "\n".join(render_prose_sections(issue))

    assert rendered.index("Found while landing.") < rendered.index("Flake report")


def test_update_task_type_is_rejected(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create_typed_task()
    capsys.readouterr()
    with BeadProject(project_dir) as project:
        task = project.list_issues(issue_types=[IssueType.TASK])[0]

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_update(
            create_parser().parse_args(
                ["bead", "update", task.id, "--task-type", "bug"]
            )
        )

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "task_type is immutable" in err
    assert "recreate" in err


def _seed_untyped_task(project_dir: Path, title: str) -> None:
    with BeadProject(project_dir) as project:
        beads_dir = project.beads_dir
    issue = {
        "id": "legacy-untyped",
        "title": title,
        "status": "open",
        "issue_type": "task",
        "size": "small",
        "parent_id": None,
        "created_at": NOW,
        "updated_at": NOW,
        "dependencies": [],
    }
    issues_path = beads_dir / "issues.jsonl"
    existing = issues_path.read_text(encoding="utf-8")
    issues_path.write_text(existing + json.dumps(issue) + "\n", encoding="utf-8")
    events_dir = beads_dir / "events"
    if events_dir.exists():
        shutil.rmtree(events_dir)


def test_list_and_search_filter_by_task_type(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create_typed_task("Typed flake")
    _seed_untyped_task(project_dir, "Legacy follow-up")
    capsys.readouterr()

    bead_cli.handle_bead_list(
        parse_sase_args(["bead", "list", "--format", "json", "--task-type", "flake"])
    )
    typed = json.loads(capsys.readouterr().out)
    assert [row["title"] for row in typed["results"]] == ["Typed flake"]
    assert typed["results"][0]["task_type"] == "flake"

    bead_cli.handle_bead_list(
        parse_sase_args(["bead", "list", "--format", "json", "--task-type", "untyped"])
    )
    untyped = json.loads(capsys.readouterr().out)
    assert [row["title"] for row in untyped["results"]] == ["Legacy follow-up"]
    assert untyped["results"][0].get("task_type", "") == ""

    bead_cli.handle_bead_search(
        parse_sase_args(
            [
                "bead",
                "search",
                "follow",
                "--format",
                "json",
                "--task-type",
                UNTYPED_TASK_TYPE,
            ]
        )
    )
    searched = json.loads(capsys.readouterr().out)
    assert [row["issue"]["title"] for row in searched["results"]] == [
        "Legacy follow-up"
    ]


def test_query_parsers_accept_repeatable_task_type() -> None:
    args = parse_sase_args(["bead", "list", "--task-type", "flake", "-T", "untyped"])

    assert args.task_type == ["flake", "untyped"]


def test_jsonl_and_wire_round_trip_preserve_task_type(tmp_path: Path) -> None:
    source = init_db(tmp_path / "source.db")
    target = init_db(tmp_path / "target.db")
    path = tmp_path / "issues.jsonl"
    try:
        task = Issue(
            id="task-1",
            title="Typed follow-up",
            status=Status.OPEN,
            issue_type=IssueType.TASK,
            size=PhaseSize.MEDIUM,
            created_at=NOW,
            updated_at=NOW,
            task_type="flake",
            task_type_fields={"node_id": "tests/foo.py::test_bar"},
        )
        create_issue(source, task)
        export_to_jsonl(source, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["task_type"] == "flake"
        assert payload["task_type_fields"]["node_id"] == "tests/foo.py::test_bar"

        import_from_jsonl(path, target)
        loaded = get_issue(target, task.id)
        assert loaded is not None
        assert loaded.task_type == "flake"
        assert loaded.task_type_fields["node_id"] == "tests/foo.py::test_bar"
    finally:
        source.close()
        target.close()

    decoded = issue_from_dict(
        {
            "id": "task-1",
            "title": "Typed follow-up",
            "status": "open",
            "issue_type": "task",
            "task_type": "flake",
            "task_type_fields": {"evidence": "failed then passed"},
        }
    )
    assert decoded.task_type == "flake"
    assert decoded.task_type_fields == {"evidence": "failed then passed"}

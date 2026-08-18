"""CLI round-trip coverage for flag beads.

Mirrors sase-core's ``create_round_trips_a_flag_bead`` and
``flag_bead_create_update_and_close_round_trip`` at the Python CLI layer:
create, show, list, update, and close all have to agree about what a flag
bead is.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import FlagRecord, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Create a fresh beads project and route the CLI's lookups at it."""
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)
    yield tmp_path


def test_parse_type_arg_accepts_the_flag_form() -> None:
    result = bead_cli._parse_type_arg("flag(demo_key,2026-12-01,0.19.0)")

    assert result == (
        IssueType.FLAG,
        None,
        None,
        FlagRecord(
            key="demo_key", remove_by_date="2026-12-01", remove_by_release="0.19.0"
        ),
        "",
    )


def test_parse_type_arg_rejects_wrong_flag_arity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        bead_cli._parse_type_arg("flag(demo_key,2026-12-01)")

    assert "flag() expects exactly 3 arguments, got 2" in capsys.readouterr().err


def _create_flag_bead(project_dir: Path) -> str:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Retire demo_key",
            "--type",
            "flag(demo_key,2026-12-01,0.19.0)",
        ]
    )
    bead_cli.handle_bead_create(args)
    with BeadProject(project_dir) as project:
        issues = project.list_issues(issue_types=[IssueType.FLAG])
    assert len(issues) == 1
    return issues[0].id


def test_create_prints_the_flag_type_and_stores_thresholds(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "--title",
            "Retire demo_key",
            "--type",
            "flag(demo_key,2026-12-01,0.19.0)",
        ]
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as project:
        issue = project.list_issues(issue_types=[IssueType.FLAG])[0]
    assert issue.flag == FlagRecord(
        key="demo_key", remove_by_date="2026-12-01", remove_by_release="0.19.0"
    )
    assert issue.parent_id is None
    assert capsys.readouterr().out == f"Created flag: {issue.id} — Retire demo_key\n"


def test_show_json_reports_the_flag_section(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_id = _create_flag_bead(project_dir)
    capsys.readouterr()  # discard the "Created flag: ..." line

    args = create_parser().parse_args(["bead", "show", bead_id, "--format", "json"])
    bead_cli.handle_bead_show(args)

    envelope = json.loads(capsys.readouterr().out)
    flag = envelope["issue"]["flag"]
    assert flag["key"] == "demo_key"
    assert flag["remove_by_date"] == "2026-12-01"
    assert flag["remove_by_release"] == "0.19.0"
    assert flag["due_state"] in {"live", "soon", "due"}


def test_list_json_finds_the_flag_bead_by_type(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_id = _create_flag_bead(project_dir)
    capsys.readouterr()  # discard the "Created flag: ..." line

    args = create_parser().parse_args(
        ["bead", "list", "--type", "flag", "--format", "json"]
    )
    bead_cli.handle_bead_list(args)

    envelope = json.loads(capsys.readouterr().out)
    ids = [result["id"] for result in envelope["results"]]
    assert ids == [bead_id]


def test_list_compact_renders_the_flag_glyph(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create_flag_bead(project_dir)
    capsys.readouterr()  # discard the "Created flag: ..." line

    args = create_parser().parse_args(
        ["bead", "list", "--type", "flag", "--format", "compact", "--color", "never"]
    )
    bead_cli.handle_bead_list(args)

    out = capsys.readouterr().out
    assert "⚑" in out
    assert "Retire demo_key" in out


def test_show_full_renders_the_flag_section(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_id = _create_flag_bead(project_dir)
    capsys.readouterr()  # discard the "Created flag: ..." line

    args = create_parser().parse_args(
        ["bead", "show", bead_id, "--format", "full", "--color", "never"]
    )
    bead_cli.handle_bead_show(args)

    out = capsys.readouterr().out
    assert "FLAG" in out
    assert "demo_key" in out
    assert "2026-12-01" in out
    assert "0.19.0" in out


def _create_flag_task_bead(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Retire demo_key",
            IssueType.TASK,
            size="small",
            task_type="flag",
            task_type_fields={
                "key": "demo_key",
                "kind": "beta",
                "when_enabled": "new path",
                "when_disabled": "old path",
                "remove_when": "when proven",
                "remove_by_date": "2026-12-01",
                "remove_by_release": "0.19.0",
            },
        )
    return issue.id


def test_load_flag_bead_snapshots_includes_flag_task_beads(
    project_dir: Path,
) -> None:
    from sase.feature_flags.beads import load_flag_bead_snapshots

    bead_id = _create_flag_task_bead(project_dir)

    snapshots = load_flag_bead_snapshots(cwd=project_dir)
    assert snapshots is not None
    assert len(snapshots) == 1
    assert snapshots[0].id == bead_id
    assert snapshots[0].task_type == "flag"
    assert snapshots[0].kind == "beta"
    assert snapshots[0].key == "demo_key"
    assert snapshots[0].remove_by_date == "2026-12-01"


def test_update_remove_by_writes_task_type_field_thresholds(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_id = _create_flag_task_bead(project_dir)

    args = create_parser().parse_args(
        ["bead", "update", bead_id, "--remove-by", "2026-12-15/0.20.0"]
    )
    bead_cli.handle_bead_update(args)

    with BeadProject(project_dir) as project:
        issue: Issue = project.show(bead_id)
    assert issue.task_type == "flag"
    assert issue.task_type_fields["remove_by_date"] == "2026-12-15"
    assert issue.task_type_fields["remove_by_release"] == "0.20.0"
    assert issue.task_type_fields["key"] == "demo_key"
    assert issue.flag is None
    assert f"✓ Updated issue: {bead_id}" in capsys.readouterr().out


def test_update_remove_by_extends_the_thresholds(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_id = _create_flag_bead(project_dir)

    args = create_parser().parse_args(
        ["bead", "update", bead_id, "--remove-by", "2026-12-15/0.20.0"]
    )
    bead_cli.handle_bead_update(args)

    with BeadProject(project_dir) as project:
        issue: Issue = project.show(bead_id)
    assert issue.flag == FlagRecord(
        key="demo_key", remove_by_date="2026-12-15", remove_by_release="0.20.0"
    )
    assert f"✓ Updated issue: {bead_id}" in capsys.readouterr().out


def test_update_remove_by_rejects_multiple_ids(
    project_dir: Path,
) -> None:
    first = _create_flag_bead(project_dir)
    with BeadProject(project_dir) as project:
        second = project.create(
            "Retire other_key",
            IssueType.FLAG,
            flag=FlagRecord(
                key="other_key",
                remove_by_date="2026-12-01",
                remove_by_release="0.19.0",
            ),
        ).id

    args = create_parser().parse_args(
        ["bead", "update", first, second, "--remove-by", "2026-12-15/0.20.0"]
    )
    with pytest.raises(SystemExit):
        bead_cli.handle_bead_update(args)


def test_update_remove_by_rejects_malformed_value(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_id = _create_flag_bead(project_dir)

    args = create_parser().parse_args(
        ["bead", "update", bead_id, "--remove-by", "not-a-valid-value"]
    )
    with pytest.raises(SystemExit):
        bead_cli.handle_bead_update(args)

    assert "--remove-by expects" in capsys.readouterr().err


def test_close_closes_the_flag_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bead_id = _create_flag_bead(project_dir)

    args = create_parser().parse_args(
        ["bead", "close", bead_id, "--reason", "flag removed"]
    )
    bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        issue = project.show(bead_id)
    assert issue.status is Status.CLOSED
    assert issue.flag is not None
    assert "✓ Closed" in capsys.readouterr().out

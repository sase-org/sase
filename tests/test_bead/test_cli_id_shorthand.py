"""CLI coverage for dash-free bead ID shorthand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser

from .cli_work_helpers import make_args, seed_task


def _suffix(bead_id: str) -> str:
    return bead_id.rsplit("-", 1)[1]


def _seed_epic(project_dir: Path) -> tuple[str, str, str]:
    with BeadProject(project_dir) as project:
        epic = project.create("Epic", IssueType.PLAN)
        first = project.create("First", IssueType.PHASE, parent_id=epic.id)
        second = project.create("Second", IssueType.PHASE, parent_id=epic.id)
        return epic.id, first.id, second.id


def test_show_and_history_accept_unique_shorthand(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _epic_id, first_id, _second_id = _seed_epic(project_dir)
    bead_cli.handle_bead_show(
        create_parser().parse_args(
            ["bead", "show", _suffix(first_id), "--format", "json"]
        )
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["issue"]["id"] == first_id

    bead_cli.handle_bead_history(
        create_parser().parse_args(
            ["bead", "history", _suffix(first_id), "--format", "json"]
        )
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["issue_id"] == first_id


def test_create_update_close_and_remove_canonicalize_shorthand(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, first_id, _second_id = _seed_epic(project_dir)

    bead_cli.handle_bead_create(
        create_parser().parse_args(
            [
                "bead",
                "create",
                "-t",
                "Nested",
                "-T",
                f"phase({_suffix(epic_id)})",
            ]
        )
    )
    created = capsys.readouterr().out
    assert "Created phase:" in created

    bead_cli.handle_bead_update(
        create_parser().parse_args(
            ["bead", "update", _suffix(first_id), "--status", "in_progress"]
        )
    )
    bead_cli.handle_bead_close(
        create_parser().parse_args(["bead", "close", _suffix(first_id)])
    )
    close_output = capsys.readouterr().out
    assert first_id in close_output
    with BeadProject(project_dir) as project:
        assert project.show(first_id).status is Status.CLOSED

    bead_cli.handle_bead_rm(
        create_parser().parse_args(["bead", "rm", _suffix(first_id)])
    )
    rm_output = capsys.readouterr().out
    assert first_id in rm_output
    with BeadProject(project_dir) as project:
        with pytest.raises(KeyError):
            project.show(first_id)


def test_update_accepts_multiple_shorthand_ids_in_one_batch(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _epic_id, first_id, second_id = _seed_epic(project_dir)

    bead_cli.handle_bead_update(
        create_parser().parse_args(
            [
                "bead",
                "update",
                _suffix(first_id),
                _suffix(second_id),
                "--status",
                "in_progress",
            ]
        )
    )

    output = capsys.readouterr().out
    assert f"✓ Updated issue: {first_id}" in output
    assert f"✓ Updated issue: {second_id}" in output
    with BeadProject(project_dir) as project:
        assert project.show(first_id).status is Status.IN_PROGRESS
        assert project.show(second_id).status is Status.IN_PROGRESS


def test_dependency_and_reference_commands_accept_shorthand(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _epic_id, first_id, second_id = _seed_epic(project_dir)

    bead_cli.handle_bead_dep(
        create_parser().parse_args(
            ["bead", "dep", "add", _suffix(second_id), _suffix(first_id)]
        )
    )
    assert f"{second_id} depends on {first_id}" in capsys.readouterr().out
    with BeadProject(project_dir) as project:
        assert project.show(second_id).dependencies[0].depends_on_id == first_id

    bead_cli.handle_bead_dep_list(
        create_parser().parse_args(["bead", "dep", "list", _suffix(second_id)])
    )
    assert second_id in capsys.readouterr().out

    bead_cli.handle_bead_ref(
        create_parser().parse_args(
            ["bead", "ref", "add", _suffix(second_id), "research:202607/report.md"]
        )
    )
    assert f"Added reference to {second_id}" in capsys.readouterr().out
    with BeadProject(project_dir) as project:
        assert project.show(second_id).refs == ["research:202607/report.md"]


def test_work_task_dry_run_uses_canonical_id_for_shorthand(
    project_dir: Path,
    fake_cli_work_xprompts: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.work import VCSLaunchContext

    task_id = seed_task(project_dir)
    monkeypatch.setattr(
        "sase.bead.cli_work_task.resolve_task_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )

    bead_cli.handle_bead_work(make_args(_suffix(task_id), dry_run=True))

    output = capsys.readouterr().out
    assert f"#bd/work_task:{task_id}" in output
    assert f"#bd/work_task:{_suffix(task_id)}" not in output


def test_pages_url_resolves_shorthand_before_building_url(
    tmp_path: Path,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.sdd.store import SddStore

    with BeadProject(project_dir) as project:
        bead = project.create("Page", IssueType.TASK, task_type="bug", size="small")
    store = SddStore(
        "sidecar_repos",
        tmp_path / "plans",
        tmp_path / "plans",
        beads_dir=project_dir / "sdd" / "beads",
        beads_remote_url="git@github.com:sase-org/sase--beads.git",
    )
    (tmp_path / "plans").mkdir()

    class _Resolver:
        def bead_url(self, bead_id: str) -> str:
            assert bead_id == bead.id
            return f"https://example.test/{bead_id}"

    monkeypatch.setattr(
        "sase.bead.cli_pages._page_context",
        lambda **_kwargs: (store, tmp_path, "sase"),
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_project_for_beads_dir",
        lambda _path: BeadProject(project_dir),
    )
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )
    args = create_parser().parse_args(["bead", "pages", "url", _suffix(bead.id)])

    with pytest.raises(SystemExit) as exc:
        bead_cli.handle_bead_pages(args)

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"https://example.test/{bead.id}"

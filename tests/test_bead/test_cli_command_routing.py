"""Cross-project routing coverage for bead commands with existing-ID operands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from sase.ops.commands.bead import _run_apply_status
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


def test_close_foreign_full_id_from_outside_routes_owner_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Foreign plan", IssueType.PLAN)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)

    args = create_parser().parse_args(["bead", "close", issue.id])
    bead_cli.handle_bead_close(args)

    with BeadProject(owner) as project:
        assert project.show(issue.id).status is Status.CLOSED
    assert not (caller / "sdd" / "beads").exists()


def test_create_phase_with_foreign_parent_uses_parent_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    epic = _seed_issue(owner, "Foreign epic", IssueType.PLAN, tier=BeadTier.EPIC)
    _route_only_enabled_owner(monkeypatch, owner, epic.id)
    monkeypatch.chdir(caller)

    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "-t",
            "Foreign phase",
            "-T",
            f"phase({epic.id})",
            "-z",
            "small",
        ]
    )
    bead_cli.handle_bead_create(args)

    with BeadProject(owner) as project:
        children = [
            issue
            for issue in project.list_issues()
            if issue.parent_id == epic.id and issue.issue_type is IssueType.PHASE
        ]
    assert [issue.title for issue in children] == ["Foreign phase"]
    assert not (caller / "sdd" / "beads").exists()


def test_dep_add_rejects_mixed_foreign_stores_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(first, "Blocked", IssueType.TASK)
    blocker = _seed_issue(second, "Blocker", IssueType.TASK)
    _route_enabled_projects(monkeypatch, (first, issue.id), (second, blocker.id))
    monkeypatch.chdir(caller)

    args = create_parser().parse_args(["bead", "dep", "add", issue.id, blocker.id])
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_dep(args)

    assert "multiple stores" in capsys.readouterr().err
    with BeadProject(first) as project:
        assert project.show(issue.id).dependencies == []


def test_history_foreign_full_id_reads_owner_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Foreign history", IssueType.TASK)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)

    args = create_parser().parse_args(["bead", "history", issue.id, "--format", "json"])
    bead_cli.handle_bead_history(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["issue_id"] == issue.id
    assert payload["entries"][0]["operation"] == "issue_created"


def test_ref_list_resolve_uses_owner_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Foreign refs", IssueType.TASK, refs=("doc:alpha",))
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)
    workspaces: list[Path | None] = []

    def fake_artifact_context(workspace: Path | None = None) -> None:
        workspaces.append(workspace)
        return None

    monkeypatch.setattr(
        "sase.bead.cli_refs.artifact_reference_context",
        fake_artifact_context,
    )

    args = create_parser().parse_args(["bead", "ref", "list", issue.id, "--resolve"])
    bead_cli.handle_bead_ref(args)

    assert workspaces == [owner]
    assert "doc:alpha" in capsys.readouterr().out


def test_apply_status_foreign_full_id_updates_owner_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Foreign status", IssueType.TASK)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)

    success, message, payload = _run_apply_status(
        argparse.Namespace(bead_id=issue.id, status="in_progress")
    )

    assert success is True
    assert message == f"Updated {issue.id} status to in_progress"
    assert payload == {"bead_id": issue.id, "status": "in_progress"}
    with BeadProject(owner) as project:
        assert project.show(issue.id).status is Status.IN_PROGRESS


def _seed_issue(
    root: Path,
    title: str,
    issue_type: IssueType,
    *,
    tier: BeadTier | None = None,
    refs: tuple[str, ...] = (),
) -> Issue:
    with BeadProject.init(root) as project:
        return project.create(
            title,
            issue_type,
            tier=tier,
            task_type="bug" if issue_type is IssueType.TASK else "",
            size="small" if issue_type is IssueType.TASK else None,
            refs=refs,
        )


def _route_only_enabled_owner(
    monkeypatch: pytest.MonkeyPatch,
    owner: Path,
    issue_id: str,
) -> None:
    _route_enabled_projects(monkeypatch, (owner, issue_id))


def _route_enabled_projects(
    monkeypatch: pytest.MonkeyPatch,
    *stores: tuple[Path, str],
) -> None:
    if stores:
        isolate_bead_store_resolution(
            monkeypatch,
            stores[0][0],
            project_name=stores[0][0].name,
        )
    monkeypatch.setattr(
        "sase.bead.operation_context._user_directed_context_for_project",
        lambda _project_key, _primary: None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context._writable_beads_dir_for_context",
        lambda _context: None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: tuple(_snapshot(root, issue_id) for root, issue_id in stores),
    )


def _snapshot(root: Path, issue_id: str) -> BeadStoreSnapshot:
    beads_dir = root / "sdd" / "beads"
    project_key = root.name
    return BeadStoreSnapshot(
        origin=BeadStoreOrigin(
            project_key=project_key,
            project_label=project_key,
            primary_workspace=root,
            beads_dir=beads_dir,
        ),
        store_key=str(beads_dir),
        issue_ids=frozenset({issue_id}),
        issue_prefix=project_key,
        project_refs=frozenset({project_key}),
    )

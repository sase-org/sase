"""Cross-project routing coverage for bead commands with existing-ID operands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.config import load_config, save_config
from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from sase.ops.commands.bead import _run_apply_status
from tests.test_bead.resolution_test_helpers import (
    bead_store_snapshot,
    isolate_bead_store_resolution,
)


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


def test_create_plan_with_foreign_parent_stores_owner_plan_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    plan = owner / "sdd" / "plans" / "202609" / "child.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Child plan\n", encoding="utf-8")
    epic = _seed_issue(owner, "Foreign epic", IssueType.PLAN, tier=BeadTier.EPIC)
    _route_only_enabled_owner(monkeypatch, owner, epic.id)
    monkeypatch.chdir(caller)

    args = create_parser().parse_args(
        [
            "bead",
            "create",
            "-t",
            "Foreign child plan",
            "-T",
            f"plan(../owner/sdd/plans/202609/child.md,{epic.id})",
            "--tier",
            "plan",
        ]
    )
    bead_cli.handle_bead_create(args)

    with BeadProject(owner) as project:
        children = [
            issue
            for issue in project.list_issues()
            if issue.parent_id == epic.id and issue.issue_type is IssueType.PLAN
        ]
    assert [issue.design for issue in children] == ["plan:202609/child.md"]
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


def test_apply_status_missing_full_id_does_not_retry_caller_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = tmp_path / "outside"
    caller.mkdir()
    monkeypatch.chdir(caller)
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (),
    )

    success, message, payload = _run_apply_status(
        argparse.Namespace(bead_id="missing-1", status="closed")
    )

    assert success is False
    assert message == "issue not found: missing-1"
    assert payload == {"bead_id": "missing-1", "status": "closed"}
    assert not (caller / "sdd" / "beads").exists()


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


def _seed_closed_issue(root: Path, title: str) -> Issue:
    with BeadProject.init(root) as project:
        issue = project.create(title, IssueType.TASK, task_type="bug", size="small")
        return project.close([issue.id])[0]


def _seed_dependency_pair(root: Path) -> tuple[Issue, Issue]:
    with BeadProject.init(root) as project:
        issue = project.create("Blocked", IssueType.TASK, task_type="bug", size="small")
        blocker = project.create(
            "Blocker",
            IssueType.TASK,
            task_type="bug",
            size="small",
        )
    return issue, blocker


def _seed_deep_historical_issue(root: Path) -> str:
    with BeadProject.init(root):
        pass
    config = load_config(root / "sdd" / "beads")
    config["issue_prefix"] = "sase"
    config["next_counter"] = int("xe", 36)
    save_config(root / "sdd" / "beads", config)

    with BeadProject(root) as project:
        top = project.create("Historical top", IssueType.PLAN, tier=BeadTier.EPIC)
        parent_id = top.id
        for count in (16, 11, 7, 15, 7):
            child: Issue | None = None
            for index in range(count):
                child = project.create(
                    f"Historical child {count}.{index + 1}",
                    IssueType.PHASE,
                    parent_id=parent_id,
                )
            assert child is not None
            parent_id = child.id
    assert parent_id == "sase-xe.16.11.7.15.7"
    return parent_id


def _revision_chain(root: Path) -> str:
    with BeadProject.init(root) as project:
        issue = project.create("History target", IssueType.PLAN, notes="first note")
    _append_legacy_notes_update(root, issue.id, "second note")
    _append_legacy_notes_update(root, issue.id, "third note")
    with BeadProject(root) as project:
        project.reproject_from_events()
    return issue.id


def _append_legacy_notes_update(root: Path, issue_id: str, notes: str) -> None:
    stream_path = root / f"sdd/beads/events/streams/{issue_id}.jsonl"
    lines = stream_path.read_text(encoding="utf-8").splitlines()
    sequence = len(lines) + 1
    event = {
        "schema_version": 1,
        "event_id": (
            f"{issue_id}:{sequence:06}:issue_updated:{issue_id}:"
            f"legacy-notes-{sequence:06}"
        ),
        "timestamp": f"2026-07-27T00:00:{sequence:02}Z",
        "actor": "legacy@example.com",
        "operation": "issue_updated",
        "issue_id": issue_id,
        "payload": {"kind": "issue_updated", "fields": {"notes": notes}},
    }
    stream_path.write_text(
        "\n".join(
            [
                *lines,
                json.dumps(event, separators=(",", ":"), sort_keys=True),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _route_only_enabled_owner(
    monkeypatch: pytest.MonkeyPatch,
    owner: Path,
    *issue_ids: str,
) -> None:
    _route_enabled_projects(monkeypatch, (owner, issue_ids))


def _route_enabled_projects(
    monkeypatch: pytest.MonkeyPatch,
    *stores: tuple[Path, str | tuple[str, ...]],
) -> None:
    snapshots = tuple(
        _snapshot(root, *_coerce_issue_ids(issue_ids)) for root, issue_ids in stores
    )
    _install_enabled_snapshots(monkeypatch, snapshots)


def _install_enabled_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: tuple[BeadStoreSnapshot, ...],
) -> None:
    if snapshots:
        isolate_bead_store_resolution(
            monkeypatch,
            snapshots[0].origin.primary_workspace,
            project_name=snapshots[0].origin.project_key,
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
        lambda: snapshots,
    )
    monkeypatch.setattr(
        "sase.bead.cross_project.enabled_project_store_snapshots",
        lambda: snapshots,
    )
    monkeypatch.setattr(
        "sase.bead.cross_project.origin_for_project_ref",
        lambda ref: _origin_for_ref(ref, snapshots),
    )


def _coerce_issue_ids(issue_ids: str | tuple[str, ...]) -> tuple[str, ...]:
    return (issue_ids,) if isinstance(issue_ids, str) else issue_ids


def _snapshot(root: Path, *issue_ids: str) -> BeadStoreSnapshot:
    project_key = root.name
    return bead_store_snapshot(
        project_key,
        root,
        *issue_ids,
        project_label=project_key,
        project_refs=frozenset({project_key}),
    )


def _origin_for_ref(
    ref: str,
    snapshots: tuple[BeadStoreSnapshot, ...],
) -> BeadStoreOrigin | None:
    matches = [
        snapshot.origin
        for snapshot in snapshots
        if ref in snapshot.project_refs
        or ref == snapshot.origin.project_key
        or ref == snapshot.origin.project_label
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return None
    from sase.bead.cross_project import AmbiguousBeadProjectError

    raise AmbiguousBeadProjectError(ref, matches, subject="project")


def _run_bead_entry(
    argv: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "bead", *argv])
    monkeypatch.setattr("sase.bead.sync.schedule_bead_refresh", lambda _path: None)
    monkeypatch.setattr("sase.bead.sync.schedule_current_bead_refresh", lambda: None)

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    captured = capsys.readouterr()
    return int(exc_info.value.code or 0), captured.out, captured.err


def _registered_bead_subcommands() -> frozenset[str]:
    parser = create_parser()
    command_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    bead_parser = command_action.choices["bead"]
    bead_action = next(
        action
        for action in bead_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return frozenset(bead_action.choices)


def _tree_state(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {"": None}
    state: dict[str, bytes | None] = {"": b"dir"}
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        if path.is_dir():
            state[f"{key}/"] = b"dir"
        elif path.is_symlink():
            state[key] = f"symlink:{path.readlink()}".encode()
        else:
            state[key] = path.read_bytes()
    return state


def _assert_status(root: Path, issue_id: str, status: Status) -> None:
    with BeadProject(root) as project:
        assert project.show(issue_id).status is status


def _assert_notes_contain(root: Path, issue_id: str, text: str) -> None:
    with BeadProject(root) as project:
        assert text in project.show(issue_id).notes_text


def _assert_plus_ones(root: Path, issue_id: str, count: int) -> None:
    with BeadProject(root) as project:
        assert project.show(issue_id).plus_one_count == count


def _assert_dependencies(root: Path, issue_id: str, expected: list[str]) -> None:
    with BeadProject(root) as project:
        actual = [
            dependency.depends_on_id
            for dependency in project.show(issue_id).dependencies
        ]
    assert actual == expected


def _assert_missing(root: Path, issue_id: str) -> None:
    with BeadProject(root) as project:
        with pytest.raises(KeyError):
            project.show(issue_id)


def _set_issue_prefix(root: Path, prefix: str, next_counter: int = 1) -> None:
    config = load_config(root / "sdd" / "beads")
    config["issue_prefix"] = prefix
    config["next_counter"] = next_counter
    save_config(root / "sdd" / "beads", config)


def _arrange_mixed_store_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    first = tmp_path / "first"
    second = tmp_path / "second"
    caller = tmp_path / "outside"
    caller.mkdir()
    first_issue = _seed_issue(first, "First", IssueType.TASK)
    second_issue = _seed_issue(second, "Second", IssueType.TASK)
    _route_enabled_projects(
        monkeypatch,
        (first, first_issue.id),
        (second, second_issue.id),
    )
    monkeypatch.chdir(caller)
    return {
        "first_id": first_issue.id,
        "second_id": second_issue.id,
        "message": "multiple stores",
        "snapshot_roots": [first / "sdd" / "beads", second / "sdd" / "beads", caller],
    }


def _arrange_last_operand_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Valid first", IssueType.TASK)
    missing_id = f"{issue.id.rsplit('-', maxsplit=1)[0]}-zz"
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)
    return {
        "valid_id": issue.id,
        "missing_id": missing_id,
        "message": f"issue not found: {missing_id}",
        "snapshot_roots": [owner / "sdd" / "beads", caller],
    }


def _arrange_ambiguous_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    first = tmp_path / "first"
    second = tmp_path / "second"
    caller = tmp_path / "outside"
    caller.mkdir()
    for root in (first, second):
        with BeadProject.init(root):
            pass
        _set_issue_prefix(root, "sase")
    with BeadProject(first) as project:
        first_issue = project.create(
            "Ambiguous first",
            IssueType.TASK,
            task_type="bug",
            size="small",
        )
    with BeadProject(second) as project:
        second_issue = project.create(
            "Ambiguous second",
            IssueType.TASK,
            task_type="bug",
            size="small",
        )
    assert first_issue.id == second_issue.id
    _route_enabled_projects(
        monkeypatch,
        (first, first_issue.id),
        (second, second_issue.id),
    )
    monkeypatch.chdir(caller)
    return {
        "ambiguous_id": first_issue.id,
        "message": "ambiguous",
        "snapshot_roots": [first / "sdd" / "beads", second / "sdd" / "beads", caller],
    }


def _arrange_unavailable_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    caller = tmp_path / "outside"
    caller.mkdir()
    beads_dir = tmp_path / "offline" / "sdd" / "beads"
    snapshots = (
        BeadStoreSnapshot(
            origin=BeadStoreOrigin(
                project_key="offline",
                project_label="offline",
                primary_workspace=tmp_path / "offline",
                beads_dir=beads_dir,
            ),
            store_key=str(beads_dir),
            issue_ids=frozenset(),
            issue_prefix="offline",
            project_refs=frozenset({"offline"}),
            unavailable_reason="permission denied",
        ),
    )
    _install_enabled_snapshots(monkeypatch, snapshots)
    monkeypatch.chdir(caller)
    return {
        "unavailable_id": "offline-1",
        "message": "not materialized",
        "snapshot_roots": [caller],
    }


def _arrange_mixed_shorthand_full_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    local = tmp_path / "local"
    foreign = tmp_path / "foreign"
    local_issue = _seed_issue(local, "Local", IssueType.TASK)
    foreign_issue = _seed_issue(foreign, "Foreign", IssueType.TASK)
    _route_only_enabled_owner(monkeypatch, foreign, foreign_issue.id)
    isolate_bead_store_resolution(monkeypatch, local, project_name="local")
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (_snapshot(foreign, foreign_issue.id),),
    )
    monkeypatch.setattr(
        "sase.bead.cross_project.enabled_project_store_snapshots",
        lambda: (_snapshot(foreign, foreign_issue.id),),
    )
    return {
        "local_shorthand": local_issue.id.rsplit("-", maxsplit=1)[-1],
        "foreign_id": foreign_issue.id,
        "message": "multiple stores",
        "snapshot_roots": [local / "sdd" / "beads", foreign / "sdd" / "beads"],
    }

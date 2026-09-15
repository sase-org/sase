"""Public dispatch acceptance coverage for existing-ID bead command routing."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.project import BeadProject
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution
from tests.test_bead.test_cli_command_routing import (
    _arrange_ambiguous_update,
    _arrange_last_operand_missing,
    _arrange_mixed_shorthand_full_update,
    _arrange_mixed_store_update,
    _arrange_unavailable_update,
    _assert_dependencies,
    _assert_missing,
    _assert_notes_contain,
    _assert_plus_ones,
    _assert_status,
    _install_enabled_snapshots,
    _registered_bead_subcommands,
    _revision_chain,
    _route_enabled_projects,
    _route_only_enabled_owner,
    _run_bead_entry,
    _seed_closed_issue,
    _seed_deep_historical_issue,
    _seed_dependency_pair,
    _seed_issue,
    _snapshot,
    _tree_state,
)


ROUTED_EXISTING_ID_COMMANDS = frozenset(
    {
        "+1",
        "apply-status",
        "close",
        "create",
        "dep",
        "epic-symbols",
        "history",
        "note",
        "open",
        "pages",
        "ref",
        "rm",
        "show",
        "snooze",
        "update",
        "work",
    }
)
NON_EXISTING_ID_COMMANDS = frozenset(
    {
        "blocked",
        "doctor",
        "init",
        "list",
        "onboard",
        "ready",
        "resolve-conflicts",
        "search",
        "stats",
        "sync",
        "sync-external",
        "task-type",
    }
)


def test_bead_subcommand_inventory_is_classified_for_routing_acceptance() -> None:
    """Fail loudly when a new bead surface needs routing classification."""
    assert _registered_bead_subcommands() == (
        ROUTED_EXISTING_ID_COMMANDS | NON_EXISTING_ID_COMMANDS
    )


def test_show_foreign_full_id_from_outside_does_not_initialize_caller_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Foreign show", IssueType.TASK)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)

    code, out, err = _run_bead_entry(
        ["show", issue.id, "--format", "compact", "--pager", "never", "--no-links"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    assert "Foreign show" in out
    assert not (caller / "sdd" / "beads").exists()


def test_show_strict_project_resolves_shorthand_without_local_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Pinned show", IssueType.TASK)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)

    code, out, err = _run_bead_entry(
        [
            "show",
            issue.id.rsplit("-", maxsplit=1)[-1],
            "--project",
            "owner",
            "--format",
            "compact",
            "--pager",
            "never",
            "--no-links",
        ],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    assert "Pinned show" in out
    assert not (caller / "sdd" / "beads").exists()


@pytest.mark.parametrize(
    ("name", "setup", "argv", "assertion"),
    [
        (
            "open",
            lambda owner: _seed_closed_issue(owner, "Foreign open"),
            lambda issue: ["open", issue.id],
            lambda owner, issue, _out: _assert_status(owner, issue.id, Status.OPEN),
        ),
        (
            "note",
            lambda owner: _seed_issue(owner, "Foreign note", IssueType.TASK),
            lambda issue: ["note", issue.id, "routed note", "--author", "tester"],
            lambda owner, issue, _out: _assert_notes_contain(
                owner,
                issue.id,
                "routed note",
            ),
        ),
        (
            "+1",
            lambda owner: _seed_issue(owner, "Foreign +1", IssueType.TASK),
            lambda issue: [
                "+1",
                issue.id,
                "-n",
                "routed evidence",
                "-a",
                "other@example.com",
            ],
            lambda owner, issue, _out: _assert_plus_ones(owner, issue.id, 1),
        ),
        (
            "update",
            lambda owner: _seed_issue(owner, "Foreign update", IssueType.TASK),
            lambda issue: ["update", issue.id, "--status", "in_progress"],
            lambda owner, issue, _out: _assert_status(
                owner,
                issue.id,
                Status.IN_PROGRESS,
            ),
        ),
        (
            "apply-status",
            lambda owner: _seed_issue(owner, "Foreign apply", IssueType.TASK),
            lambda issue: ["apply-status", issue.id, "in_progress"],
            lambda owner, issue, _out: _assert_status(
                owner,
                issue.id,
                Status.IN_PROGRESS,
            ),
        ),
        (
            "snooze",
            lambda owner: _seed_issue(owner, "Foreign snooze", IssueType.TASK),
            lambda issue: [
                "snooze",
                issue.id,
                "-u",
                "2099-01-01T00:00:00Z",
                "-r",
                "waiting",
            ],
            lambda owner, issue, _out: _assert_status(owner, issue.id, Status.SNOOZED),
        ),
        (
            "close",
            lambda owner: _seed_issue(owner, "Foreign close", IssueType.PLAN),
            lambda issue: ["close", issue.id, "--note", "verified"],
            lambda owner, issue, _out: _assert_status(owner, issue.id, Status.CLOSED),
        ),
        (
            "rm",
            lambda owner: _seed_issue(owner, "Foreign remove", IssueType.TASK),
            lambda issue: ["rm", issue.id],
            lambda owner, issue, _out: _assert_missing(owner, issue.id),
        ),
    ],
)
def test_public_dispatch_routes_foreign_existing_id_mutations(
    name: str,
    setup: Callable[[Path], Issue],
    argv: Callable[[Issue], list[str]],
    assertion: Callable[[Path, Issue, str], None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del name
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = setup(owner)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)

    code, out, err = _run_bead_entry(
        argv(issue),
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    assertion(owner, issue, out)
    assert not (caller / "sdd" / "beads").exists()


def test_public_dispatch_routes_foreign_dep_add_rm_list_and_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue, blocker = _seed_dependency_pair(owner)
    _route_enabled_projects(monkeypatch, (owner, (issue.id, blocker.id)))
    monkeypatch.chdir(caller)

    code, out, err = _run_bead_entry(
        ["dep", "add", issue.id, blocker.id],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert f"{issue.id} depends on {blocker.id}" in out
    _assert_dependencies(owner, issue.id, [blocker.id])

    code, out, err = _run_bead_entry(
        ["dep", "list", issue.id, "--format", "json"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert issue.id in out
    assert blocker.id in out

    code, out, err = _run_bead_entry(
        ["dep", "tree", issue.id, "--format", "json"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert issue.id in out
    assert blocker.id in out

    code, out, err = _run_bead_entry(
        ["dep", "rm", issue.id, blocker.id],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert f"{issue.id} no longer depends on {blocker.id}" in out
    _assert_dependencies(owner, issue.id, [])
    assert not (caller / "sdd" / "beads").exists()


def test_public_dispatch_routes_foreign_ref_add_list_resolve_and_rm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Foreign refs", IssueType.TASK)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)
    reference_workspaces: list[Path | None] = []

    def fake_artifact_context(workspace: Path | None = None) -> None:
        reference_workspaces.append(workspace)
        return None

    monkeypatch.setattr(
        "sase.bead.cli_refs.artifact_reference_context",
        fake_artifact_context,
    )

    code, out, err = _run_bead_entry(
        ["ref", "add", issue.id, "plan:owner.md"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "plan:owner.md" in out

    code, out, err = _run_bead_entry(
        ["ref", "list", issue.id, "--resolve", "--json"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert reference_workspaces == [owner]
    payload = json.loads(out)
    assert payload["results"][0]["issue_id"] == issue.id
    assert payload["results"][0]["refs"][0]["rendered"] == "plan:owner.md"

    code, out, err = _run_bead_entry(
        ["ref", "rm", issue.id, "plan:owner.md"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "plan:owner.md" in out
    with BeadProject(owner) as project:
        assert project.show(issue.id).refs == []
    assert not (caller / "sdd" / "beads").exists()


def test_public_dispatch_routes_foreign_history_and_lost_note_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue_id = _revision_chain(owner)
    _route_only_enabled_owner(monkeypatch, owner, issue_id)
    monkeypatch.chdir(caller)

    code, out, err = _run_bead_entry(
        ["history", issue_id, "--format", "json"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert json.loads(out)["issue_id"] == issue_id

    code, out, err = _run_bead_entry(
        ["history", issue_id, "--lost-notes", "--restore", "--yes"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 0
    assert err == ""
    assert "Restored 2 lost note revisions" in out
    _assert_notes_contain(owner, issue_id, "(restored")
    assert not (caller / "sdd" / "beads").exists()


def test_close_foreign_task_settles_gate_in_owner_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Foreign task close", IssueType.TASK)
    _route_only_enabled_owner(monkeypatch, owner, issue.id)
    monkeypatch.chdir(caller)
    settlements: list[tuple[str, set[str]]] = []
    monkeypatch.setattr(
        "sase.bead.close_gate_settle.settle_closed_task_bead_gates",
        lambda project, ids: settlements.append((project, set(ids))),
    )

    code, _out, err = _run_bead_entry(
        ["close", issue.id, "--note", "verified"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    assert settlements == [("owner", {issue.id})]


def test_close_foreign_epic_phase_selector_scans_owner_justfile_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    with BeadProject.init(owner) as project:
        epic = project.create("Foreign epic", IssueType.PLAN, tier=BeadTier.EPIC)
        first = project.create("First phase", IssueType.PHASE, parent_id=epic.id)
        second = project.create("Second phase", IssueType.PHASE, parent_id=epic.id)
    owner.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")
    caller.joinpath("Justfile").write_text(
        f'--epic-symbol "{first.id}(CallerOnly)"\n',
        encoding="utf-8",
    )
    _route_enabled_projects(monkeypatch, (owner, (epic.id, first.id, second.id)))
    monkeypatch.chdir(caller)

    code, out, err = _run_bead_entry(
        ["close", epic.id, "--phases", "1", "--note", "verified"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    assert first.id in out
    _assert_status(owner, first.id, Status.CLOSED)
    _assert_status(owner, second.id, Status.OPEN)
    assert not (caller / "sdd" / "beads").exists()


def test_deep_foreign_close_from_outside_uses_owner_and_caller_at_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    deep_id = _seed_deep_historical_issue(owner)
    (caller / "note.txt").write_text("caller note\n", encoding="utf-8")
    (caller / "reason.txt").write_text("caller reason\n", encoding="utf-8")
    _route_only_enabled_owner(monkeypatch, owner, deep_id)
    monkeypatch.chdir(caller)

    code, out, err = _run_bead_entry(
        [
            "close",
            deep_id,
            "--note",
            "@note.txt",
            "--reason",
            "@reason.txt",
            "--no-push",
        ],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    assert deep_id in out
    with BeadProject(owner) as project:
        closed = project.show(deep_id)
    assert closed.status is Status.CLOSED
    assert closed.close_reason == "caller reason\n"
    assert "caller note" in closed.notes_text
    assert not (caller / "sdd" / "beads").exists()


def test_public_dispatch_work_dry_run_routes_foreign_epic_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake_cli_work_xprompts: None,
) -> None:
    del fake_cli_work_xprompts
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    with BeadProject.init(owner) as project:
        epic = project.create("Foreign work", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)
    _route_enabled_projects(monkeypatch, (owner, (epic.id, phase.id)))
    monkeypatch.chdir(caller)
    before = _tree_state(owner / "sdd" / "beads")

    code, out, err = _run_bead_entry(
        ["work", epic.id, "--dry-run", "--yes", "--wait", f"bead={phase.id}"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    assert "Multi-prompt (dry run)" in out
    assert f"#bd/work_phase_bead:{phase.id}" in out
    assert _tree_state(owner / "sdd" / "beads") == before
    assert not (caller / "sdd" / "beads").exists()


def test_public_dispatch_local_full_id_hit_does_not_read_project_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    issue = _seed_issue(owner, "Local registry avoidance", IssueType.TASK)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")

    def fail_registry() -> tuple[BeadStoreSnapshot, ...]:
        raise AssertionError("local full-ID hit must not read enabled projects")

    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        fail_registry,
    )

    code, _out, err = _run_bead_entry(
        ["update", issue.id, "--status", "in_progress"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    _assert_status(owner, issue.id, Status.IN_PROGRESS)


@pytest.mark.parametrize(
    ("name", "arrange", "argv"),
    [
        (
            "mixed foreign stores",
            lambda tmp_path, monkeypatch: _arrange_mixed_store_update(
                tmp_path,
                monkeypatch,
            ),
            lambda data: [
                "update",
                data["first_id"],
                data["second_id"],
                "--status",
                "closed",
            ],
        ),
        (
            "last operand missing",
            lambda tmp_path, monkeypatch: _arrange_last_operand_missing(
                tmp_path,
                monkeypatch,
            ),
            lambda data: [
                "update",
                data["valid_id"],
                data["missing_id"],
                "--status",
                "closed",
            ],
        ),
        (
            "exact ambiguity",
            lambda tmp_path, monkeypatch: _arrange_ambiguous_update(
                tmp_path,
                monkeypatch,
            ),
            lambda data: ["update", data["ambiguous_id"], "--status", "closed"],
        ),
        (
            "relevant unavailable store",
            lambda tmp_path, monkeypatch: _arrange_unavailable_update(
                tmp_path,
                monkeypatch,
            ),
            lambda data: ["update", data["unavailable_id"], "--status", "closed"],
        ),
        (
            "mixed shorthand and full",
            lambda tmp_path, monkeypatch: _arrange_mixed_shorthand_full_update(
                tmp_path,
                monkeypatch,
            ),
            lambda data: [
                "update",
                data["local_shorthand"],
                data["foreign_id"],
                "--status",
                "closed",
            ],
        ),
    ],
)
def test_rejected_public_dispatch_preflights_leave_every_store_unchanged(
    name: str,
    arrange: Callable[[Path, pytest.MonkeyPatch], dict[str, Any]],
    argv: Callable[[dict[str, Any]], list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del name
    data = arrange(tmp_path, monkeypatch)
    roots = [Path(root) for root in data["snapshot_roots"]]
    before = {str(root): _tree_state(root) for root in roots}

    def fail_binding(_name: str) -> object:
        raise AssertionError("routing failure must not reach Rust executor")

    monkeypatch.setattr("sase.core.rust.require_rust_binding", fail_binding)

    code, out, err = _run_bead_entry(
        argv(data),
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 1
    assert out == ""
    assert data["message"] in err
    assert {str(root): _tree_state(root) for root in roots} == before


def test_unrelated_unavailable_store_does_not_block_valid_foreign_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue = _seed_issue(owner, "Valid despite unrelated outage", IssueType.TASK)
    snapshots = (
        _snapshot(owner, issue.id),
        BeadStoreSnapshot(
            origin=BeadStoreOrigin(
                project_key="offline",
                project_label="offline",
                primary_workspace=tmp_path / "offline",
                beads_dir=tmp_path / "offline" / "sdd" / "beads",
            ),
            store_key=str(tmp_path / "offline" / "sdd" / "beads"),
            issue_ids=frozenset(),
            issue_prefix="offline",
            project_refs=frozenset({"offline"}),
            unavailable_reason="permission denied",
        ),
    )
    _install_enabled_snapshots(monkeypatch, snapshots)
    monkeypatch.chdir(caller)

    code, _out, err = _run_bead_entry(
        ["update", issue.id, "--status", "in_progress"],
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert code == 0
    assert err == ""
    _assert_status(owner, issue.id, Status.IN_PROGRESS)
    assert not (caller / "sdd" / "beads").exists()

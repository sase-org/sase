"""Tests for owner-qualified bead operation contexts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot
from sase.bead.model import IssueType
from sase.bead.cli_work_from_plan_project import _invocation_belongs_to_project
from sase.bead.operation_context import (
    BeadOperationRoutingError,
    resolve_operation_context_for_project,
    resolve_operation_context_for_targets,
)
from sase.bead.project import BeadProject
from sase.main import bead_fast_path
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


def test_resolve_context_routes_foreign_full_id_to_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "caller"
    caller.mkdir()
    issue_id = _seed_task(owner, "Foreign target")
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.chdir(caller)
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (_snapshot("owner", owner, issue_id),),
    )

    context = resolve_operation_context_for_targets(
        [issue_id],
        cwd=caller,
        for_write=True,
    )

    assert context.invocation_cwd == caller.resolve()
    assert context.write_beads_dir == owner / "sdd" / "beads"
    assert context.project_key == "owner"
    assert context.resolved_ids == (issue_id,)


def test_resolve_context_keeps_local_full_id_without_registry_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    issue_id = _seed_task(owner, "Local target")
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")

    def fail_registry() -> tuple[BeadStoreSnapshot, ...]:
        raise AssertionError("local full-ID hit must not read enabled projects")

    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        fail_registry,
    )

    context = resolve_operation_context_for_targets([issue_id], cwd=owner)

    assert context.write_beads_dir == owner / "sdd" / "beads"
    assert context.project_key is None
    assert context.resolved_ids == (issue_id,)


def test_resolve_context_rejects_mixed_store_batch_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    caller = tmp_path / "caller"
    caller.mkdir()
    first_id = _seed_task(first, "First target")
    second_id = _seed_task(second, "Second target")
    monkeypatch.chdir(caller)
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (
            _snapshot("first", first, first_id),
            _snapshot("second", second, second_id),
        ),
    )

    with pytest.raises(BeadOperationRoutingError, match="multiple stores"):
        resolve_operation_context_for_targets(
            [first_id, second_id],
            cwd=caller,
            for_write=True,
        )


def test_resolve_context_rejects_local_and_foreign_store_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = tmp_path / "local"
    foreign = tmp_path / "foreign"
    local_id = _seed_task(local, "Local target")
    foreign_id = _seed_task(foreign, "Foreign target")
    isolate_bead_store_resolution(monkeypatch, local, project_name="local")
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (_snapshot("foreign", foreign, foreign_id),),
    )

    with pytest.raises(BeadOperationRoutingError, match="multiple stores"):
        resolve_operation_context_for_targets(
            [local_id, foreign_id],
            cwd=local,
            for_write=True,
        )


def test_fast_path_executes_foreign_target_with_owner_store_and_invocation_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "outside"
    caller.mkdir()
    issue_id = _seed_task(owner, "Foreign remove")
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.chdir(caller)
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (_snapshot("owner", owner, issue_id),),
    )
    monkeypatch.setattr("sase.bead.sync.schedule_bead_refresh", lambda _path: None)

    calls: list[dict[str, Any]] = []

    def fake_binding(
        argv: list[str],
        read_beads_dirs: list[str],
        write_beads_dir: str,
        cwd: str,
        relativize_design_paths: bool,
    ) -> dict[str, object]:
        calls.append(
            {
                "argv": argv,
                "read_beads_dirs": read_beads_dirs,
                "write_beads_dir": write_beads_dir,
                "cwd": cwd,
                "relativize_design_paths": relativize_design_paths,
            }
        )
        return {"handled": True, "exit_code": 0, "stdout": ""}

    from sase.core import rust as rust_bindings

    real_require = rust_bindings.require_rust_binding

    def require_binding(name: str) -> object:
        if name == "bead_cli_execute":
            return fake_binding
        # Ownership probes never read the store; serve them for real.
        return real_require(name)

    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        require_binding,
    )

    assert bead_fast_path.try_handle_bead_fast_path(["rm", issue_id]) == 0

    assert calls == [
        {
            "argv": ["rm", issue_id],
            "read_beads_dirs": [str(owner / "sdd" / "beads")],
            "write_beads_dir": str(owner / "sdd" / "beads"),
            "cwd": str(caller.resolve()),
            "relativize_design_paths": True,
        }
    ]


def test_resolve_context_for_project_keeps_invocation_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "caller"
    caller.mkdir()
    with BeadProject.init(owner):
        pass
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.chdir(caller)
    origin = BeadStoreOrigin(
        project_key="owner",
        project_label="Owner",
        primary_workspace=owner,
        beads_dir=owner / "sdd" / "beads",
    )
    monkeypatch.setattr(
        "sase.bead.cross_project.origin_for_project_ref",
        lambda ref: origin if ref in {"owner", "Owner"} else None,
    )
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace_for_project",
        lambda name: owner if name == "owner" else None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context._user_directed_context_for_project",
        lambda _project_key, _primary: None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context._writable_beads_dir_for_context",
        lambda _context: None,
    )

    context = resolve_operation_context_for_project(
        "Owner",
        cwd=caller,
        for_write=True,
        materialize=True,
    )

    assert context.invocation_cwd == caller.resolve()
    assert context.project_key == "owner"
    assert context.project_label == "Owner"
    assert context.primary_workspace == owner.resolve()
    assert context.write_beads_dir == (owner / "sdd" / "beads").resolve()


def test_resolve_context_for_project_dry_run_does_not_materialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "caller"
    caller.mkdir()
    with BeadProject.init(owner):
        pass
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.chdir(caller)
    origin = BeadStoreOrigin(
        project_key="owner",
        project_label="owner",
        primary_workspace=owner,
        beads_dir=owner / "sdd" / "beads",
    )
    monkeypatch.setattr(
        "sase.bead.cross_project.origin_for_project_ref",
        lambda ref: origin if ref == "owner" else None,
    )
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace_for_project",
        lambda name: owner if name == "owner" else None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context._user_directed_context_for_project",
        lambda _project_key, _primary: None,
    )
    seen: list[dict[str, object]] = []
    from sase.bead import cli_common

    real_resolve = cli_common.resolve_beads_location

    def wrapped(*args: object, **kwargs: object) -> object:
        seen.append(dict(kwargs))
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        wrapped,
    )

    context = resolve_operation_context_for_project(
        "owner",
        cwd=caller,
        for_write=False,
        materialize=False,
    )

    assert context.write_beads_dir == (owner / "sdd" / "beads").resolve()
    assert seen
    assert all(item.get("materialize") in (False, None) for item in seen)


def test_invocation_belongs_to_project_for_primary_and_foreign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "caller"
    caller.mkdir()
    owner.mkdir()
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    origin = BeadStoreOrigin(
        project_key="owner",
        project_label="Owner",
        primary_workspace=owner,
        beads_dir=owner / "sdd" / "beads",
    )

    assert _invocation_belongs_to_project(origin, cwd=owner) is True
    assert _invocation_belongs_to_project(origin, cwd=caller) is False


def _seed_task(root: Path, title: str) -> str:
    with BeadProject.init(root) as project:
        issue = project.create(title, IssueType.TASK, task_type="bug", size="small")
    return issue.id


def _snapshot(project_key: str, primary: Path, issue_id: str) -> BeadStoreSnapshot:
    beads_dir = primary / "sdd" / "beads"
    return BeadStoreSnapshot(
        origin=BeadStoreOrigin(
            project_key=project_key,
            project_label=project_key,
            primary_workspace=primary,
            beads_dir=beads_dir,
        ),
        store_key=str(beads_dir),
        issue_ids=frozenset({issue_id}),
        issue_prefix=project_key,
        project_refs=frozenset({project_key}),
    )

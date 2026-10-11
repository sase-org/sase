"""Frontmatter ``project`` routing for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.cross_project import BeadStoreOrigin
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from tests.test_bead.cli_work_from_plan_helpers import (
    EPIC_PLAN,
    epic_plan_with_project,
    write_plan_update,
)
from tests.test_bead.resolution_test_helpers import (
    bead_store_snapshot,
    isolate_bead_store_resolution,
)


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


def test_plan_file_frontmatter_project_routes_from_non_project_cwd(
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
    _install_plan_project_origin(monkeypatch, project_key="owner", primary=owner)
    source = caller / "rollout.md"
    source.write_text(epic_plan_with_project("owner"), encoding="utf-8")

    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=False,
    )

    assert result.project == "owner"
    assert result.to_json()["project"] == "owner"
    assert result.archived_plan_path.is_relative_to(owner / "sdd" / "plans")
    assert not (caller / "sdd").exists()


def test_plan_file_frontmatter_project_routes_from_other_project_with_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    other = tmp_path / "other"
    with BeadProject.init(owner):
        pass
    with BeadProject.init(other):
        pass
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    isolate_bead_store_resolution(monkeypatch, other, project_name="other")
    _install_plan_project_origin(monkeypatch, project_key="owner", primary=owner)
    source = other / "rollout.md"
    source.write_text(epic_plan_with_project("owner"), encoding="utf-8")

    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=True,
    )

    output = capsys.readouterr().out
    assert result.project == "owner"
    assert result.archived_plan_path.is_relative_to(owner / "sdd" / "plans")
    assert "Project         owner" in output
    assert "frontmatter project owner" in output
    assert "working directory is other" in output
    assert not (other / "sdd" / "plans").exists() or not any(
        (other / "sdd" / "plans").rglob("rollout.md")
    )


def test_plan_file_same_project_cwd_does_not_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    with BeadProject.init(owner):
        pass
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    _install_plan_project_origin(monkeypatch, project_key="owner", primary=owner)
    monkeypatch.setattr(
        "sase.bead.operation_context.resolve_operation_context_for_project",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("same-project cwd must not route")
        ),
    )
    source = owner / "rollout.md"
    source.write_text(epic_plan_with_project("owner"), encoding="utf-8")

    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=False,
    )

    assert result.project == "owner"
    assert result.archived_plan_path.is_relative_to(owner / "sdd" / "plans")


def test_plan_file_without_project_field_keeps_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    with BeadProject.init(owner):
        pass
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.setattr(
        "sase.bead.operation_context.resolve_operation_context_for_project",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("plans without project must not route")
        ),
    )
    source = owner / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")

    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=False,
    )

    assert result.project is None
    assert "project" not in result.to_json()
    assert result.archived_plan_path.is_relative_to(owner / "sdd" / "plans")


def test_plan_file_unknown_project_fails_before_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    with BeadProject.init(owner):
        pass
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    source = owner / "rollout.md"
    source.write_text(epic_plan_with_project("missing-project"), encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cross_project.origin_for_project_ref",
        lambda _ref: None,
    )

    def _fail_if_called(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unknown project must fail before the launch lock")

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._epic_plan_launch_lock",
        _fail_if_called,
    )

    with pytest.raises(PlanFileWorkError, match="unknown or not enabled") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )
    assert "sase project list" in str(excinfo.value)
    assert excinfo.value.resume_command is not None


def test_plan_file_parent_project_mismatch_refuses_while_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    other = tmp_path / "other"
    caller = tmp_path / "caller"
    caller.mkdir()
    with BeadProject.init(owner):
        pass
    with BeadProject.init(other) as project:
        root = project.create("Root epic", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Owner phase", IssueType.PHASE, parent_id=root.id)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.chdir(caller)
    _install_plan_project_origin(monkeypatch, project_key="owner", primary=owner)
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (bead_store_snapshot("other", other, root.id, phase.id),),
    )
    source = caller / "child.md"
    source.write_text(
        epic_plan_with_project("owner", parent_id=phase.id),
        encoding="utf-8",
    )

    with pytest.raises(PlanFileWorkError, match="--parent top-level") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=True,
            yes=False,
            no_push=False,
            render=False,
        )
    message = str(excinfo.value)
    assert "owner" in message
    assert "other" in message


def test_plan_file_dry_run_route_does_not_materialize(
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
    _install_plan_project_origin(monkeypatch, project_key="owner", primary=owner)
    calls: list[dict[str, object]] = []
    from sase.bead.operation_context import resolve_operation_context_for_project

    real = resolve_operation_context_for_project

    def wrapped(project_ref: str, **kwargs: object) -> object:
        calls.append(dict(kwargs))
        return real(project_ref, **kwargs)

    monkeypatch.setattr(
        "sase.bead.operation_context.resolve_operation_context_for_project",
        wrapped,
    )
    source = caller / "rollout.md"
    source.write_text(epic_plan_with_project("owner"), encoding="utf-8")

    work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=False,
    )

    assert calls
    assert all(item.get("for_write") is False for item in calls)
    assert all(item.get("materialize") is False for item in calls)


def test_plan_file_archive_receives_routed_primary_root(
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
    _install_plan_project_origin(monkeypatch, project_key="owner", primary=owner)
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )
    seen: list[Path | None] = []
    from sase.sdd import plan_archive

    real_archive = plan_archive.archive_plan_file

    def wrapped(*args: object, **kwargs: object) -> object:
        primary_root = kwargs.get("primary_root")
        seen.append(primary_root if isinstance(primary_root, Path) else None)
        return real_archive(*args, **kwargs)

    monkeypatch.setattr("sase.sdd.plan_archive.archive_plan_file", wrapped)
    source = caller / "rollout.md"
    source.write_text(epic_plan_with_project("owner"), encoding="utf-8")

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.epic_id is not None
    assert seen
    assert seen[0] is not None
    assert seen[0].resolve() == owner.resolve()
    assert not (caller / "sdd").exists()


def _install_plan_project_origin(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_key: str,
    primary: Path,
    project_label: str | None = None,
) -> BeadStoreOrigin:
    origin = BeadStoreOrigin(
        project_key=project_key,
        project_label=project_label or project_key,
        primary_workspace=primary,
        beads_dir=primary / "sdd" / "beads",
    )
    refs = {project_key, origin.project_label}

    def origin_for_ref(ref: str) -> BeadStoreOrigin | None:
        return origin if ref in refs else None

    monkeypatch.setattr(
        "sase.bead.cross_project.origin_for_project_ref",
        origin_for_ref,
    )
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace_for_project",
        lambda name: primary if name == project_key else None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context._user_directed_context_for_project",
        lambda _project_key, _primary: None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context._writable_beads_dir_for_context",
        lambda _context: None,
    )
    return origin

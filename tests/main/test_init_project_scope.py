"""Tests for active-main-project inventory used by ``sase init --all``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.main import init_project_scope


def _record(
    tmp_path: Path,
    project_name: str,
    *,
    display_name: str | None = None,
    state: str = "enabled",
    system_managed: bool = False,
    workspace_exists: bool = True,
    project_file_exists: bool = True,
    is_project: bool = True,
    warnings: list[str] | None = None,
    parse_warnings: list[str] | None = None,
    aliases: list[str] | None = None,
) -> ProjectRecordWire:
    project_dir = tmp_path / "projects" / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{project_name}.sase"
    if project_file_exists:
        project_file.write_text("NAME: test\n", encoding="utf-8")
    workspace = tmp_path / "workspaces" / project_name
    if workspace_exists:
        workspace.mkdir(parents=True, exist_ok=True)
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(workspace),
        state=state,
        state_explicit=True,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=state == "enabled",
        aliases=aliases or [],
        warnings=warnings or [],
        parse_warnings=parse_warnings or [],
        display_name=display_name,
        is_project=is_project,
    )


def test_inventory_selects_and_sorts_active_main_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record(tmp_path, "zeta", display_name="Alpha"),
        _record(tmp_path, "beta", display_name="beta"),
        _record(tmp_path, "disabled", state="disabled"),
        _record(tmp_path, "sibling", state="sibling"),
        _record(tmp_path, "home"),
        _record(tmp_path, "managed", system_managed=True),
        _record(tmp_path, "skill-use-telemetry", is_project=False),
    ]
    calls: list[tuple[object, object, object, object]] = []

    def fake_list(  # type: ignore[no-untyped-def]
        root, states, *, include_home, projects_only
    ):
        calls.append((root, states, include_home, projects_only))
        return records

    monkeypatch.setattr(init_project_scope, "list_project_records", fake_list)
    monkeypatch.setattr(
        init_project_scope, "sase_projects_dir", lambda: tmp_path / "projects"
    )

    inventory = init_project_scope.resolve_init_project_inventory()

    assert inventory.error is None
    assert [target.project_name for target in inventory.targets] == ["zeta", "beta"]
    assert calls == [(tmp_path / "projects", "enabled", False, True)]


def test_inventory_preserves_warnings_and_unavailable_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record(
            tmp_path,
            "missing-file",
            project_file_exists=False,
            warnings=["record warning"],
            parse_warnings=["parse warning"],
        ),
        _record(tmp_path, "missing-workspace", workspace_exists=False),
        _record(tmp_path, "healthy"),
    ]
    monkeypatch.setattr(
        init_project_scope,
        "list_project_records",
        lambda *args, **kwargs: records,
    )

    inventory = init_project_scope.resolve_init_project_inventory()
    targets = {target.project_name: target for target in inventory.targets}

    assert targets["healthy"].unavailable_reason is None
    assert "project file is unavailable" in (
        targets["missing-file"].unavailable_reason or ""
    )
    assert targets["missing-file"].warnings == ("record warning", "parse warning")
    assert "primary workspace is unavailable" in (
        targets["missing-workspace"].unavailable_reason or ""
    )


def test_inventory_failure_is_returned_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(init_project_scope, "list_project_records", fail)

    inventory = init_project_scope.resolve_init_project_inventory()

    assert inventory.targets == ()
    assert (
        inventory.error
        == "project inventory could not be loaded: inventory unavailable"
    )


def test_select_init_project_targets_matches_name_display_and_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record(tmp_path, "alpha", display_name="Alpha", aliases=["a"]),
        _record(tmp_path, "beta", display_name="Beta"),
        _record(tmp_path, "gamma"),
    ]
    monkeypatch.setattr(
        init_project_scope,
        "list_project_records",
        lambda *args, **kwargs: records,
    )

    inventory = init_project_scope.resolve_init_project_inventory()
    selected = init_project_scope.select_init_project_targets(
        inventory, ["Beta", "a", "gamma", "alpha"]
    )

    assert selected.error is None
    assert [target.project_name for target in selected.targets] == [
        "beta",
        "alpha",
        "gamma",
    ]


def test_select_init_project_targets_rejects_unknown_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [_record(tmp_path, "alpha", display_name="Alpha", aliases=["a"])]
    monkeypatch.setattr(
        init_project_scope,
        "list_project_records",
        lambda *args, **kwargs: records,
    )

    inventory = init_project_scope.resolve_init_project_inventory()
    selected = init_project_scope.select_init_project_targets(inventory, ["missing"])

    assert selected.targets == ()
    assert selected.error is not None
    assert "unknown or non-enabled project 'missing'" in selected.error
    assert "alpha" in selected.error
    assert "Alpha" in selected.error
    assert "a" in selected.error

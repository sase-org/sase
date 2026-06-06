"""Tests for reusable project alias service helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_aliases import allocate_project_alias, ensure_project_alias_locked
from tests.main.project_handler_helpers import (
    _write_project,
    lifecycle_stubs,
    projects_root,
)

__all__ = ["lifecycle_stubs", "projects_root"]


def _record(
    project_name: str,
    *,
    aliases: list[str] | None = None,
    state: str = "active",
    system_managed: bool = False,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state=state,
        state_explicit=False,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=state == "active",
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
    )


def test_allocate_project_alias_uses_available_base() -> None:
    assert allocate_project_alias("foo", [_record("alpha")]) == "foo"


def test_allocate_project_alias_skips_real_project_name_collision() -> None:
    assert allocate_project_alias("foo", [_record("foo")]) == "foo-2"


def test_allocate_project_alias_skips_alias_collision() -> None:
    assert allocate_project_alias("foo", [_record("alpha", aliases=["foo"])]) == (
        "foo-2"
    )


def test_allocate_project_alias_uses_inactive_and_sibling_records() -> None:
    records = [
        _record("alpha", aliases=["foo"], state="inactive"),
        _record("foo-2", state="sibling"),
    ]

    assert allocate_project_alias("foo", records) == "foo-3"


def test_allocate_project_alias_walks_hyphenated_suffixes() -> None:
    records = [
        _record("foo"),
        _record("alpha", aliases=["foo-2"]),
        _record("beta", aliases=["foo-3"]),
    ]

    assert allocate_project_alias("foo", records) == "foo-4"


def test_allocate_project_alias_reuses_current_project_alias() -> None:
    records = [
        _record("alpha", aliases=["foo"]),
        _record("foo-2"),
    ]

    assert allocate_project_alias("foo", records, project_name="alpha") == "foo"


def test_allocate_project_alias_rejects_invalid_base() -> None:
    with pytest.raises(ValueError, match="invalid project alias"):
        allocate_project_alias(".hidden", [])


def test_ensure_project_alias_locked_preserves_existing_aliases_and_sorts(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "PROJECT_ALIASES: zed\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )

    record = ensure_project_alias_locked("alpha", "bob", projects_root=projects_root)

    assert record.aliases == ["bob", "zed"]
    assert "PROJECT_ALIASES: bob, zed\n" in project_file.read_text(encoding="utf-8")


def test_ensure_project_alias_locked_is_idempotent(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "PROJECT_ALIASES: bob, zed\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )

    record = ensure_project_alias_locked("alpha", "bob", projects_root=projects_root)

    content = project_file.read_text(encoding="utf-8")
    assert record.aliases == ["bob", "zed"]
    assert content.count("bob") == 1


def test_ensure_project_alias_locked_rejects_sibling_alias_collision(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )
    _write_project(
        projects_root,
        "beta",
        "PROJECT_STATE: sibling\nPROJECT_ALIASES: bob\n"
        "WORKSPACE_DIR: /tmp/beta\nNAME: b\n",
    )

    with pytest.raises(ValueError, match="assigned to both"):
        ensure_project_alias_locked("alpha", "bob", projects_root=projects_root)

    assert "PROJECT_ALIASES" not in project_file.read_text(encoding="utf-8")

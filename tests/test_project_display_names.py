"""Tests for display-only project name resolution."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase import project_display_names as pdn


def _record(project_name: str, display_name: str | None = None) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state="active",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def test_project_display_name_for_resolves_and_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [_record("gh_acme__widgets", "widgets"), _record("plain")]

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    assert pdn.project_display_name_for("plain", root) == "plain"
    assert pdn.project_display_name_for("missing", root) == "missing"


def test_project_display_name_cache_invalidates_on_projects_dir_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    calls = 0
    display_name = "widgets"

    def fake_list_project_records(
        *_args: object, **_kwargs: object
    ) -> list[ProjectRecordWire]:
        nonlocal calls
        calls += 1
        return [_record("gh_acme__widgets", display_name)]

    monkeypatch.setattr(pdn, "list_project_records", fake_list_project_records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    display_name = "gadgets"
    assert pdn.project_display_name_for("gh_acme__widgets", root) == "widgets"
    assert calls == 1

    stat = root.stat()
    os.utime(
        root, ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000)
    )

    assert pdn.project_display_name_for("gh_acme__widgets", root) == "gadgets"
    assert calls == 2


def test_attach_project_display_names_duck_types_and_clears_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    records = [
        _record("gh_acme__widgets", "widgets"),
        _record("gh_acme__plain", "gh_acme__plain"),
    ]
    widgets = SimpleNamespace(
        project_file="/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase",
        project_display_name=None,
    )
    equal = SimpleNamespace(
        project_file="/tmp/projects/gh_acme__plain/gh_acme__plain.sase",
        project_display_name="stale",
    )
    missing = SimpleNamespace(
        project_file="/tmp/projects/missing/missing.sase",
        project_display_name="stale",
    )
    ignored = SimpleNamespace(project_file="/tmp/projects/ignored/ignored.sase")

    monkeypatch.setattr(pdn, "list_project_records", lambda *_a, **_kw: records)
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    pdn.attach_project_display_names([widgets, equal, missing, ignored], root)

    assert widgets.project_display_name == "widgets"
    assert equal.project_display_name is None
    assert missing.project_display_name is None
    assert not hasattr(ignored, "project_display_name")

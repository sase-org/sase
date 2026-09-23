"""Tests for the shared project accent backend (D6)."""

from __future__ import annotations

from sase.ace.tui.project_styles import (
    PROJECT_ACCENTS,
    project_accent,
    project_accent_index,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_accents import accent_among_keys


def _record(
    project_name: str,
    *,
    state: str = "enabled",
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
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=None,
        is_project=state != "sibling",
    )


def test_among_keys_is_enabled_non_system_projects() -> None:
    records = [
        _record("sase"),
        _record("bob"),
        _record("old", state="disabled"),
        _record("side", state="sibling"),
        _record("home", system_managed=True),
    ]
    assert accent_among_keys(records) == ("bob", "sase")


def test_accent_index_points_at_accent() -> None:
    among = ("bob", "sase")
    for key in among:
        assert PROJECT_ACCENTS[project_accent_index(key, among=among)] == (
            project_accent(key, among=among)
        )


def test_reexport_matches_shared_backend() -> None:
    from sase.project_accents import PROJECT_ACCENTS as SHARED_PALETTE

    assert PROJECT_ACCENTS == SHARED_PALETTE
    assert len(PROJECT_ACCENTS) == 18

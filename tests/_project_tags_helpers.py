"""Shared fixtures for the project-tags test modules.

Split from ``tests.test_project_tags``; the original module re-exports its
tests so its import path keeps working.

Not a conftest so files opt in by importing the fixtures directly. Names are
public so the ``test_project_tags_*`` split modules can share them without
importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import sase.project_tags.catalog as tag_catalog_module
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_accents import PROJECT_ACCENTS
from sase.project_tags import ProjectTagCatalog, build_targets
from sase.project_tags.catalog import _clear_project_tag_catalog_cache


def make_project_record(
    project_name: str,
    *,
    aliases: list[str] | None = None,
    display_name: str | None = None,
    state: str = "enabled",
    system_managed: bool = False,
    launchable: bool = True,
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
        launchable=launchable,
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
        is_project=state != "sibling",
    )


@pytest.fixture(name="tag_catalog")
def project_tag_catalog() -> ProjectTagCatalog:
    """A fake five-target catalog: sase, bob, widgets, disabled beta, home."""
    records = [
        make_project_record("sase"),
        make_project_record("bob", aliases=["bobby"]),
        make_project_record("gh_acme__widgets", display_name="widgets"),
        make_project_record("beta", state="disabled"),
        make_project_record("home", system_managed=True),
    ]
    workflow_types = {
        "sase": "gh",
        "bob": "git",
        "beta": "git",
        "home": "git",
        "gh_acme__widgets": "gh",
    }
    display_names = {"gh": "GitHub", "git": "Git (bare)"}

    def _detect(project_file: str) -> str:
        for record in records:
            if record.project_file == project_file:
                return workflow_types[record.project_name]
        raise ValueError(f"unknown project file {project_file}")

    return ProjectTagCatalog(
        targets=tuple(
            build_targets(
                records,
                detect_workflow_type=_detect,
                get_display_name=display_names.get,
            )
        ),
        accent_palette=tuple(PROJECT_ACCENTS),
    )


@pytest.fixture(autouse=True)
def patched_catalog(tag_catalog: ProjectTagCatalog):
    """Route every catalog load at the fake catalog (real core bindings)."""
    _clear_project_tag_catalog_cache()
    with patch.object(
        tag_catalog_module,
        "load_project_tag_catalog",
        return_value=tag_catalog,
    ):
        yield
    _clear_project_tag_catalog_cache()

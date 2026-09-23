"""Deterministic project-tag catalog fixtures for ACE PNG visual snapshots.

The tag catalog snapshot is process-global (``_CATALOG_CACHE``), and the TUI
warms it off-thread at startup from the host's real projects directory. Goldens
must never depend on host projects or on test order, so the visual harness pins
this fixed catalog and resets it between tests (see ``conftest.py``).
"""

from __future__ import annotations

import pytest

import sase.project_tags.catalog as tag_catalog_module
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_accents import PROJECT_ACCENTS
from sase.project_tags import ProjectTagCatalog, build_targets

VISUAL_TAG_SIGNATURE = ("visual-tag-fixture",)


def _record(
    project_name: str,
    *,
    state: str = "enabled",
    vcs_kind: str | None = "gh",
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
        is_project=True,
        vcs_kind=vcs_kind,
    )


def visual_project_tag_catalog() -> ProjectTagCatalog:
    """Return the fixed visual-suite tag catalog.

    Fixed projects: ``sase`` and ``bob-cli`` (enabled, accented), ``home``
    (system, neutral), and ``oldproj`` (disabled, neutral). Accents come from
    the shared ``build_targets`` path so goldens pin real accent wiring.
    """
    records = [
        _record("sase"),
        _record("bob-cli"),
        _record("home", vcs_kind="git", system_managed=True),
        _record("oldproj", state="disabled"),
    ]

    def _workflow_type(project_file: object) -> str | None:
        if "home" in str(project_file):
            return "git"
        return "gh"

    def _display_name(workflow_type: str) -> str:
        if workflow_type == "gh":
            return "GitHub"
        if workflow_type == "git":
            return "git"
        return workflow_type

    targets = tuple(
        build_targets(
            records,
            detect_workflow_type=_workflow_type,
            get_display_name=_display_name,
        )
    )
    return ProjectTagCatalog(
        targets=targets,
        accent_palette=tuple(PROJECT_ACCENTS),
        signature=VISUAL_TAG_SIGNATURE,
    )


def patch_visual_project_tag_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> ProjectTagCatalog:
    """Pin the fixture catalog and block background warm from host projects.

    The cache pin covers ``peek`` render paths, but the TUI warms the
    catalog off-thread at startup through ``sase.project_tags`` package
    bindings (``_startup_loads`` and the VCS completion warm), which a
    submodule-attribute stub of the loader does not intercept: the real
    loader would rebuild from the test-isolated (home-only) projects dir
    and clobber the pin. Every real load funnels through
    ``_build_catalog``, so stubbing it pins fixture content no matter
    which binding the warm path uses.
    """
    catalog = visual_project_tag_catalog()
    monkeypatch.setattr(
        tag_catalog_module, "_CATALOG_CACHE", (catalog.signature, catalog)
    )
    monkeypatch.setattr(
        tag_catalog_module, "load_project_tag_catalog", lambda *a, **k: catalog
    )
    monkeypatch.setattr(
        tag_catalog_module,
        "_build_catalog",
        lambda projects_dir: visual_project_tag_catalog(),
    )
    return catalog

"""Shared fixtures and builders for ``+`` VCS project completion tests.

Split from ``tests/test_xprompt_vcs_project_completion.py``: the catalog
builder, caching, payload, ordering, and filtering tests live in thematic
``tests/test_xprompt_vcs_project_completion_*.py`` modules and share these
helpers.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.xprompt import vcs_project_completion as vpc
from sase.xprompt.vcs_project_completion import VcsProjectEntry


#: Real MRU rank builder, captured before the module autouse fixture stubs it.
_REAL_MRU_CATALOG_RANK = vpc._mru_catalog_rank


@pytest.fixture(autouse=True)
def clear_vcs_project_completion_cache() -> Iterator[None]:
    """Keep the module-level catalog cache from leaking across tests.

    Neutralizes current-project/MRU row ordering so builder expectations
    stay alphabetical and hermetic regardless of this machine's MRU;
    ordering itself is covered by dedicated tests.
    """
    vpc._clear_vcs_project_completion_cache()
    with (
        patch.object(vpc, "_current_catalog_key", return_value=None),
        patch.object(vpc, "_mru_catalog_rank", return_value={}),
    ):
        yield
    vpc._clear_vcs_project_completion_cache()


def _record(
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
    )


def _patch_catalog(records, workflow_types, display_names=None):
    """Patch the builder's project enumeration + provider lookups."""
    display_names = display_names or {}

    def _detect(project_file: str) -> str:
        for record in records:
            if record.project_file == project_file:
                prefix = workflow_types.get(record.project_name)
                if prefix is None:
                    raise ValueError(f"no plugin for {project_file}")
                return prefix
        raise ValueError(f"unknown project file {project_file}")

    return (
        patch.object(vpc, "list_project_records", return_value=records),
        patch.object(vpc, "detect_workflow_type", side_effect=_detect),
        patch.object(
            vpc, "get_display_name", side_effect=lambda wt: display_names.get(wt)
        ),
    )


def _patch(name: str, project: str, status: str):
    return SimpleNamespace(name=name, project_basename=project, status=status)


def _entry(name: str, *, aliases: tuple[str, ...] = ()) -> VcsProjectEntry:
    return VcsProjectEntry(
        name=name,
        vcs_prefix="gh",
        display_tag=f"#gh:{name}",
        provider_display="GitHub",
        aliases=aliases,
    )

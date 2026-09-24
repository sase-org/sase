"""Catalog payload, D7 row ordering, and filtering tests for ``+`` completion."""

from __future__ import annotations

from unittest.mock import patch

from sase.workspace_provider import VcsNamespaceEntry
from sase.xprompt import vcs_project_completion as vpc
from sase.xprompt.vcs_project_completion import (
    VCS_PROJECT_CATALOG_SCHEMA_VERSION,
    build_vcs_project_completion_entries,
    filter_vcs_project_entries,
    vcs_project_catalog_payload,
)
from tests._xprompt_vcs_project_completion_helpers import (
    _entry,
    _patch_catalog,
    _record,
    clear_vcs_project_completion_cache as clear_vcs_project_completion_cache,
)


def test_catalog_payload_bundles_entries_and_workflow_names() -> None:
    records = [_record("sase"), _record("bob", aliases=["bobby"])]
    workflow_types = {"sase": "gh", "bob": "git"}
    display_names = {"gh": "GitHub", "git": "Git (bare)"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types, display_names)

    from sase.project_accents import PROJECT_ACCENTS, project_accent_index
    from sase.project_tags.catalog import ProjectTagCatalog, build_targets

    def _fake_detect(project_file: str) -> str:
        for record in records:
            if record.project_file == project_file:
                prefix = workflow_types.get(record.project_name)
                if prefix is None:
                    raise ValueError(f"no plugin for {project_file}")
                return prefix
        raise ValueError(f"unknown project file {project_file}")

    tag_catalog = ProjectTagCatalog(
        targets=tuple(
            build_targets(
                records,
                detect_workflow_type=_fake_detect,
                get_display_name=display_names.get,
            )
        ),
        accent_palette=tuple(PROJECT_ACCENTS),
    )
    among = ("bob", "sase")

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(vpc, "get_workflow_names", return_value={"spy", "gh", "git"}),
        patch.object(vpc, "load_project_tag_catalog", return_value=tag_catalog),
        patch(
            "sase.xprompt.vcs_ref_completion.vcs_ref_namespaces_by_workflow",
            return_value={
                "gh": (
                    VcsNamespaceEntry(
                        name="sase-org",
                        description="2 enabled projects",
                        kind_label="org",
                    ),
                ),
                "git": (),
                "spy": (),
            },
        ),
    ):
        payload = vcs_project_catalog_payload(projects_dir="/tmp/projects")

    assert payload["schema_version"] == VCS_PROJECT_CATALOG_SCHEMA_VERSION
    assert payload["schema_version"] == 5
    # Workflow names cover every known prefix (not just active ones), sorted.
    assert payload["workflow_names"] == ["gh", "git", "spy"]
    # Entries mirror VcsProjectEntry field-for-field, sorted by name, so the
    # Rust loader deserializes them directly.
    assert payload["entries"] == [
        {
            "name": "bob",
            "vcs_prefix": "git",
            "display_tag": "#git:bob",
            "provider_display": "Git (bare)",
            "description": "",
            "aliases": ["bobby"],
            "kind": "project",
            "project": "bob",
            "status": "",
            "key": "bob",
            "tag": "+bob",
            "accent_index": project_accent_index("bob", among=among),
            "current": False,
        },
        {
            "name": "sase",
            "vcs_prefix": "gh",
            "display_tag": "#gh:sase",
            "provider_display": "GitHub",
            "description": "",
            "aliases": [],
            "kind": "project",
            "project": "sase",
            "status": "",
            "key": "sase",
            "tag": "+sase",
            "accent_index": project_accent_index("sase", among=among),
            "current": False,
        },
    ]
    assert payload["namespaces"] == {
        "gh": [
            {
                "name": "sase-org",
                "description": "2 enabled projects",
                "kind_label": "org",
            }
        ],
        "git": [],
        "spy": [],
    }
    # v5 additions: the Python-owned accent palette and every tag target.
    assert payload["accent_palette"] == list(PROJECT_ACCENTS)
    assert payload["project_tags"] == [
        {
            "key": "bob",
            "name": "bob",
            "aliases": ["bobby"],
            "workflow_type": "git",
            "state": "enabled",
            "workspace_dir": "/tmp/workspaces/bob",
        },
        {
            "key": "sase",
            "name": "sase",
            "aliases": [],
            "workflow_type": "gh",
            "state": "enabled",
            "workspace_dir": "/tmp/workspaces/sase",
        },
    ]


# --- D7 row ordering ------------------------------------------------------


def test_catalog_orders_current_project_first() -> None:
    records = [_record("sase"), _record("bob"), _record("zed")]
    workflow_types = {"sase": "gh", "bob": "git", "zed": "git"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(vpc, "_current_catalog_key", return_value="zed"),
        patch.object(vpc, "_mru_catalog_rank", return_value={"sase": 0}),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [e.name for e in entries] == ["zed", "sase", "bob"]
    assert [e.current for e in entries] == [True, False, False]


def test_catalog_orders_mru_recency_before_name() -> None:
    records = [_record("sase"), _record("bob"), _record("zed")]
    workflow_types = {"sase": "gh", "bob": "git", "zed": "git"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(vpc, "_current_catalog_key", return_value=None),
        patch.object(vpc, "_mru_catalog_rank", return_value={"zed": 0, "bob": 1}),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [e.name for e in entries] == ["zed", "bob", "sase"]
    assert [e.current for e in entries] == [False, False, False]


# --- Filtering -------------------------------------------------------------


def test_filter_empty_query_returns_all() -> None:
    entries = [_entry("bob"), _entry("sase")]
    assert filter_vcs_project_entries(entries, "") == entries


def test_filter_prefix_case_insensitive() -> None:
    entries = [_entry("bob"), _entry("sase"), _entry("saseling")]
    result = filter_vcs_project_entries(entries, "SA")
    assert [e.name for e in result] == ["sase", "saseling"]


def test_filter_matches_aliases() -> None:
    entries = [_entry("sase", aliases=("seaside",)), _entry("bob")]
    result = filter_vcs_project_entries(entries, "sea")
    assert [e.name for e in result] == ["sase"]


def test_filter_no_match() -> None:
    entries = [_entry("bob"), _entry("sase")]
    assert filter_vcs_project_entries(entries, "zzz") == []

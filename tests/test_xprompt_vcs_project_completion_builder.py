"""Catalog-builder tests for ``+`` VCS project completion."""

from __future__ import annotations

from unittest.mock import patch

from sase.xprompt import vcs_project_completion as vpc
from sase.xprompt.vcs_project_completion import (
    VcsProjectEntry,
    build_vcs_project_completion_entries,
    filter_vcs_project_entries,
)
from tests._project_display_case import ProjectDisplayCase
from tests._xprompt_vcs_project_completion_helpers import (
    _patch,
    _patch_catalog,
    _record,
    clear_vcs_project_completion_cache as clear_vcs_project_completion_cache,
)


def test_builder_basic_entries_sorted_by_name() -> None:
    records = [
        _record("sase"),
        _record("bob", aliases=["bobby"]),
    ]
    workflow_types = {"sase": "gh", "bob": "git"}
    display_names = {"gh": "GitHub", "git": "Git (bare)"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types, display_names)

    with list_p, detect_p, display_p:
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [e.name for e in entries] == ["bob", "sase"]
    bob, sase = entries
    assert bob == VcsProjectEntry(
        name="bob",
        vcs_prefix="git",
        display_tag="#git:bob",
        provider_display="Git (bare)",
        description="",
        aliases=("bobby",),
        kind="project",
        project="bob",
        status="",
        key="bob",
        tag="+bob",
        accent_index=bob.accent_index,
        current=False,
    )
    assert bob.accent_index is not None
    assert sase.display_tag == "#gh:sase"
    assert sase.provider_display == "GitHub"
    assert sase.key == "sase"
    assert sase.tag == "+sase"
    assert sase.accent_index is not None
    assert sase.accent_index != bob.accent_index
    assert sase.current is False


def test_builder_uses_project_name_as_completion_display() -> None:
    records = [
        _record("gh_acme__widgets", aliases=["legacy"], display_name="widgets"),
    ]
    workflow_types = {"gh_acme__widgets": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p, detect_p, display_p:
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert entries == [
        VcsProjectEntry(
            name="widgets",
            vcs_prefix="gh",
            display_tag="#gh:widgets",
            provider_display="gh",
            description="",
            aliases=("legacy", "gh_acme__widgets"),
            kind="project",
            project="gh_acme__widgets",
            status="",
            key="gh_acme__widgets",
            tag="+widgets",
            accent_index=entries[0].accent_index,
            current=False,
        )
    ]
    assert entries[0].accent_index is not None


def test_builder_excludes_system_managed_and_non_launchable() -> None:
    records = [
        _record("sase"),
        _record("home", system_managed=True),
        _record("dotfiles", launchable=False),
    ]
    workflow_types = {"sase": "gh", "home": "git", "dotfiles": "git"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p, detect_p, display_p:
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [e.name for e in entries] == ["sase"]


def test_builder_skips_undetectable_workflow_type() -> None:
    """A project whose provider plugin is absent is silently skipped."""
    records = [_record("sase"), _record("mystery")]
    workflow_types = {"sase": "gh"}  # "mystery" -> ValueError
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p, detect_p, display_p:
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [e.name for e in entries] == ["sase"]


def test_builder_provider_display_falls_back_to_prefix() -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types, {})

    with list_p, detect_p, display_p:
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert entries[0].provider_display == "gh"


def test_builder_dedupes_by_name() -> None:
    records = [_record("sase"), _record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p, detect_p, display_p:
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert len(entries) == 1


def test_builder_appends_active_patches_after_projects() -> None:
    records = [_record("sase"), _record("bob")]
    workflow_types = {"sase": "gh", "bob": "git"}
    display_names = {"gh": "GitHub", "git": "Git"}
    patches = [
        _patch("ship-z", "sase", "Ready"),
        _patch("draft-b", "bob", "Draft (bob_2)"),
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types, display_names)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(vpc, "_iter_enabled_project_patches", return_value=patches),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [(entry.kind, entry.project, entry.name) for entry in entries] == [
        ("project", "bob", "bob"),
        ("project", "sase", "sase"),
        ("patch", "bob", "draft-b"),
        ("patch", "sase", "ship-z"),
    ]
    draft = entries[2]
    assert draft.display_tag == "#git:draft-b"
    assert draft.status == "Draft"


def test_builder_projects_patch_rows_but_keeps_canonical_search_identity(
    project_display_case: ProjectDisplayCase,
) -> None:
    records = [project_display_case.project_record()]
    workflow_types = {project_display_case.project_key: "gh"}
    patches = [
        _patch(
            project_display_case.patch_key,
            project_display_case.project_key,
            "Ready",
        )
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(
            vpc,
            "_iter_enabled_project_patches",
            return_value=patches,
        ),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects",
            use_cache=False,
        )

    patch_entry = next(entry for entry in entries if entry.kind == "patch")
    assert patch_entry.name == project_display_case.patch_label
    assert patch_entry.display_tag == f"#gh:{project_display_case.patch_label}"
    assert patch_entry.project == project_display_case.project_key
    assert patch_entry.aliases == (project_display_case.patch_key,)
    assert filter_vcs_project_entries(
        entries,
        project_display_case.patch_key,
    ) == [patch_entry]


def test_builder_filters_patch_status_and_missing_project() -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    patches = [
        _patch("active", "sase", "Mailed"),
        _patch("done", "sase", "Submitted"),
        _patch("other", "missing", "Ready"),
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(vpc, "_iter_enabled_project_patches", return_value=patches),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [(entry.kind, entry.name) for entry in entries] == [
        ("project", "sase"),
        ("patch", "active"),
    ]


def test_builder_allows_changespec_name_to_match_project_name() -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    patches = [_patch("sase", "sase", "WIP")]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(vpc, "_iter_enabled_project_patches", return_value=patches),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [(entry.kind, entry.name, entry.display_tag) for entry in entries] == [
        ("project", "sase", "#gh:sase"),
        ("patch", "sase", "#gh:sase"),
    ]

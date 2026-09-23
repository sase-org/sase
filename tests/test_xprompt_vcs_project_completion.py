"""Tests for the ``+`` VCS project completion foundations.

Covers the active-project catalog builder, prefix filtering, the v5 catalog
payload, and D7 row ordering. Trigger detection and the in-place accept
algorithm now live in the Rust core; their golden vectors moved to the
core's ``project_tag/tests.rs`` with the tui-editor phase.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.workspace_provider import VcsNamespaceEntry
from sase.xprompt import vcs_project_completion as vpc
from sase.xprompt.vcs_project_completion import (
    VCS_PROJECT_CATALOG_SCHEMA_VERSION,
    VcsProjectEntry,
    build_vcs_project_completion_entries,
    filter_vcs_project_entries,
    vcs_project_catalog_payload,
)
from tests._project_display_case import ProjectDisplayCase


#: Real MRU rank builder, captured before the module autouse fixture stubs it.
_REAL_MRU_CATALOG_RANK = vpc._mru_catalog_rank


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    """Keep the module-level catalog cache from leaking across tests.

    Neutralizes current-project/MRU row ordering so builder expectations
    stay alphabetical and hermetic regardless of this machine's MRU;
    ordering itself is covered by dedicated tests below.
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


# --- Catalog builder -------------------------------------------------------


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


def _patch(name: str, project: str, status: str):
    return SimpleNamespace(name=name, project_basename=project, status=status)


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


# --- Caching ---------------------------------------------------------------


def test_builder_caches_on_unchanged_directory(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p as list_mock, detect_p, display_p:
        first = build_vcs_project_completion_entries(projects_dir=tmp_path)
        second = build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert first == second
    assert list_mock.call_count == 1


def test_clear_cache_forces_rebuild(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p as list_mock, detect_p, display_p:
        build_vcs_project_completion_entries(projects_dir=tmp_path)
        vpc._clear_vcs_project_completion_cache()
        build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert list_mock.call_count == 2


def test_use_cache_false_always_rebuilds(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p as list_mock, detect_p, display_p:
        build_vcs_project_completion_entries(projects_dir=tmp_path, use_cache=False)
        build_vcs_project_completion_entries(projects_dir=tmp_path, use_cache=False)

    assert list_mock.call_count == 2


def test_returned_list_is_isolated_from_cache(tmp_path) -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with list_p, detect_p, display_p:
        first = build_vcs_project_completion_entries(projects_dir=tmp_path)
        first.clear()
        second = build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert [e.name for e in second] == ["sase"]


def test_cache_invalidates_when_project_spec_mtime_changes(tmp_path) -> None:
    spec_file = tmp_path / "sase" / "sase.sase"
    spec_file.parent.mkdir()
    spec_file.write_text("NAME: first\nSTATUS: WIP\n", encoding="utf-8")
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    patch_versions = [
        [_patch("first", "sase", "WIP")],
        [_patch("second", "sase", "Ready")],
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p as list_mock,
        detect_p,
        display_p,
        patch.object(vpc, "iter_patch_project_files", return_value=[spec_file]),
        patch.object(
            vpc, "_iter_enabled_project_patches", side_effect=patch_versions
        ) as patch_mock,
    ):
        first = build_vcs_project_completion_entries(projects_dir=tmp_path)
        second = build_vcs_project_completion_entries(projects_dir=tmp_path)
        stat = spec_file.stat()
        os.utime(
            spec_file,
            ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000),
        )
        third = build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert [entry.name for entry in first if entry.kind == "patch"] == ["first"]
    assert second == first
    assert [entry.name for entry in third if entry.kind == "patch"] == ["second"]
    assert list_mock.call_count == 2
    assert patch_mock.call_count == 2


def test_cache_invalidates_when_mru_store_changes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``current`` badge and MRU order follow ``set-current`` (D7).

    ``sase project set-current`` writes only the MRU, so the entries cache
    keys on the MRU store alongside the spec signature.
    """
    import sase.history.vcs_xprompt_mru as mru_module

    records = [_record("sase"), _record("bob")]
    workflow_types = {"sase": "gh", "bob": "git"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)
    mru_file = tmp_path / "vcs_xprompt_mru.json"
    mru_file.write_text('{"entries": ["#gh:sase"]}', encoding="utf-8")
    monkeypatch.setattr(mru_module, "_MRU_FILE", mru_file)
    # Keep every MRU entry: with no resolvability snapshot the prune guards
    # keep entries rather than risk nuking the store, so the rank below is
    # computed from the real store contents.
    monkeypatch.setattr(mru_module, "_resolvable_vcs_ref_index", lambda: None)

    with (
        list_p as list_mock,
        detect_p,
        display_p,
        # Exercise the real recency rank; the module fixture stubs it.
        patch.object(vpc, "_mru_catalog_rank", _REAL_MRU_CATALOG_RANK),
    ):
        # The current key tracks the MRU head the way `set-current` writes
        # it; resolution itself is covered by the current-project tests.
        with patch.object(vpc, "_current_catalog_key", return_value="sase"):
            first = build_vcs_project_completion_entries(projects_dir=tmp_path)
            second = build_vcs_project_completion_entries(projects_dir=tmp_path)
        assert second == first
        assert list_mock.call_count == 1
        assert [entry.name for entry in first] == ["sase", "bob"]
        assert [entry.current for entry in first] == [True, False]
        # Rewrite the store the way `sase project set-current` does.
        mru_file.write_text(
            '{"entries": ["#git:bob", "#gh:sase", "#git:bob-extra"]}',
            encoding="utf-8",
        )
        stat = mru_file.stat()
        os.utime(
            mru_file,
            ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000),
        )
        with patch.object(vpc, "_current_catalog_key", return_value="bob"):
            third = build_vcs_project_completion_entries(projects_dir=tmp_path)
        assert [entry.name for entry in third] == ["bob", "sase"]
        assert [entry.current for entry in third] == [True, False]
        assert list_mock.call_count == 2


# --- Catalog payload (the LSP materialization contract) --------------------


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


def _entry(name: str, *, aliases: tuple[str, ...] = ()) -> VcsProjectEntry:
    return VcsProjectEntry(
        name=name,
        vcs_prefix="gh",
        display_tag=f"#gh:{name}",
        provider_display="GitHub",
        aliases=aliases,
    )


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

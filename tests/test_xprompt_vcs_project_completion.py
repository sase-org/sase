"""Tests for the ``+`` VCS project completion foundations.

Covers trigger detection, the active-project catalog builder, prefix filtering,
and the canonical expansion algorithm, including the cross-language golden
test-vector table that the Rust core must match byte-for-byte.
"""

from __future__ import annotations

import os
import re
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
    apply_vcs_project_selection,
    build_vcs_project_completion_entries,
    filter_vcs_project_entries,
    find_vcs_project_trigger,
    vcs_project_catalog_payload,
)
from tests._project_display_case import ProjectDisplayCase

# A replace pattern covering gh/git/spy regardless of which workspace-provider
# plugins happen to be installed in the test environment.
_TEST_VCS_REPLACE_PATTERN = re.compile(
    r"^((?:%\S+[\s]+)*)#(?:gh|git|spy)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)(?:\s|$)",
    re.MULTILINE,
)


def _patch_vcs_replace_pattern():
    """Patch the shared replace pattern used by the expansion transform."""
    return patch(
        "sase.xprompt._parsing._get_vcs_replace_pattern",
        return_value=_TEST_VCS_REPLACE_PATTERN,
    )


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    """Keep the module-level catalog cache from leaking across tests."""
    vpc._clear_vcs_project_completion_cache()
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


# --- Golden vectors (the cross-language parity contract) -------------------

# ``‸`` marks the caret. The trigger token starts at ``+``; most vectors place
# the caret at the end, while one asserts a cursor-local query inside a longer
# whole-token replacement span.
_CURSOR = "‸"

_GOLDEN_VECTORS = [
    ("Describe this repo. +‸", "#gh:sase Describe this repo."),
    ("+‸", "#gh:sase "),
    ("+sa‸", "#gh:sase "),
    ("+s‸\n", "#gh:sase \n"),
    ("+s‸\nmore text", "#gh:sase \nmore text"),
    ("#git:foo Fix bug +‸", "#gh:sase Fix bug"),
    ("#gh!!:foo do X +‸", "#gh:sase do X"),
    # Existing leading VCS tag at end-of-input (no trailing text): the trigger
    # strip leaves the bare tag at EOF, which must still be replaced, not
    # doubled.
    ("#gh:sase +‸", "#gh:sase "),
    ("#gh:sase +foo‸", "#gh:sase "),
    ("#git:foo +‸", "#gh:sase "),
    ("Fix +bug‸ here", "#gh:sase Fix here"),
    ("Line one\n +‸", "#gh:sase Line one\n"),
    ("---\nname: x\n---\nBody +‸", "---\nname: x\n---\n#gh:sase Body"),
    ("%model:opus Body +‸", "%model:opus #gh:sase Body"),
    ("+sa‸ Fix", "#gh:sase Fix"),
    ("Fix +sa‸se now", "#gh:sase Fix now"),
]


@pytest.mark.parametrize(("marked", "expected"), _GOLDEN_VECTORS)
def test_golden_vectors(marked: str, expected: str) -> None:
    """End-to-end trigger detection + expansion matches the golden table."""
    cursor = marked.index(_CURSOR)
    prompt = marked.replace(_CURSOR, "")

    trigger = find_vcs_project_trigger(prompt, cursor)
    assert trigger is not None

    with _patch_vcs_replace_pattern():
        result = apply_vcs_project_selection(prompt, trigger.span, "#gh:sase")

    assert result == expected


# --- Trigger detection -----------------------------------------------------


def test_trigger_at_beginning_of_prompt() -> None:
    trigger = find_vcs_project_trigger("+", 1)
    assert trigger is not None
    assert trigger.span == (0, 1)
    assert trigger.query == ""


def test_trigger_with_query() -> None:
    trigger = find_vcs_project_trigger("+sa", 3)
    assert trigger is not None
    assert trigger.span == (0, 3)
    assert trigger.query == "sa"


def test_trigger_after_space() -> None:
    trigger = find_vcs_project_trigger("Fix +bug", 8)
    assert trigger is not None
    assert trigger.span == (4, 8)
    assert trigger.query == "bug"


def test_trigger_after_space_on_new_line() -> None:
    trigger = find_vcs_project_trigger("line\n +x", 8)
    assert trigger is not None
    assert trigger.span == (6, 8)
    assert trigger.query == "x"


def test_trigger_token_extends_past_cursor() -> None:
    """The span covers the whole token; the query stops at the cursor."""
    trigger = find_vcs_project_trigger("Fix +abc", 6)
    assert trigger is not None
    assert trigger.span == (4, 8)
    assert trigger.query == "a"


def test_trigger_fires_after_literal_space() -> None:
    trigger = find_vcs_project_trigger("2 + 2", 3)
    assert trigger is not None
    assert trigger.span == (2, 3)
    assert trigger.query == ""


@pytest.mark.parametrize(
    ("prompt", "cursor"),
    [
        ("#+", 2),
        ("#+sa", 4),
        ("Fix #+sa", 8),
        ("line\n+", 6),
        ("\t+", 2),
        ("\N{NO-BREAK SPACE}+", 2),
        ("word+", 5),
        ("a+b", 3),
        ("c++", 3),
        ("c#+x", 4),
    ],
)
def test_unclaimed_plus_forms(prompt: str, cursor: int) -> None:
    assert find_vcs_project_trigger(prompt, cursor) is None


def test_no_trigger_before_cursor_advances_past_plus() -> None:
    """The caret must sit past ``+`` for the trigger to be live."""
    assert find_vcs_project_trigger("+", 0) is None


def test_hash_then_space_plus_triggers_at_plus() -> None:
    trigger = find_vcs_project_trigger("# +", 3)
    assert trigger is not None
    assert trigger.span == (2, 3)
    assert trigger.query == ""


def test_no_trigger_hash_without_plus() -> None:
    assert find_vcs_project_trigger("#", 1) is None


def test_no_trigger_with_cursor_inside_hash_plus_token() -> None:
    assert find_vcs_project_trigger("#+", 0) is None
    assert find_vcs_project_trigger("#+", 1) is None


def test_no_trigger_without_plus() -> None:
    assert find_vcs_project_trigger("hello world", 11) is None


def test_no_trigger_empty_prompt() -> None:
    assert find_vcs_project_trigger("", 0) is None


def test_no_trigger_cursor_out_of_range() -> None:
    assert find_vcs_project_trigger("+", 5) is None
    assert find_vcs_project_trigger("+", -1) is None


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
    )
    assert sase.display_tag == "#gh:sase"
    assert sase.provider_display == "GitHub"


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
        )
    ]


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


def _changespec(name: str, project: str, status: str):
    return SimpleNamespace(name=name, project_basename=project, status=status)


def test_builder_appends_active_changespecs_after_projects() -> None:
    records = [_record("sase"), _record("bob")]
    workflow_types = {"sase": "gh", "bob": "git"}
    display_names = {"gh": "GitHub", "git": "Git"}
    changespecs = [
        _changespec("ship-z", "sase", "Ready"),
        _changespec("draft-b", "bob", "Draft (bob_2)"),
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types, display_names)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(
            vpc, "_iter_enabled_project_changespecs", return_value=changespecs
        ),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [(entry.kind, entry.project, entry.name) for entry in entries] == [
        ("project", "bob", "bob"),
        ("project", "sase", "sase"),
        ("changespec", "bob", "draft-b"),
        ("changespec", "sase", "ship-z"),
    ]
    draft = entries[2]
    assert draft.display_tag == "#git:draft-b"
    assert draft.status == "Draft"


def test_builder_projects_changespec_rows_but_keeps_canonical_search_identity(
    project_display_case: ProjectDisplayCase,
) -> None:
    records = [project_display_case.project_record()]
    workflow_types = {project_display_case.project_key: "gh"}
    changespecs = [
        _changespec(
            project_display_case.changespec_key,
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
            "_iter_enabled_project_changespecs",
            return_value=changespecs,
        ),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects",
            use_cache=False,
        )

    changespec = next(entry for entry in entries if entry.kind == "changespec")
    assert changespec.name == project_display_case.changespec_label
    assert changespec.display_tag == f"#gh:{project_display_case.changespec_label}"
    assert changespec.project == project_display_case.project_key
    assert changespec.aliases == (project_display_case.changespec_key,)
    assert filter_vcs_project_entries(
        entries,
        project_display_case.changespec_key,
    ) == [changespec]


def test_builder_filters_changespec_status_and_missing_project() -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    changespecs = [
        _changespec("active", "sase", "Mailed"),
        _changespec("done", "sase", "Submitted"),
        _changespec("other", "missing", "Ready"),
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(
            vpc, "_iter_enabled_project_changespecs", return_value=changespecs
        ),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [(entry.kind, entry.name) for entry in entries] == [
        ("project", "sase"),
        ("changespec", "active"),
    ]


def test_builder_allows_changespec_name_to_match_project_name() -> None:
    records = [_record("sase")]
    workflow_types = {"sase": "gh"}
    changespecs = [_changespec("sase", "sase", "WIP")]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(
            vpc, "_iter_enabled_project_changespecs", return_value=changespecs
        ),
    ):
        entries = build_vcs_project_completion_entries(
            projects_dir="/tmp/projects", use_cache=False
        )

    assert [(entry.kind, entry.name, entry.display_tag) for entry in entries] == [
        ("project", "sase", "#gh:sase"),
        ("changespec", "sase", "#gh:sase"),
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
    changespec_versions = [
        [_changespec("first", "sase", "WIP")],
        [_changespec("second", "sase", "Ready")],
    ]
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types)

    with (
        list_p as list_mock,
        detect_p,
        display_p,
        patch.object(vpc, "iter_changespec_project_files", return_value=[spec_file]),
        patch.object(
            vpc, "_iter_enabled_project_changespecs", side_effect=changespec_versions
        ) as changespec_mock,
    ):
        first = build_vcs_project_completion_entries(projects_dir=tmp_path)
        second = build_vcs_project_completion_entries(projects_dir=tmp_path)
        stat = spec_file.stat()
        os.utime(
            spec_file,
            ns=(stat.st_atime_ns + 1_000_000_000, stat.st_mtime_ns + 1_000_000_000),
        )
        third = build_vcs_project_completion_entries(projects_dir=tmp_path)

    assert [entry.name for entry in first if entry.kind == "changespec"] == ["first"]
    assert second == first
    assert [entry.name for entry in third if entry.kind == "changespec"] == ["second"]
    assert list_mock.call_count == 2
    assert changespec_mock.call_count == 2


# --- Catalog payload (the LSP materialization contract) --------------------


def test_catalog_payload_bundles_entries_and_workflow_names() -> None:
    records = [_record("sase"), _record("bob", aliases=["bobby"])]
    workflow_types = {"sase": "gh", "bob": "git"}
    display_names = {"gh": "GitHub", "git": "Git (bare)"}
    list_p, detect_p, display_p = _patch_catalog(records, workflow_types, display_names)

    with (
        list_p,
        detect_p,
        display_p,
        patch.object(vpc, "get_workflow_names", return_value={"spy", "gh", "git"}),
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

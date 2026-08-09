"""Tests for VCS ref-root completion headless foundations."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from sase.workspace_provider import VcsNamespaceEntry, VcsRefNamespaces
from sase.workspace_provider import _registry as workspace_registry
from sase.xprompt import vcs_ref_completion as vrf
from sase.xprompt.vcs_project_completion import VcsProjectEntry
from sase.xprompt.vcs_ref_completion import (
    VCS_REF_GOLDEN_CURSOR,
    VCS_REF_GOLDEN_VECTORS,
    _VcsRefCompletionConfig,
    apply_vcs_ref_selection,
    build_vcs_ref_candidates,
    filter_vcs_ref_candidates,
    find_vcs_ref_trigger,
    load_vcs_ref_completion_config,
    vcs_ref_namespaces_by_workflow,
)


@pytest.fixture(autouse=True)
def _clear_ref_completion_cache() -> Iterator[None]:
    vrf._NAMESPACE_CACHE.clear()
    yield
    vrf._NAMESPACE_CACHE.clear()


@pytest.mark.parametrize(
    ("marked", "workflow_names", "selected_ref", "chain", "expected"),
    VCS_REF_GOLDEN_VECTORS,
)
def test_golden_vectors(
    marked: str,
    workflow_names: tuple[str, ...],
    selected_ref: str,
    chain: bool,
    expected: str,
) -> None:
    cursor = marked.index(VCS_REF_GOLDEN_CURSOR)
    prompt = marked.replace(VCS_REF_GOLDEN_CURSOR, "")

    trigger = find_vcs_ref_trigger(prompt, cursor, workflow_names)
    assert trigger is not None

    assert (
        apply_vcs_ref_selection(prompt, trigger, selected_ref, chain=chain) == expected
    )


def test_trigger_detects_empty_colon_ref() -> None:
    trigger = find_vcs_ref_trigger("#gh:", 4, {"gh"})

    assert trigger is not None
    assert trigger.workflow == "gh"
    assert trigger.separator == ":"
    assert trigger.query == ""
    assert trigger.span == (0, 4)
    assert trigger.value_span == (4, 4)
    assert trigger.query_span == (4, 4)


def test_trigger_detects_partial_query_mid_prompt() -> None:
    prompt = "Fix #gh:sa now"
    cursor = prompt.index("sa") + 2

    trigger = find_vcs_ref_trigger(prompt, cursor, {"gh"})

    assert trigger is not None
    assert trigger.workflow == "gh"
    assert trigger.query == "sa"
    assert trigger.span == (4, 10)
    assert trigger.value_span == (8, 10)
    assert trigger.query_span == (8, 10)


def test_trigger_detects_paren_form_with_hitl_marker() -> None:
    prompt = "#gh??(sa"

    trigger = find_vcs_ref_trigger(prompt, len(prompt), {"gh"})

    assert trigger is not None
    assert trigger.workflow == "gh"
    assert trigger.separator == "("
    assert trigger.query == "sa"


def test_trigger_after_newline() -> None:
    prompt = "line\n#git:"

    trigger = find_vcs_ref_trigger(prompt, len(prompt), {"git"})

    assert trigger is not None
    assert trigger.workflow == "git"
    assert trigger.query == ""


def test_trigger_query_stops_at_cursor_but_value_span_covers_ref() -> None:
    prompt = "#gh:sasex"
    cursor = prompt.index("sa") + 2

    trigger = find_vcs_ref_trigger(prompt, cursor, {"gh"})

    assert trigger is not None
    assert trigger.query == "sa"
    assert trigger.value_span == (4, len(prompt))


@pytest.mark.parametrize(
    ("prompt", "cursor"),
    [
        ("#gh", 3),
        ("#gh:owner/repo", 14),
        ("#gh:sase/repo", 7),
        ("#gh:~", 5),
        ("#gh:.", 5),
        ("#gh:/tmp", 8),
        ("#gh:https://github.com/bbugyi200/sase", 37),
        ("#gh:123)", 8),
        ("#gh_bbugyi200", 13),
        ("word#gh:", 8),
        ("#foo:x", 6),
        ("#gh(sa)", 7),
    ],
)
def test_trigger_negatives(prompt: str, cursor: int) -> None:
    assert find_vcs_ref_trigger(prompt, cursor, {"gh"}) is None


def test_trigger_rejects_cursor_out_of_range() -> None:
    assert find_vcs_ref_trigger("#gh:", -1, {"gh"}) is None
    assert find_vcs_ref_trigger("#gh:", 5, {"gh"}) is None


def test_trigger_requires_known_workflow() -> None:
    assert find_vcs_ref_trigger("#gh:", 4, set()) is None
    assert find_vcs_ref_trigger("#gh:", 4, {"git"}) is None


def test_config_reader_uses_defaults_and_overrides() -> None:
    assert load_vcs_ref_completion_config({}) == _VcsRefCompletionConfig()
    assert load_vcs_ref_completion_config(
        {"vcs_ref_completion": {"enabled": False}}
    ) == _VcsRefCompletionConfig(enabled=False)
    assert (
        load_vcs_ref_completion_config({"vcs_ref_completion": {"enabled": "no"}})
        == _VcsRefCompletionConfig()
    )


def _project(
    name: str,
    *,
    workflow: str = "gh",
    kind: str = "project",
    aliases: tuple[str, ...] = (),
) -> VcsProjectEntry:
    return VcsProjectEntry(
        name=name,
        vcs_prefix=workflow,
        display_tag=f"#{workflow}:{name}",
        provider_display=workflow,
        aliases=aliases,
        kind=kind,  # type: ignore[arg-type]
        project=name,
        status="Draft" if kind == "patch" else "",
    )


def test_build_candidates_filters_projects_by_workflow_and_appends_namespaces() -> None:
    namespace = VcsNamespaceEntry("sase-org", description="2 active projects")

    with (
        patch.object(
            vrf,
            "build_vcs_project_completion_entries",
            return_value=[
                _project("dotfiles", workflow="git"),
                _project("sase", workflow="gh"),
                _project("ship-it", workflow="gh", kind="patch"),
            ],
        ),
        patch.object(vrf, "_list_cached_namespaces", return_value=(namespace,)),
    ):
        result = build_vcs_ref_candidates(
            "gh",
            projects_dir="/tmp/projects",
            use_cache=False,
        )

    assert result == [
        _project("sase", workflow="gh"),
        _project("ship-it", workflow="gh", kind="patch"),
        namespace,
    ]


def test_build_candidates_disabled_skips_catalog_and_namespaces() -> None:
    with (
        patch.object(
            vrf,
            "build_vcs_project_completion_entries",
            side_effect=AssertionError("project catalog should not be read"),
        ),
        patch.object(
            vrf,
            "_list_cached_namespaces",
            side_effect=AssertionError("namespaces should not be read"),
        ),
    ):
        result = build_vcs_ref_candidates(
            "gh",
            config=_VcsRefCompletionConfig(enabled=False),
        )

    assert result == []


def test_filter_candidates_matches_project_aliases_and_namespace_names() -> None:
    candidates = [
        _project("sase", aliases=("seaside",)),
        _project("ship-it", kind="changespec"),
        VcsNamespaceEntry("sase-org"),
        VcsNamespaceEntry("bbugyi200"),
    ]

    assert filter_vcs_ref_candidates(candidates, "sea") == [candidates[0]]
    assert filter_vcs_ref_candidates(candidates, "SA") == [
        candidates[0],
        candidates[2],
    ]
    assert filter_vcs_ref_candidates(candidates, "zzz") == []


def test_namespace_cache_reuses_until_project_signature_changes(tmp_path) -> None:
    calls: list[str] = []
    responses = [
        VcsRefNamespaces((VcsNamespaceEntry("first"),)),
        VcsRefNamespaces((VcsNamespaceEntry("second"),)),
    ]

    def fake_list(workflow: str) -> VcsRefNamespaces:
        calls.append(workflow)
        return responses.pop(0)

    with (
        patch.object(vrf, "build_vcs_project_completion_entries", return_value=[]),
        patch.object(
            vrf,
            "vcs_project_catalog_signature",
            side_effect=["sig1", "sig1", "sig2"],
        ),
        patch.object(vrf, "list_ref_namespaces", side_effect=fake_list),
    ):
        first = build_vcs_ref_candidates("gh", projects_dir=tmp_path)
        second = build_vcs_ref_candidates("gh", projects_dir=tmp_path)
        third = build_vcs_ref_candidates("gh", projects_dir=tmp_path)

    assert [entry.name for entry in first] == ["first"]
    assert [entry.name for entry in second] == ["first"]
    assert [entry.name for entry in third] == ["second"]
    assert calls == ["gh", "gh"]


def test_namespaces_by_workflow_invokes_each_registered_workflow(tmp_path) -> None:
    def fake_list(workflow: str) -> VcsRefNamespaces:
        if workflow == "gh":
            return VcsRefNamespaces((VcsNamespaceEntry("sase-org"),))
        return VcsRefNamespaces()

    with (
        patch.object(vrf, "vcs_project_catalog_signature", return_value="sig"),
        patch.object(vrf, "list_ref_namespaces", side_effect=fake_list),
    ):
        result = vcs_ref_namespaces_by_workflow(
            {"git", "gh"},
            projects_dir=tmp_path,
        )

    assert result == {
        "gh": (VcsNamespaceEntry("sase-org"),),
        "git": (),
    }


def test_registry_wrapper_falls_back_to_empty_namespaces_on_hook_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BoomManager:
        def list_ref_namespaces(self, _workflow_type: str) -> VcsRefNamespaces | None:
            raise RuntimeError("boom")

    monkeypatch.setattr(workspace_registry, "_get_manager", lambda: BoomManager())

    assert workspace_registry.list_ref_namespaces("gh") == VcsRefNamespaces()

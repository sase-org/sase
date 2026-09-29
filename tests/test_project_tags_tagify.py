"""Humanizer tagify and known-target spelling tests for project tags.

Split from ``tests.test_project_tags``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.project_tags import ProjectTagCatalog, known_project_tag_for
from tests._project_tags_helpers import (
    patched_catalog,  # noqa: F401 (registers the autouse fixture)
    project_tag_catalog,  # noqa: F401 (registers the tag_catalog fixture)
)

__all__ = [
    "test_known_project_tag_for_matches_key_name_and_alias",
    "test_known_project_tag_for_rejects_unknown_names",
    "test_tagify_flag_off_and_cold_catalog_keep_hash_form",
    "test_tagify_keeps_refs_outside_tag_positions",
    "test_tagify_leaves_fenced_refs_verbatim",
    "test_tagify_matches_keys_names_and_aliases_case_insensitively",
    "test_tagify_never_rewrites_non_project_refs",
    "test_tagify_rewrites_matching_workflow_refs",
]


# --- Humanizer tagify (D5) ------------------------------------------------------


_DISPLAY_BY_KEY = {
    "sase": "sase",
    "bob": "bob",
    "gh_acme__widgets": "widgets",
    "beta": "beta",
    "home": "home",
}


def _humanize_with_catalog(
    prompt: str,
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_tags: bool = True,
) -> str:
    """Humanize *prompt* with the fake catalog as the warm peek snapshot."""
    from sase.project_aliases import humanize_project_refs_in_prompt

    monkeypatch.setattr(
        "sase.project_alias_prompts._project_tag_targets_for_tagify",
        lambda _seam: tag_catalog.targets,
    )
    return humanize_project_refs_in_prompt(
        prompt,
        _DISPLAY_BY_KEY,
        project_tags=project_tags,
    )


def test_tagify_rewrites_matching_workflow_refs(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _humanize_with_catalog("#gh:sase run", tag_catalog, monkeypatch) == (
        "+sase run"
    )
    assert _humanize_with_catalog("#git:bob run", tag_catalog, monkeypatch) == (
        "+bob run"
    )
    assert _humanize_with_catalog("#gh:widgets run", tag_catalog, monkeypatch) == (
        "+widgets run"
    )
    assert _humanize_with_catalog("#git:home run", tag_catalog, monkeypatch) == (
        "+home run"
    )


def test_tagify_matches_keys_names_and_aliases_case_insensitively(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _humanize_with_catalog("#gh:Sase run", tag_catalog, monkeypatch) == (
        "+sase run"
    )
    assert (
        _humanize_with_catalog("#gh:gh_acme__widgets run", tag_catalog, monkeypatch)
        == "+widgets run"
    )
    assert _humanize_with_catalog("#git:bobby run", tag_catalog, monkeypatch) == (
        "+bob run"
    )


def test_tagify_never_rewrites_non_project_refs(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _humanize_with_catalog(
        "#gh:sase_fix_1 review", tag_catalog, monkeypatch
    ) == ("#gh:sase_fix_1 review")
    assert _humanize_with_catalog(
        "#gh:acme/widgets review", tag_catalog, monkeypatch
    ) == ("#gh:acme/widgets review")
    assert _humanize_with_catalog("#gh(sase) review", tag_catalog, monkeypatch) == (
        "#gh(sase) review"
    )
    assert _humanize_with_catalog("#gh:sase!! review", tag_catalog, monkeypatch) == (
        "#gh:sase!! review"
    )
    assert _humanize_with_catalog("#git:sase review", tag_catalog, monkeypatch) == (
        "#git:sase review"
    )


def test_tagify_keeps_refs_outside_tag_positions(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refs whose tag form would not re-parse keep ``#`` (D1 round-trip)."""
    assert _humanize_with_catalog("(#gh:sase)", tag_catalog, monkeypatch) == (
        "(#gh:sase)"
    )
    assert _humanize_with_catalog(
        "for #gh:sase, #git:bob", tag_catalog, monkeypatch
    ) == ("for #gh:sase, +bob")
    assert _humanize_with_catalog('"#gh:sase"', tag_catalog, monkeypatch) == (
        '"#gh:sase"'
    )
    # Tag positions still rewrite on the same line shapes.
    assert _humanize_with_catalog("(#gh:sase) #gh:sase", tag_catalog, monkeypatch) == (
        "(#gh:sase) +sase"
    )
    assert _humanize_with_catalog(
        "line one #gh:sase\nline two #git:bob", tag_catalog, monkeypatch
    ) == ("line one +sase\nline two +bob")


def test_tagify_leaves_fenced_refs_verbatim(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "```text\n#gh:sase fenced\n```\n#gh:sase live"
    assert _humanize_with_catalog(prompt, tag_catalog, monkeypatch) == (
        "```text\n#gh:sase fenced\n```\n+sase live"
    )


def test_tagify_flag_off_and_cold_catalog_keep_hash_form(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.project_aliases import humanize_project_refs_in_prompt

    assert (
        humanize_project_refs_in_prompt(
            "#gh:sase run",
            _DISPLAY_BY_KEY,
            project_tags=False,
        )
        == "#gh:sase run"
    )
    monkeypatch.setattr(
        "sase.project_alias_prompts._project_tag_targets_for_tagify",
        lambda _seam: (),
    )
    assert humanize_project_refs_in_prompt("#gh:sase run", _DISPLAY_BY_KEY) == (
        "#gh:sase run"
    )


# --- Known-target spelling ---------------------------------------------------


def test_known_project_tag_for_matches_key_name_and_alias(
    tag_catalog: ProjectTagCatalog,
) -> None:
    assert known_project_tag_for(tag_catalog, "sase") == "+sase"
    assert known_project_tag_for(tag_catalog, "SASE") == "+sase"
    assert known_project_tag_for(tag_catalog, "+sase") == "+sase"
    assert known_project_tag_for(tag_catalog, "bobby") == "+bob"
    assert known_project_tag_for(tag_catalog, "gh_acme__widgets") == "+widgets"


def test_known_project_tag_for_rejects_unknown_names(
    tag_catalog: ProjectTagCatalog,
) -> None:
    # Patch names and typos never gain a ``+`` spelling here (unlike
    # project_tag_for's generator fallback); callers fall back to ``#``.
    assert known_project_tag_for(tag_catalog, "some-patch") is None
    assert known_project_tag_for(tag_catalog, "ssae") is None
    assert known_project_tag_for(tag_catalog, "") is None

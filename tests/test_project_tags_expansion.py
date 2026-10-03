"""Expansion and launch-validation tests for the project-tag backend.

Split from ``tests.test_project_tags``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import sase.project_tags.catalog as tag_catalog_module
from sase.project_aliases import canonicalize_project_aliases_in_prompt
from sase.project_tags import (
    ProjectTagCatalog,
    ProjectTagError,
    effective_find_vcs_workflow_tag,
    effective_find_vcs_workflow_tag_with_catalog,
    effective_vcs_workflow_tag,
    effective_vcs_workflow_tag_with_catalog,
    expand_project_tags,
    find_project_tags,
    project_tag_for,
    validate_project_tags_for_launch,
)
from tests._project_tags_helpers import (
    patched_catalog,  # noqa: F401 (registers the autouse fixture)
    project_tag_catalog,  # noqa: F401 (registers the tag_catalog fixture)
)

__all__ = [
    "test_canonicalize_expands_tags_before_the_hash_guard",
    "test_effective_tags_resolve_before_extraction",
    "test_expand_ignores_non_tags",
    "test_expand_is_case_insensitive",
    "test_expand_leaves_unknown_tags_verbatim",
    "test_expand_rewrites_tag_to_canonical_key",
    "test_find_project_tags_reports_anchored_spans",
    "test_launch_toast_prefix_never_loads_catalog",
    "test_project_tag_for_spellings",
    "test_snapshot_effective_tags_never_load",
    "test_validate_alt_branches_are_separate_units",
    "test_validate_disabled_tag_errors",
    "test_validate_segments_are_separate_units",
    "test_validate_tag_plus_ref_errors",
    "test_validate_two_targets_in_one_unit_errors",
    "test_validate_unknown_anchored_suggests",
    "test_validate_unknown_unanchored_is_plain_text",
]


# --- Expansion -------------------------------------------------------------


def test_expand_rewrites_tag_to_canonical_key() -> None:
    assert expand_project_tags("+sase do x") == "#gh:sase do x"
    assert expand_project_tags("+widgets do x") == "#gh:gh_acme__widgets do x"


def test_expand_is_case_insensitive() -> None:
    assert expand_project_tags("+Sase do x") == "#gh:sase do x"


def test_expand_leaves_unknown_tags_verbatim() -> None:
    assert expand_project_tags("+ssae do x") == "+ssae do x"


def test_expand_ignores_non_tags() -> None:
    assert expand_project_tags("C++ and a+b") == "C++ and a+b"
    assert expand_project_tags("no plus here") == "no plus here"


def test_find_project_tags_reports_anchored_spans() -> None:
    assert find_project_tags("no plus here") == []
    (span,) = find_project_tags("+sase do x")
    assert span["name"] == "sase"
    assert span["anchored"] is True
    assert (span["start"], span["end"]) == (0, 5)


# --- Launch validation (D3) -------------------------------------------------


def test_validate_disabled_tag_errors() -> None:
    with pytest.raises(ProjectTagError, match="disabled"):
        validate_project_tags_for_launch("+beta do x")


def test_validate_unknown_anchored_suggests() -> None:
    with pytest.raises(ProjectTagError) as exc:
        validate_project_tags_for_launch("+ssae do x")
    message = str(exc.value)
    assert "Unknown project tag +ssae (line 1)." in message
    assert "Did you mean +sase" in message
    assert "Known:" in message
    assert "+sase" in message.split("Known:")[1]


def test_validate_unknown_unanchored_is_plain_text() -> None:
    validate_project_tags_for_launch("run chmod +x file")
    validate_project_tags_for_launch("fix the C++ build")


def test_validate_alt_branches_are_separate_units() -> None:
    validate_project_tags_for_launch("%{+sase | +bob} audit the README")


def test_validate_mid_word_alt_branches_are_separate_units() -> None:
    validate_project_tags_for_launch("go%{+sase | +bob}now")


def test_validate_nested_alt_branches_are_separate_units() -> None:
    validate_project_tags_for_launch("%{pick %{+sase | +bob} | +widgets} audit")


def test_validate_brace_text_does_not_close_alt_group() -> None:
    # A `{...}` span inside a branch is branch text, not the group close.
    validate_project_tags_for_launch("%{+sase {fast} | +bob} audit")


def test_validate_two_targets_in_one_unit_errors() -> None:
    with pytest.raises(
        ProjectTagError, match="Only one workspace target.*`\\+sase` and `\\+bob`"
    ):
        validate_project_tags_for_launch("+sase +bob do x")


def test_validate_segments_are_separate_units() -> None:
    validate_project_tags_for_launch("+sase do x\n---\n+bob do y")


def test_validate_tag_plus_ref_errors() -> None:
    from sase.macro import find_vcs_workflow_tag_span

    if find_vcs_workflow_tag_span("#git:bob ") is None:
        pytest.skip("git workflow provider is not installed")
    with pytest.raises(ProjectTagError, match="Only one workspace target"):
        validate_project_tags_for_launch("+sase #git:bob do x")


# --- Tag-aware helpers -------------------------------------------------------


def test_effective_tags_resolve_before_extraction() -> None:
    assert (effective_vcs_workflow_tag("+sase do x") or "").strip() == "#gh:sase"
    assert (effective_find_vcs_workflow_tag("do +sase x") or "").strip() == "#gh:sase"
    assert (effective_vcs_workflow_tag("#gh:sase do x") or "").strip() == "#gh:sase"


def test_snapshot_effective_tags_never_load(tag_catalog: ProjectTagCatalog) -> None:
    with patch.object(
        tag_catalog_module,
        "load_project_tag_catalog",
        side_effect=AssertionError("snapshot helper must not load"),
    ):
        warm = effective_vcs_workflow_tag_with_catalog("+sase do x", tag_catalog)
        assert (warm or "").strip() == "#gh:sase"
        found = effective_find_vcs_workflow_tag_with_catalog("do +sase x", tag_catalog)
        assert (found or "").strip() == "#gh:sase"
        # Cold catalog: no expansion, raw ``#`` extraction only.
        assert effective_vcs_workflow_tag_with_catalog("+sase do x", None) is None
        cold = effective_vcs_workflow_tag_with_catalog("#gh:sase do x", None)
        assert (cold or "").strip() == "#gh:sase"


def test_launch_toast_prefix_never_loads_catalog(
    tag_catalog: ProjectTagCatalog,
) -> None:
    from sase.ace.tui.actions.agent_workflow._launch_submit_helpers import (
        submitted_vcs_xprompt_prefix,
    )

    with (
        patch.object(
            tag_catalog_module,
            "load_project_tag_catalog",
            side_effect=AssertionError("must not load"),
        ),
        patch(
            "sase.project_tags.peek_project_tag_catalog",
            return_value=tag_catalog,
        ),
    ):
        assert submitted_vcs_xprompt_prefix("+sase do x") == "#gh:sase"
    with (
        patch.object(
            tag_catalog_module,
            "load_project_tag_catalog",
            side_effect=AssertionError("must not load"),
        ),
        patch("sase.project_tags.peek_project_tag_catalog", return_value=None),
    ):
        assert submitted_vcs_xprompt_prefix("+sase do x") is None


def test_project_tag_for_spellings() -> None:
    assert project_tag_for("sase") == "+sase"
    assert project_tag_for("+sase") == "+sase"
    assert project_tag_for("bob") == "+bob"
    assert project_tag_for("zzz") == "zzz"
    assert project_tag_for("+zzz") == "+zzz"
    assert project_tag_for("sase-core") == "sase-core"
    assert project_tag_for("1abc") == "1abc"


# --- Launch-query ordering ----------------------------------------------------


def test_canonicalize_expands_tags_before_the_hash_guard() -> None:
    """The ``#``-less fast path must still expand ``+`` tags (D4)."""
    with patch(
        "sase.project_tags.expand_project_tags",
        return_value="#gh:sase fix",
    ) as expand_mock:
        result = canonicalize_project_aliases_in_prompt("+sase fix")
    expand_mock.assert_called_once_with("+sase fix")
    assert "#" in result

"""Trigger and target-position tests for the project-tag backend.

Split from ``tests.test_project_tags``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.project_tags import (
    ProjectTagCatalog,
    ProjectTagError,
    apply_project_tag_selection,
    find_project_tag_trigger,
    validate_project_tags_with_catalog,
)
from tests._project_tags_helpers import (
    patched_catalog,  # noqa: F401 (registers the autouse fixture)
    project_tag_catalog,  # noqa: F401 (registers the tag_catalog fixture)
)

__all__ = [
    "test_apply_selection_accepts_pr_ref_spelling",
    "test_apply_selection_inserts_tag_at_leading_position",
    "test_apply_selection_keeps_other_segments",
    "test_apply_selection_replaces_existing_target_in_segment",
    "test_apply_selection_replaces_mid_line_target_and_drops_extra",
    "test_apply_selection_switches_projects",
    "test_apply_selection_uses_leading_position_without_target",
    "test_find_project_tag_trigger_at_d1_boundaries",
    "test_find_project_tag_trigger_rejects_non_triggers",
    "test_validate_with_catalog_allows_unanchored_unknown",
    "test_validate_with_catalog_rejects_disabled",
    "test_validate_with_catalog_rejects_two_targets",
    "test_validate_with_catalog_rejects_unknown_anchored",
]


# --- Core trigger ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    [
        ("+", 1, (0, 1, "")),
        ("+sa", 3, (0, 3, "sa")),
        ("Fix +bug", 8, (4, 8, "bug")),
        ("line\n +x", 8, (6, 8, "x")),
        ("\t+", 2, (1, 2, "")),
        ("%{+sa", 5, (2, 5, "sa")),
        ("%{a | +sa", 9, (6, 9, "sa")),
    ],
)
def test_find_project_tag_trigger_at_d1_boundaries(
    text: str, cursor: int, expected: tuple[int, int, str]
) -> None:
    trigger = find_project_tag_trigger(text, cursor)
    assert trigger is not None
    assert (trigger.start, trigger.end, trigger.query) == expected
    assert trigger.span == expected[:2]


@pytest.mark.parametrize(
    ("text", "cursor"),
    [
        ("a+b", 3),
        ("c++", 3),
        ("#+sa", 4),
        ("Fix #+sa", 8),
        ("hello world", 11),
        ("", 0),
        ("+", 0),
        ("+", 5),
        ("+", -1),
    ],
)
def test_find_project_tag_trigger_rejects_non_triggers(text: str, cursor: int) -> None:
    assert find_project_tag_trigger(text, cursor) is None


# --- Core target-position accept ----------------------------------------------


def _patched_workflows() -> object:
    return patch(
        "sase.workspace_provider.get_workflow_names", return_value={"gh", "git"}
    )


def test_apply_selection_inserts_tag_at_leading_position() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection("+", (0, 1), "+sase ")
    assert (text, cursor) == ("+sase ", len("+sase "))


def test_apply_selection_uses_leading_position_without_target() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection(
            "Describe this repo. +", (20, 21), "+sase "
        )
    assert text == "+sase Describe this repo. "
    assert cursor == len("+sase ")


def test_apply_selection_replaces_existing_target_in_segment() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection(
            "#git:foo Fix bug +", (17, 18), "+sase "
        )
    assert text == "+sase Fix bug "
    assert cursor == len("+sase ")


def test_apply_selection_replaces_mid_line_target_and_drops_extra() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection(
            "#git:foo #git:baz +", (18, 19), "+sase "
        )
    assert text == "+sase "
    assert cursor == len("+sase ")
    with _patched_workflows():
        text, cursor = apply_project_tag_selection(
            "Fix #git:foo bug +", (17, 18), "+sase "
        )
    assert text == "Fix +sase bug "
    assert cursor == len("Fix +sase ")


def test_apply_selection_switches_projects() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection("+sase do it +bo", (12, 15), "+bob ")
    assert text == "+bob do it "
    assert cursor == len("+bob ")


def test_apply_selection_keeps_other_segments() -> None:
    prompt = "#git:foo first\n---\n#git:baz second +"
    with _patched_workflows():
        text, _ = apply_project_tag_selection(
            prompt, (len(prompt) - 1, len(prompt)), "+sase "
        )
    assert text == "#git:foo first\n---\n+sase second "


def test_apply_selection_accepts_pr_ref_spelling() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection("Review +sh", (7, 10), "#gh:ship ")
    assert text == "#gh:ship Review "
    assert cursor == len("#gh:ship ")


# --- Warm-catalog validation -------------------------------------------------


def test_validate_with_catalog_rejects_unknown_anchored(
    tag_catalog: ProjectTagCatalog,
) -> None:
    with pytest.raises(ProjectTagError, match=r"Unknown project tag \+ssae"):
        validate_project_tags_with_catalog("+ssae do it", tag_catalog)


def test_validate_with_catalog_rejects_disabled(
    tag_catalog: ProjectTagCatalog,
) -> None:
    with pytest.raises(ProjectTagError, match="disabled"):
        validate_project_tags_with_catalog("+beta do it", tag_catalog)


def test_validate_with_catalog_allows_unanchored_unknown(
    tag_catalog: ProjectTagCatalog,
) -> None:
    validate_project_tags_with_catalog("run chmod +x-dependent fix", tag_catalog)


def test_validate_with_catalog_rejects_two_targets(
    tag_catalog: ProjectTagCatalog,
) -> None:
    with pytest.raises(ProjectTagError, match="Only one workspace target"):
        validate_project_tags_with_catalog("+sase +bob", tag_catalog)

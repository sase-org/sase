"""Xprompt save naming and post-save resolution rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.xprompt.loader_sources import load_xprompt_from_file
from sase.xprompt.naming import (
    ResolutionSource,
    is_inline_reference_name,
    is_inline_reference_name_char,
    markdown_save_plan,
    resolution_after_save,
    validate_snippet_trigger,
    validate_xprompt_name,
)
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import save_markdown_xprompt


@pytest.mark.parametrize(
    ("name", "error"),
    [
        ("", "required"),
        ("#review", "leading #"),
        ("two words", "Whitespace"),
        ("review.md", "extension"),
        ("review.yml", "extension"),
        ("/review", "start or end"),
        ("review/", "start or end"),
        ("review//fast", "segments"),
        ("review@fast", "Use only"),
    ],
)
def test_validate_xprompt_name_rejects_specific_invalid_forms(
    name: str, error: str
) -> None:
    assert error in (validate_xprompt_name(name) or "")


@pytest.mark.parametrize("name", ["review", "review-fast", "review.v2", "ns/foo"])
def test_validate_xprompt_name_accepts_supported_names(name: str) -> None:
    assert validate_xprompt_name(name) is None


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("review", True),
        ("review_2", True),
        ("namespace/review", True),
        ("2review", False),
        ("review-fast", False),
        ("review.v2", False),
        ("namespace//review", False),
    ],
)
def test_is_inline_reference_name_uses_runtime_grammar(
    name: str,
    valid: bool,
) -> None:
    assert is_inline_reference_name(name) is valid


@pytest.mark.parametrize(
    ("character", "valid"),
    [
        ("a", True),
        ("Z", True),
        ("2", True),
        ("_", True),
        ("/", True),
        (".", False),
        ("-", False),
        ("é", False),
        ("ab", False),
    ],
)
def test_is_inline_reference_name_char_is_ascii_only(
    character: str,
    valid: bool,
) -> None:
    assert is_inline_reference_name_char(character) is valid


def test_markdown_save_plan_stamps_namespaced_name_and_round_trips(
    tmp_path: Path,
) -> None:
    filename, frontmatter = markdown_save_plan(
        "ns/foo", PromptFrontmatter(description="Namespaced")
    )
    assert filename == "ns_foo.md"
    assert frontmatter.name == "ns/foo"

    path = tmp_path / filename
    save_markdown_xprompt(path, frontmatter, "body")
    loaded = load_xprompt_from_file(path)
    assert loaded is not None
    assert loaded.name == "ns/foo"


def test_markdown_save_plan_replaces_mismatched_and_strips_redundant_name() -> None:
    filename, corrected = markdown_save_plan("review", PromptFrontmatter(name="old"))
    assert filename == "review.md"
    assert corrected.name == "review"

    _, redundant = markdown_save_plan("review", PromptFrontmatter(name="review"))
    assert redundant.name is None


def test_resolution_after_save_reports_higher_and_lower_sources() -> None:
    sources = [
        ResolutionSource("high", True),
        ResolutionSource("target", False),
        ResolutionSource("low", True),
    ]
    result = resolution_after_save("target", sources)
    assert result.shadowed_by == "high"
    assert result.shadows == "low"


@pytest.mark.parametrize(
    ("name", "valid"),
    [("review", True), ("review_2", True), ("review-fast", False), ("", False)],
)
def test_validate_snippet_trigger_reuses_runtime_rule(name: str, valid: bool) -> None:
    assert (validate_snippet_trigger(name) is None) is valid

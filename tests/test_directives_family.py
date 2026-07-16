"""Tests for parallel agent-family prompt directives."""

from __future__ import annotations

import re

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("%family:sase-6g", "sase-6g"),
        ("%family:research.@.final", "research.@.final"),
        ("%family(sase-6g)", "sase-6g"),
        ("%f:research.@.final", "research.@.final"),
    ],
)
def test_family_directive_parses_target_and_default_role(
    source: str,
    target: str,
) -> None:
    cleaned, directives = extract_prompt_directives(f"{source}\nDo work")

    assert cleaned == "Do work"
    assert directives.family_target == target
    assert directives.family_role == "member"


def test_family_directive_parses_explicit_role_and_cleans_prompt() -> None:
    prompt = "%name:worker\n%family(research.@.final, role=researcher)\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "Do work"
    assert directives.name == "worker"
    assert directives.family_target == "research.@.final"
    assert directives.family_role == "researcher"


def test_family_directive_allows_plain_name_directive() -> None:
    _, directives = extract_prompt_directives("%n:worker\n%family:root\nDo work")

    assert directives.name == "worker"
    assert directives.family_target == "root"


@pytest.mark.parametrize(
    "source",
    ["%family", "%family:", "%family+", "%family()", "%family(role=phase)"],
)
def test_family_directive_rejects_empty_target(source: str) -> None:
    with pytest.raises(DirectiveError, match="requires a root-name argument"):
        extract_prompt_directives(f"{source}\nDo work")


def test_family_directive_rejects_duplicate_alias_occurrence() -> None:
    with pytest.raises(DirectiveError, match="Duplicate directive '%family'"):
        extract_prompt_directives("%family:root\n%f(other)\nDo work")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("%family(root, extra=value)", "Only role= is supported"),
        ("%family(root, other)", "exactly one positional root-name"),
        ("%family(root, role=a, role=b)", "Duplicate keyword argument 'role'"),
        ("%family(root, role=)", "role must be a bare token"),
        ("%family(root, role='phase worker')", "role must be a bare token"),
    ],
)
def test_family_directive_rejects_invalid_parenthesized_arguments(
    source: str,
    message: str,
) -> None:
    with pytest.raises(DirectiveError, match=re.escape(message)):
        extract_prompt_directives(f"{source}\nDo work")


def test_family_directive_conflicts_with_serial_family_attach() -> None:
    prompt = "%n(parent, reviewer)\n%family:root\nDo work"

    with pytest.raises(DirectiveError, match="Cannot combine %family with %n"):
        extract_prompt_directives(prompt)


def test_family_directive_inside_fenced_block_is_ignored() -> None:
    prompt = "```text\n%family:example\n```\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.family_target is None
    assert directives.family_role is None


def test_family_directive_inside_disabled_region_is_ignored() -> None:
    prompt = "%xprompts_enabled:false\n%family:example\n%xprompts_enabled:true\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "%family:example\nDo work"
    assert directives.family_target is None
    assert directives.family_role is None
